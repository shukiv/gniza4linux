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

from tui.backend import start_cli_background

MAX_OUTPUT_LINES = 10_000
FINISHED_JOB_TTL_HOURS = 24


def _work_dir() -> Path:
    if os.geteuid() == 0:
        return Path("/usr/local/gniza/workdir")
    state_home = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(state_home) / "gniza" / "workdir"


REGISTRY_FILE = _work_dir() / "gniza-jobs.json"


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
        self._jobs = {k: v for k, v in self._jobs.items() if v.status == "running"}
        self._save_registry()

    def start_job(self, app, job: Job, *cli_args: str) -> None:
        task = asyncio.create_task(self.run_job(app, job, *cli_args))
        job._tail_task = task  # prevent GC of the asyncio task

    async def run_job(self, app, job: Job, *cli_args: str) -> int:
        log_path = _work_dir() / f"gniza-job-{job.id}.log"
        job._log_file = str(log_path)
        proc = start_cli_background(*cli_args, log_file=str(log_path))
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
                        await asyncio.sleep(0.2)
                # Read remaining lines after process exit
                for line in f:
                    text = line.rstrip("\n")
                    if len(job.output) < MAX_OUTPUT_LINES:
                        job.output.append(text)
            rc = proc.returncode if proc.returncode is not None else 1
            job.return_code = rc
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
        # Reconnected jobs: use stored PID/PGID
        if job._reconnected and job._pid:
            try:
                pgid = job._pgid or os.getpgid(job._pid)
                os.killpg(pgid, signal.SIGKILL)
                return f"killed pgid={pgid} (pid={job._pid})"
            except (ProcessLookupError, PermissionError, OSError) as e:
                try:
                    os.kill(job._pid, signal.SIGKILL)
                    return f"fallback kill pid={job._pid} ({e})"
                except (ProcessLookupError, OSError) as e2:
                    return f"failed: {e}, {e2}"
        if job._proc is None:
            return f"proc is None (status={job.status})"
        pid = job._proc.pid
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
            return f"killed pgid={pgid} (pid={pid})"
        except (ProcessLookupError, PermissionError, OSError) as e:
            try:
                job._proc.kill()
                return f"fallback kill pid={pid} ({e})"
            except (ProcessLookupError, OSError) as e2:
                return f"failed: {e}, {e2}"

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
            # Skip finished jobs older than TTL
            if job.status != "running" and job.finished_at:
                age_hours = (now - job.finished_at).total_seconds() / 3600
                if age_hours > FINISHED_JOB_TTL_HOURS:
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

            # Already-finished job from a previous session
            if saved_status != "running":
                finished_at_str = entry.get("finished_at")
                finished_at = datetime.fromisoformat(finished_at_str) if finished_at_str else now
                age_hours = (now - finished_at).total_seconds() / 3600
                if age_hours > FINISHED_JOB_TTL_HOURS:
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
            try:
                os.kill(pid, 0)
                alive = True
            except ProcessLookupError:
                pass
            except PermissionError:
                # Process exists but we can't signal it
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
                # Process finished while TUI was closed — check log for exit info
                rc = self._detect_return_code(entry.get("log_file"))
                if rc is None:
                    status = "unknown"
                else:
                    status = "success" if rc == 0 else "failed"
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
            self._jobs[job.id] = job
        self._save_registry()

    @staticmethod
    def _detect_return_code(log_file: str | None) -> int | None:
        """Try to determine exit code from log file content.

        Returns 0 for success, 1 for detected failure, None if unknown.
        """
        if not log_file or not Path(log_file).is_file():
            return None
        try:
            text = Path(log_file).read_text()
            if not text.strip():
                return None
            for marker in ("FATAL:", "ERROR:", "failed", "Failed"):
                if marker in text:
                    return 1
            # Look for success indicators
            if "completed" in text.lower() or "Backup Summary" in text:
                return 0
        except OSError:
            return None
        return None

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
                rc = self._detect_return_code(job._log_file)
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
        except (asyncio.CancelledError, KeyboardInterrupt):
            # TUI shutting down — keep job as running for next reconnect
            raise
        except Exception:
            pass
        finally:
            job._tail_task = None

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
                rc = self._detect_return_code(job._log_file)
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
