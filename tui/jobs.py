import asyncio
import os
import signal
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from textual.message import Message

from tui.backend import start_cli_process

MAX_OUTPUT_LINES = 10_000


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


class JobManager:

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

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

    async def run_job(self, app, job: Job, *cli_args: str) -> int:
        proc = await start_cli_process(*cli_args)
        job._proc = proc
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

    def kill_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job._proc is None:
            return False
        self._kill_process_group(job._proc)
        return True

    def kill_running(self) -> None:
        for job in self._jobs.values():
            if job._proc is not None:
                self._kill_process_group(job._proc)


job_manager = JobManager()
