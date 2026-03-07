import json
import os
import signal
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from web.backend import start_cli_background

MAX_OUTPUT_LINES = 10_000
FINISHED_JOB_TTL_HOURS = 24


def _work_dir():
    if os.geteuid() == 0:
        return Path("/usr/local/gniza/workdir")
    state_home = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(state_home) / "gniza" / "workdir"


REGISTRY_FILE = _work_dir() / "gniza-jobs.json"


@dataclass
class WebJob:
    id: str
    kind: str
    label: str
    status: str = "running"
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None
    return_code: int | None = None
    pid: int | None = None
    pgid: int | None = None
    log_file: str | None = None


class WebJobManager:
    """Sync job manager for Flask. Shares registry with TUI JobManager."""

    def __init__(self):
        self._jobs = {}
        self.load_registry()

    def create_and_start(self, kind, label, *cli_args):
        """Create a job, start the CLI process, save to registry. Returns the job."""
        job_id = uuid.uuid4().hex[:8]
        log_path = _work_dir() / f"gniza-job-{job_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        proc = start_cli_background(*cli_args, log_file=str(log_path))

        job = WebJob(
            id=job_id, kind=kind, label=label,
            pid=proc.pid, log_file=str(log_path)
        )
        try:
            job.pgid = os.getpgid(proc.pid)
        except OSError:
            pass

        self._jobs[job_id] = job
        self._save_registry()
        return job

    def get_job(self, job_id):
        self.load_registry()
        return self._jobs.get(job_id)

    def list_jobs(self):
        self.load_registry()
        return list(self._jobs.values())

    def running_count(self):
        self.load_registry()
        return sum(1 for j in self._jobs.values() if j.status == "running")

    def kill_job(self, job_id):
        job = self._jobs.get(job_id)
        if not job or not job.pid:
            return "not found"
        try:
            pgid = job.pgid or os.getpgid(job.pid)
            os.killpg(pgid, signal.SIGKILL)
            return "killed"
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(job.pid, signal.SIGKILL)
                return "killed"
            except Exception:
                return "failed"

    def remove_finished(self):
        self._jobs = {k: v for k, v in self._jobs.items() if v.status == "running"}
        self._save_registry()

    def get_log_lines(self, job_id, offset=0):
        """Read log file from offset line. Returns (lines, total_lines)."""
        job = self._jobs.get(job_id)
        if not job or not job.log_file:
            return [], 0
        try:
            with open(job.log_file) as f:
                all_lines = f.readlines()
            total = len(all_lines)
            new_lines = [l.rstrip('\n') for l in all_lines[offset:]]
            return new_lines, total
        except (OSError, FileNotFoundError):
            return [], 0

    def load_registry(self):
        """Load jobs from shared JSON registry."""
        if not REGISTRY_FILE.is_file():
            return
        try:
            entries = json.loads(REGISTRY_FILE.read_text())
        except Exception:
            return
        now = datetime.now()
        changed = False
        refreshed = {}
        for entry in entries:
            job_id = entry["id"]
            status = entry.get("status", "running")
            pid = entry.get("pid")

            # Check if running process is still alive
            if status == "running" and pid:
                alive = True
                rc = None
                # Try to reap zombie child (works if we're the parent)
                try:
                    wpid, wstatus = os.waitpid(pid, os.WNOHANG)
                    if wpid != 0:
                        alive = False
                        if os.WIFEXITED(wstatus):
                            rc = os.WEXITSTATUS(wstatus)
                        elif os.WIFSIGNALED(wstatus):
                            rc = 1
                        else:
                            rc = self._detect_return_code(entry.get("log_file"))
                except ChildProcessError:
                    # Not our child — fall back to kill-0 check
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        alive = False
                        rc = self._detect_return_code(entry.get("log_file"))
                    except PermissionError:
                        pass  # alive but can't signal
                if not alive:
                    if rc is None:
                        rc = self._detect_return_code(entry.get("log_file"))
                    status = "success" if rc == 0 else "failed" if rc else "unknown"
                    entry["status"] = status
                    entry["return_code"] = rc
                    entry["finished_at"] = now.isoformat()
                    changed = True

            # Skip expired finished jobs
            if status != "running":
                fin = entry.get("finished_at")
                if fin:
                    try:
                        age = (now - datetime.fromisoformat(fin)).total_seconds() / 3600
                        if age > FINISHED_JOB_TTL_HOURS:
                            changed = True
                            continue
                    except Exception:
                        pass

            job = WebJob(
                id=job_id,
                kind=entry.get("kind", "backup"),
                label=entry.get("label", "Job"),
                status=status,
                started_at=datetime.fromisoformat(entry.get("started_at", now.isoformat())),
                finished_at=datetime.fromisoformat(entry["finished_at"]) if entry.get("finished_at") else None,
                return_code=entry.get("return_code"),
                pid=pid,
                pgid=entry.get("pgid"),
                log_file=entry.get("log_file"),
            )
            refreshed[job_id] = job
        self._jobs = refreshed
        if changed:
            self._save_registry()

    def _save_registry(self):
        entries = []
        for job in self._jobs.values():
            entry = {
                "id": job.id, "kind": job.kind, "label": job.label,
                "status": job.status, "return_code": job.return_code,
                "started_at": job.started_at.isoformat(),
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                "log_file": job.log_file,
            }
            if job.status == "running" and job.pid:
                entry["pid"] = job.pid
                entry["pgid"] = job.pgid
            entries.append(entry)
        try:
            REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            REGISTRY_FILE.write_text(json.dumps(entries, indent=2))
        except OSError:
            pass

    @staticmethod
    def _detect_return_code(log_file):
        if not log_file or not Path(log_file).is_file():
            return None
        try:
            text = Path(log_file).read_text()
            if not text.strip():
                return None
            if "Backup completed" in text or "Backup Summary" in text:
                return 0
            for line in text.splitlines():
                if "[FATAL]" in line or "[ERROR]" in line:
                    return 1
            # Process exited, log has content, no error markers → success
            return 0
        except OSError:
            return None
        return None


# Module-level singleton
web_job_manager = WebJobManager()
