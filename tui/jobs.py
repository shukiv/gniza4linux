import asyncio
import json
import os
import signal
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from textual.message import Message

from tui.backend import start_cli_process

MAX_OUTPUT_LINES = 10_000


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
    _proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
    _pid: int | None = field(default=None, repr=False)
    _pgid: int | None = field(default=None, repr=False)
    _reconnected: bool = field(default=False, repr=False)


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
        asyncio.create_task(self.run_job(app, job, *cli_args))

    async def run_job(self, app, job: Job, *cli_args: str) -> int:
        proc = await start_cli_process(*cli_args)
        job._proc = proc
        job._pid = proc.pid
        try:
            job._pgid = os.getpgid(proc.pid)
        except OSError:
            job._pgid = None
        self._save_registry()
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode().rstrip("\n")
                if len(job.output) < MAX_OUTPUT_LINES:
                    job.output.append(text)
            await proc.wait()
            rc = proc.returncode if proc.returncode is not None else 1
            job.return_code = rc
            job.status = "success" if rc == 0 else "failed"
        except Exception:
            job.status = "failed"
            job.return_code = job.return_code if job.return_code is not None else 1
        finally:
            job.finished_at = datetime.now()
            job._proc = None
            job._reconnected = False
            self._save_registry()
            rc = job.return_code if job.return_code is not None else 1
            app.post_message(JobFinished(job.id, rc))
        return job.return_code if job.return_code is not None else 1

    @staticmethod
    def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
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
        for job in self._jobs.values():
            if job.status != "running":
                continue
            pid = job._pid
            if job._proc is not None:
                pid = job._proc.pid
            if pid is None:
                continue
            entries.append({
                "id": job.id,
                "kind": job.kind,
                "label": job.label,
                "pid": pid,
                "pgid": job._pgid,
                "started_at": job.started_at.isoformat(),
            })
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
        for entry in entries:
            pid = entry.get("pid")
            if pid is None:
                continue
            # Check if process is still alive
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                continue
            job_id = entry["id"]
            if job_id in self._jobs:
                continue
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
            self._jobs[job.id] = job

    def check_reconnected(self) -> None:
        changed = False
        for job in list(self._jobs.values()):
            if not job._reconnected or job.status != "running":
                continue
            if job._pid is None:
                continue
            try:
                os.kill(job._pid, 0)
            except ProcessLookupError:
                job.status = "success"
                job.finished_at = datetime.now()
                job._reconnected = False
                changed = True
            except PermissionError:
                pass  # Process exists but we can't signal it
        if changed:
            self._save_registry()


job_manager = JobManager()
