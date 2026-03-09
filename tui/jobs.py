import asyncio
import json
import os
import signal
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from textual.message import Message

from lib.job_utils import detect_return_code, is_skipped_job
from tui.backend import start_cli_background
from tui.config import get_log_retain_days, get_max_concurrent_jobs, WORK_DIR, LOG_DIR

MAX_OUTPUT_LINES = 10_000


REGISTRY_FILE = WORK_DIR / "gniza-jobs.json"


class JobFinished(Message):
    def __init__(self, job_id: str, return_code: int) -> None:
        super().__init__()
        self.job_id = job_id
        self.return_code = return_code


@dataclass
class Job:
    id: str
    kind: str
    label: str
    status: str = "running"
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None
    return_code: int | None = None
    output: list[str] = field(default_factory=list)
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _pid: int | None = field(default=None, repr=False)
    _pgid: int | None = field(default=None, repr=False)
    _reconnected: bool = field(default=False, repr=False)
    _log_file: str | None = field(default=None, repr=False)
    _cli_args: tuple[str, ...] | None = field(default=None, repr=False)
    _tail_task: asyncio.Task | None = field(default=None, repr=False)


class JobManager:

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._load_registry()

    def create_job(self, kind: str, label: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:8], kind=kind, label=label)
        self._jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        return list(self._jobs.values())

    def running_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status == "running")

    def remove_finished(self) -> None:
        for job in self._jobs.values():
            if job.status not in ("running", "queued") and job._log_file:
                try:
                    Path(job._log_file).unlink(missing_ok=True)
                except OSError:
                    pass
        self._jobs = {k: v for k, v in self._jobs.items() if v.status in ("running", "queued")}
        self._save_registry()

    def start_job(self, app, job: Job, *cli_args: str) -> None:
        max_jobs = get_max_concurrent_jobs()
        if max_jobs > 0 and self.running_count() >= max_jobs:
            job.status = "queued"
            job._cli_args = cli_args
            self._save_registry()
            return
        task = asyncio.create_task(self.run_job(app, job, *cli_args))
        job._tail_task = task  # prevent GC of the asyncio task

    def _dispatch_queue(self, app) -> None:
        """Start queued jobs if under the concurrency limit."""
        max_jobs = get_max_concurrent_jobs()
        for job in sorted(self._jobs.values(), key=lambda j: j.started_at):
            if job.status != "queued" or job._cli_args is None:
                continue
            if max_jobs > 0 and self.running_count() >= max_jobs:
                break
            job.status = "running"
            cli_args = job._cli_args
            job._cli_args = None
            task = asyncio.create_task(self.run_job(app, job, *cli_args))
            job._tail_task = task

    async def run_job(self, app, job: Job, *cli_args: str) -> int:
        log_path = LOG_DIR / f"gniza-job-{job.id}.log"
        job._log_file = str(log_path)
        proc = start_cli_background(*cli_args, log_file=str(log_path), job_id=job.id)
        job._proc = proc
        job._pid = proc.pid
        try:
            job._pgid = os.getpgid(proc.pid)
        except OSError:
            job._pgid = None
        self._save_registry()
        try:
            # Poll process and tail log file
            with open(log_path, "r") as f:
                while proc.poll() is None:
                    line = f.readline()
                    if line:
                        text = line.rstrip("\n")
                        if len(job.output) < MAX_OUTPUT_LINES:
                            job.output.append(text)
                    else:
                        # Fallback: directly reap zombie via waitpid
                        # (proc.poll() can fail in asyncio/Textual context)
                        try:
                            wpid, wstatus = os.waitpid(proc.pid, os.WNOHANG)
                            if wpid != 0:
                                if os.WIFEXITED(wstatus):
                                    proc.returncode = os.WEXITSTATUS(wstatus)
                                elif os.WIFSIGNALED(wstatus):
                                    proc.returncode = -os.WTERMSIG(wstatus)
                                else:
                                    proc.returncode = 1
                                break
                        except ChildProcessError:
                            # Already reaped
                            break
                        await asyncio.sleep(0.2)
                # Read remaining lines after process exit
                for line in f:
                    text = line.rstrip("\n")
                    if len(job.output) < MAX_OUTPUT_LINES:
                        job.output.append(text)
            rc = proc.returncode
            if rc is None:
                # proc.poll() missed the exit — try one more wait
                try:
                    proc.wait(timeout=1)
                    rc = proc.returncode
                except Exception:
                    pass
            if rc is None:
                # Fall back to log-based detection
                rc = detect_return_code(str(log_path))
                if rc is None:
                    rc = 1
            job.return_code = rc
            if rc == 0 and is_skipped_job(job.output):
                job.status = "skipped"
            else:
                job.status = "success" if rc == 0 else "failed"
        except (asyncio.CancelledError, KeyboardInterrupt):
            # TUI is shutting down — keep status as "running" so the job
            # stays in the registry for reconnection on next launch.
            self._save_registry()
            raise
        except Exception:
            job.status = "failed"
            job.return_code = job.return_code if job.return_code is not None else 1
        finally:
            if job.status != "running":
                job.finished_at = datetime.now()
            job._proc = None
            job._reconnected = False
            self._save_registry()
            rc = job.return_code if job.return_code is not None else 1
            try:
                app.post_message(JobFinished(job.id, rc))
            except Exception:
                pass
            self._dispatch_queue(app)
        return job.return_code if job.return_code is not None else 1

    @staticmethod
    def _kill_process_group(proc: subprocess.Popen) -> None:
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass

    def kill_job(self, job_id: str) -> str:
        """Kill a job. Returns a status message for debugging."""
        job = self._jobs.get(job_id)
        if not job:
            return "job not found"
        # Queued job: just cancel it
        if job.status == "queued":
            job.status = "failed"
            job.return_code = -9
            job.finished_at = datetime.now()
            job._cli_args = None
            self._save_registry()
            return "cancelled queued job"
        msg = ""
        # Reconnected jobs: use stored PID/PGID
        if job._reconnected and job._pid:
            try:
                pgid = job._pgid or os.getpgid(job._pid)
                os.killpg(pgid, signal.SIGKILL)
                msg = f"killed pgid={pgid} (pid={job._pid})"
            except (ProcessLookupError, PermissionError, OSError) as e:
                try:
                    os.kill(job._pid, signal.SIGKILL)
                    msg = f"fallback kill pid={job._pid} ({e})"
                except (ProcessLookupError, OSError) as e2:
                    msg = f"failed: {e}, {e2}"
        elif job._proc is not None:
            pid = job._proc.pid
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGKILL)
                msg = f"killed pgid={pgid} (pid={pid})"
            except (ProcessLookupError, PermissionError, OSError) as e:
                try:
                    job._proc.kill()
                    msg = f"fallback kill pid={pid} ({e})"
                except (ProcessLookupError, OSError) as e2:
                    msg = f"failed: {e}, {e2}"
        else:
            msg = f"proc is None (status={job.status})"
        # Always mark the job as finished after kill attempt
        if job.status == "running":
            job.status = "failed"
            job.return_code = -9
            job.finished_at = datetime.now()
            job._reconnected = False
            if job._tail_task:
                job._tail_task.cancel()
                job._tail_task = None
            self._save_registry()
        return msg

    def kill_running(self) -> None:
        for job in self._jobs.values():
            if job._proc is not None:
                self._kill_process_group(job._proc)
            elif job._reconnected and job._pid:
                try:
                    pgid = job._pgid or os.getpgid(job._pid)
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    try:
                        os.kill(job._pid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        pass

    # ── Job Registry Persistence ─────────────────────────────

    def _save_registry(self) -> None:
        entries = []
        now = datetime.now()
        for job in self._jobs.values():
            # Skip finished jobs older than LOG_RETAIN
            if job.status not in ("running", "queued") and job.finished_at:
                age_days = (now - job.finished_at).total_seconds() / 86400
                if age_days > get_log_retain_days():
                    if job._log_file:
                        try:
                            Path(job._log_file).unlink(missing_ok=True)
                        except OSError:
                            pass
                    continue
            pid = job._pid
            if job._proc is not None:
                pid = job._proc.pid
            entry = {
                "id": job.id,
                "kind": job.kind,
                "label": job.label,
                "status": job.status,
                "return_code": job.return_code,
                "started_at": job.started_at.isoformat(),
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                "log_file": job._log_file,
            }
            if job.status == "running" and pid is not None:
                entry["pid"] = pid
                entry["pgid"] = job._pgid
            if job.status == "queued" and job._cli_args:
                entry["cli_args"] = list(job._cli_args)
            entries.append(entry)
        try:
            REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            REGISTRY_FILE.write_text(json.dumps(entries, indent=2))
        except OSError:
            pass

    def _load_registry(self) -> None:
        if not REGISTRY_FILE.is_file():
            return
        try:
            entries = json.loads(REGISTRY_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return
        now = datetime.now()
        for entry in entries:
            job_id = entry["id"]
            if job_id in self._jobs:
                continue
            saved_status = entry.get("status", "running")
            pid = entry.get("pid")

            if saved_status == "queued":
                job = Job(
                    id=job_id,
                    kind=entry.get("kind", "backup"),
                    label=entry.get("label", "Job"),
                    status="queued",
                    started_at=datetime.fromisoformat(entry["started_at"]),
                )
                job._log_file = entry.get("log_file")
                cli_args = entry.get("cli_args")
                if cli_args:
                    job._cli_args = tuple(cli_args)
                self._jobs[job.id] = job
                continue

            # Already-finished job from a previous session
            if saved_status != "running":
                finished_at_str = entry.get("finished_at")
                finished_at = datetime.fromisoformat(finished_at_str) if finished_at_str else now
                age_days = (now - finished_at).total_seconds() / 86400
                if age_days > get_log_retain_days():
                    log_file = entry.get("log_file")
                    if log_file:
                        try:
                            Path(log_file).unlink(missing_ok=True)
                        except OSError:
                            pass
                    continue
                job = Job(
                    id=job_id,
                    kind=entry.get("kind", "backup"),
                    label=entry.get("label", "Job"),
                    status=saved_status,
                    started_at=datetime.fromisoformat(entry["started_at"]),
                    finished_at=finished_at,
                    return_code=entry.get("return_code"),
                )
                job._log_file = entry.get("log_file")
                if job._log_file and Path(job._log_file).is_file():
                    try:
                        lines = Path(job._log_file).read_text().splitlines()
                        job.output = lines[:MAX_OUTPUT_LINES]
                    except OSError:
                        pass
                self._jobs[job.id] = job
                continue

            # Running job — check if process is still alive
            if pid is None:
                continue
            alive = False
            rc_from_wait = None
            # Try to reap zombie child first (works if we're the parent)
            try:
                wpid, wstatus = os.waitpid(pid, os.WNOHANG)
                if wpid != 0:
                    alive = False
                    if os.WIFEXITED(wstatus):
                        rc_from_wait = os.WEXITSTATUS(wstatus)
                    elif os.WIFSIGNALED(wstatus):
                        rc_from_wait = 1
                else:
                    alive = True
            except ChildProcessError:
                # Not our child — fall back to kill-0 check
                try:
                    os.kill(pid, 0)
                    alive = True
                except ProcessLookupError:
                    pass
                except PermissionError:
                    alive = True
            if alive:
                job = Job(
                    id=job_id,
                    kind=entry.get("kind", "backup"),
                    label=entry.get("label", f"Job (PID {pid})"),
                    status="running",
                    started_at=datetime.fromisoformat(entry["started_at"]),
                )
                job._pid = pid
                job._pgid = entry.get("pgid")
                job._reconnected = True
            else:
                # Process finished while TUI was closed
                rc = rc_from_wait if rc_from_wait is not None else detect_return_code(entry.get("log_file"))
                if rc is None:
                    status = "unknown"
                elif rc == 0:
                    status = "success"
                else:
                    status = "failed"
                job = Job(
                    id=job_id,
                    kind=entry.get("kind", "backup"),
                    label=entry.get("label", f"Job (PID {pid})"),
                    status=status,
                    started_at=datetime.fromisoformat(entry["started_at"]),
                    finished_at=now,
                    return_code=rc,
                )
            job._log_file = entry.get("log_file")
            # Load output from log file
            if job._log_file and Path(job._log_file).is_file():
                try:
                    lines = Path(job._log_file).read_text().splitlines()
                    job.output = lines[:MAX_OUTPUT_LINES]
                except OSError:
                    pass
            # Detect skipped after loading output
            if job.status == "success" and is_skipped_job(job.output):
                job.status = "skipped"
            self._jobs[job.id] = job
        self._save_registry()

    def start_tailing_reconnected(self, app) -> None:
        """Start log file tailing tasks for all reconnected running jobs."""
        for job in self._jobs.values():
            if job._reconnected and job.status == "running" and job._tail_task is None:
                job._tail_task = asyncio.create_task(
                    self._tail_reconnected(app, job)
                )

    async def _tail_reconnected(self, app, job: Job) -> None:
        """Tail the log file and monitor PID for a reconnected job."""
        try:
            log_path = job._log_file
            if not log_path or not Path(log_path).is_file():
                # No log file — just poll PID
                while job.status == "running":
                    if not job._pid:
                        break
                    try:
                        os.kill(job._pid, 0)
                    except ProcessLookupError:
                        break
                    except PermissionError:
                        pass
                    await asyncio.sleep(1)
            else:
                with open(log_path, "r") as f:
                    # Seek to end of already-loaded content
                    f.seek(0, 2)
                    while job.status == "running":
                        line = f.readline()
                        if line:
                            text = line.rstrip("\n")
                            if len(job.output) < MAX_OUTPUT_LINES:
                                job.output.append(text)
                        else:
                            # Check if process is still alive
                            if job._pid:
                                try:
                                    os.kill(job._pid, 0)
                                except ProcessLookupError:
                                    break
                                except PermissionError:
                                    pass
                            await asyncio.sleep(0.3)
                    # Read remaining lines after process exit
                    for line in f:
                        text = line.rstrip("\n")
                        if len(job.output) < MAX_OUTPUT_LINES:
                            job.output.append(text)
            # Process finished
            if job.status == "running":
                rc = detect_return_code(job._log_file)
                job.return_code = rc
                if rc is None:
                    job.status = "unknown"
                else:
                    job.status = "success" if rc == 0 else "failed"
                job.finished_at = datetime.now()
                job._reconnected = False
                self._save_registry()
                try:
                    app.post_message(JobFinished(job.id, rc or 0))
                except Exception:
                    pass
                self._dispatch_queue(app)
        except (asyncio.CancelledError, KeyboardInterrupt):
            # TUI shutting down — keep job as running for next reconnect
            raise
        except Exception:
            pass
        finally:
            job._tail_task = None

    def reload_registry(self) -> None:
        """Re-read the registry file to pick up jobs created externally."""
        if not REGISTRY_FILE.is_file():
            return
        try:
            entries = json.loads(REGISTRY_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return
        now = datetime.now()
        registry_ids = set()
        for entry in entries:
            job_id = entry["id"]
            registry_ids.add(job_id)
            existing = self._jobs.get(job_id)

            # Skip jobs we're actively managing (have a live proc or tail task)
            if existing and (existing._proc is not None or existing._tail_task is not None):
                continue

            saved_status = entry.get("status", "running")
            pid = entry.get("pid")

            # New job not in our dict — add it
            if not existing:
                if saved_status == "queued":
                    job = Job(
                        id=job_id,
                        kind=entry.get("kind", "backup"),
                        label=entry.get("label", "Job"),
                        status="queued",
                        started_at=datetime.fromisoformat(entry["started_at"]),
                    )
                    job._log_file = entry.get("log_file")
                    cli_args = entry.get("cli_args")
                    if cli_args:
                        job._cli_args = tuple(cli_args)
                    self._jobs[job.id] = job
                    continue

                if saved_status == "running" and pid:
                    # Check if process is alive
                    alive = False
                    try:
                        os.kill(pid, 0)
                        alive = True
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        alive = True

                    if alive:
                        job = Job(
                            id=job_id,
                            kind=entry.get("kind", "backup"),
                            label=entry.get("label", f"Job (PID {pid})"),
                            status="running",
                            started_at=datetime.fromisoformat(entry["started_at"]),
                        )
                        job._pid = pid
                        job._pgid = entry.get("pgid")
                        job._reconnected = True
                        job._log_file = entry.get("log_file")
                        self._jobs[job.id] = job
                        continue
                    else:
                        saved_status = "unknown"  # will be refined below

                # Finished job (or running that died)
                if saved_status not in ("running", "queued"):
                    finished_at_str = entry.get("finished_at")
                    finished_at = datetime.fromisoformat(finished_at_str) if finished_at_str else now
                    age_days = (now - finished_at).total_seconds() / 86400
                    if age_days > get_log_retain_days():
                        continue
                    job = Job(
                        id=job_id,
                        kind=entry.get("kind", "backup"),
                        label=entry.get("label", "Job"),
                        status=saved_status,
                        started_at=datetime.fromisoformat(entry["started_at"]),
                        finished_at=finished_at,
                        return_code=entry.get("return_code"),
                    )
                    job._log_file = entry.get("log_file")
                    self._jobs[job.id] = job
                    continue

            # Existing job — update status if changed externally
            if existing and existing.status != saved_status:
                if saved_status not in ("running", "queued"):
                    existing.status = saved_status
                    existing.return_code = entry.get("return_code")
                    finished_at_str = entry.get("finished_at")
                    if finished_at_str:
                        existing.finished_at = datetime.fromisoformat(finished_at_str)

        # Remove jobs that are no longer in the registry (cleared externally)
        # but only if they're not actively managed by this TUI instance
        for job_id in list(self._jobs):
            if job_id not in registry_ids:
                job = self._jobs[job_id]
                if job._proc is None and job._tail_task is None:
                    del self._jobs[job_id]

    def check_reconnected(self) -> None:
        changed = False
        for job in list(self._jobs.values()):
            if not job._reconnected or job.status != "running":
                continue
            # Skip jobs that have an active tail task
            if job._tail_task is not None:
                continue
            if job._pid is None:
                continue
            try:
                os.kill(job._pid, 0)
            except ProcessLookupError:
                rc = detect_return_code(job._log_file)
                job.return_code = rc
                if rc is None:
                    job.status = "unknown"
                else:
                    job.status = "success" if rc == 0 else "failed"
                job.finished_at = datetime.now()
                job._reconnected = False
                changed = True
            except PermissionError:
                pass  # Process exists but we can't signal it
        if changed:
            self._save_registry()


job_manager = JobManager()
