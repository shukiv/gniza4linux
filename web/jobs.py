import fcntl
import json
import os
import re
import signal
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import logging
import subprocess

from tui.config import (
    get_log_retain_days, get_max_concurrent_jobs, CONFIG_DIR, parse_conf,
    list_conf_dir, WORK_DIR, LOG_DIR,
)
from web.backend import start_cli_background

logger = logging.getLogger(__name__)

MAX_OUTPUT_LINES = 10_000


REGISTRY_FILE = WORK_DIR / "gniza-jobs.json"


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
    cli_args: tuple[str, ...] | None = None


class WebJobManager:
    """Sync job manager for Flask. Shares registry with TUI JobManager."""

    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()
        self.load_registry()

    def create_and_start(self, kind, label, *cli_args):
        """Create a job. If under concurrency limit, start it; otherwise queue it."""
        with self._lock:
            job_id = uuid.uuid4().hex[:8]
            log_path = LOG_DIR / f"gniza-job-{job_id}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)

            max_jobs = get_max_concurrent_jobs()
            if max_jobs > 0 and self._running_count_internal() >= max_jobs:
                job = WebJob(
                    id=job_id, kind=kind, label=label,
                    status="queued", log_file=str(log_path),
                    cli_args=cli_args,
                )
                self._jobs[job_id] = job
                self._save_registry()
                return job

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

    def _running_count_internal(self):
        """Count running jobs without reloading registry (avoids recursion)."""
        return sum(1 for j in self._jobs.values() if j.status == "running")

    def _dispatch_queue(self):
        """Start queued jobs if under the concurrency limit."""
        with self._lock:
            max_jobs = get_max_concurrent_jobs()
            started = False
            for job in sorted(self._jobs.values(), key=lambda j: j.started_at):
                if job.status != "queued" or not job.cli_args:
                    continue
                if max_jobs > 0 and self._running_count_internal() >= max_jobs:
                    break
                proc = start_cli_background(*job.cli_args, log_file=job.log_file)
                job.status = "running"
                job.pid = proc.pid
                try:
                    job.pgid = os.getpgid(proc.pid)
                except OSError:
                    pass
                job.cli_args = None
                started = True
            if started:
                self._save_registry()

    @staticmethod
    def _get_descendants(pid):
        """Get all descendant PIDs of a process."""
        descendants = []
        try:
            result = subprocess.run(
                ["ps", "--ppid", str(pid), "-o", "pid=", "--no-headers"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().splitlines():
                child_pid = int(line.strip())
                descendants.append(child_pid)
                descendants.extend(WebJobManager._get_descendants(child_pid))
        except Exception:
            pass
        return descendants

    @staticmethod
    def _kill_remote_rsync(job):
        """Kill orphaned rsync processes on remote SSH destinations.

        When a pipelined SSH→SSH backup is killed locally, the rsync running
        on the destination server keeps going.  We SSH in and pkill it.
        """
        if not job.log_file or not Path(job.log_file).is_file():
            return
        try:
            log_text = Path(job.log_file).read_text(errors="replace")
        except OSError:
            return

        # Only relevant for pipelined (ssh→ssh) transfers
        if "Pipelined transfer" not in log_text and "ssh\u2192ssh" not in log_text:
            return

        # Collect SSH remotes to clean up
        remotes_to_clean = []
        for name in list_conf_dir("remotes.d"):
            conf = parse_conf(CONFIG_DIR / "remotes.d" / f"{name}.conf")
            if conf.get("REMOTE_TYPE") != "ssh":
                continue
            host = conf.get("REMOTE_HOST", "")
            if not host or host not in log_text:
                continue
            remotes_to_clean.append({
                "user": conf.get("REMOTE_USER", "root"),
                "host": host,
                "port": conf.get("REMOTE_PORT", "22"),
                "key": conf.get("REMOTE_KEY", ""),
                "auth_method": conf.get("REMOTE_AUTH_METHOD", "key"),
                "base": conf.get("REMOTE_BASE", ""),
            })

        for remote in remotes_to_clean:
            # Use the remote base path to target only gniza rsync processes
            pkill_pattern = f"rsync.*{remote['base']}" if remote["base"] else "rsync --fake-super"
            ssh_cmd = ["ssh", "-p", remote["port"],
                       "-o", "ConnectTimeout=5",
                       "-o", "StrictHostKeyChecking=accept-new"]
            if remote["auth_method"] != "password":
                ssh_cmd += ["-o", "BatchMode=yes"]
                if remote["key"]:
                    ssh_cmd += ["-i", remote["key"]]
            ssh_cmd += [f"{remote['user']}@{remote['host']}",
                        f"pkill -f '{pkill_pattern}'"]
            try:
                subprocess.run(ssh_cmd, capture_output=True, timeout=10)
                logger.info(f"Killed remote rsync on {remote['user']}@{remote['host']}")
            except Exception as e:
                logger.warning(f"Failed to kill remote rsync on {remote['host']}: {e}")

    def kill_job(self, job_id):
        job = self._jobs.get(job_id)
        if not job:
            return "not found"
        if job.status == "queued":
            job.status = "failed"
            job.return_code = -9
            job.finished_at = datetime.now()
            job.cli_args = None
            self._save_registry()
            self._dispatch_queue()
            return "cancelled"
        if not job.pid:
            return "not found"

        # Collect all descendant PIDs before killing (tree may disappear)
        all_pids = self._get_descendants(job.pid)
        all_pids.append(job.pid)

        # Kill process group first
        try:
            pgid = job.pgid or os.getpgid(job.pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

        # Kill all descendants individually (catches processes in different groups)
        for pid in all_pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        # Kill rsync on remote SSH destinations (pipelined transfers)
        try:
            self._kill_remote_rsync(job)
        except Exception:
            logger.exception("Failed to clean up remote rsync processes")

        return "killed"

    def remove_finished(self):
        for job in self._jobs.values():
            if job.status not in ("running", "queued") and job.log_file:
                try:
                    Path(job.log_file).unlink(missing_ok=True)
                except OSError:
                    pass
        self._jobs = {k: v for k, v in self._jobs.items() if v.status in ("running", "queued")}
        self._save_registry()

    def get_log_lines(self, job_id, tail=100):
        """Read last `tail` lines from the job's log file. Returns (lines, total_lines)."""
        job = self._jobs.get(job_id)
        if not job or not job.log_file:
            return [], 0
        try:
            with open(job.log_file) as f:
                # Split on both \n and \r to handle rsync's carriage-return progress updates
                all_lines = f.read().replace('\r', '\n').splitlines()
            total = len(all_lines)
            last_lines = [l for l in all_lines[-tail:]]
            return last_lines, total
        except (OSError, FileNotFoundError):
            return [], 0

    def get_progress(self, job_id):
        """Read rsync progress from the separate progress file."""
        job = self._jobs.get(job_id)
        if not job or job.status != "running" or not job.pid:
            return None
        progress_file = WORK_DIR / f"gniza-progress-{job.pid}.txt"
        try:
            line = progress_file.read_text().strip()
            if not line:
                return None
            m = re.search(r"(\d+)%", line)
            if m:
                return {"pct": int(m.group(1)), "line": line}
        except (OSError, FileNotFoundError):
            pass
        return None

    def _flock_read(self):
        """Read registry under flock."""
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_path = REGISTRY_FILE.with_suffix(".lock")
        with open(lock_path, "w") as lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_SH)
            try:
                if not REGISTRY_FILE.is_file():
                    return []
                return json.loads(REGISTRY_FILE.read_text())
            except Exception:
                return []
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)

    def load_registry(self):
        """Load jobs from shared JSON registry."""
        entries = self._flock_read()
        if not entries:
            return
        now = datetime.now()
        changed = False
        refreshed = {}
        for entry in entries:
            job_id = entry["id"]
            status = entry.get("status", "running")
            pid = entry.get("pid")

            if status == "queued":
                job = WebJob(
                    id=job_id,
                    kind=entry.get("kind", "backup"),
                    label=entry.get("label", "Job"),
                    status="queued",
                    started_at=datetime.fromisoformat(entry.get("started_at", now.isoformat())),
                    log_file=entry.get("log_file"),
                    cli_args=tuple(entry["cli_args"]) if entry.get("cli_args") else None,
                )
                refreshed[job_id] = job
                continue

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
                    if rc == 0 and self._is_skipped(entry.get("log_file")):
                        status = "skipped"
                    else:
                        status = "success" if rc == 0 else "failed" if rc else "unknown"
                    entry["status"] = status
                    entry["return_code"] = rc
                    entry["finished_at"] = now.isoformat()
                    changed = True

            # Skip expired finished jobs
            if status not in ("running", "queued"):
                fin = entry.get("finished_at")
                if fin:
                    try:
                        age_days = (now - datetime.fromisoformat(fin)).total_seconds() / 86400
                        if age_days > get_log_retain_days():
                            log_file = entry.get("log_file")
                            if log_file:
                                try:
                                    Path(log_file).unlink(missing_ok=True)
                                except OSError:
                                    pass
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
            self._dispatch_queue()

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
            if job.status == "queued" and job.cli_args:
                entry["cli_args"] = list(job.cli_args)
            entries.append(entry)
        try:
            REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            lock_path = REGISTRY_FILE.with_suffix(".lock")
            with open(lock_path, "w") as lock_fh:
                fcntl.flock(lock_fh, fcntl.LOCK_EX)
                try:
                    fd, tmp = tempfile.mkstemp(dir=str(REGISTRY_FILE.parent), suffix=".tmp")
                    try:
                        os.write(fd, json.dumps(entries, indent=2).encode())
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    os.rename(tmp, str(REGISTRY_FILE))
                finally:
                    fcntl.flock(lock_fh, fcntl.LOCK_UN)
        except OSError:
            pass

    @staticmethod
    def _is_skipped(log_file):
        """Check if all targets were skipped (disabled)."""
        if not log_file or not Path(log_file).is_file():
            return False
        try:
            text = Path(log_file).read_text()
            return ("is disabled, skipping" in text
                    and "Backup completed" not in text
                    and "Backup Summary" not in text)
        except OSError:
            return False

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
            # No completion marker and no error markers — unknown (likely killed)
            return None
        except OSError:
            return None


# Module-level singleton
web_job_manager = WebJobManager()
