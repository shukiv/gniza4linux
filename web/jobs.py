from __future__ import annotations

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

from lib.job_utils import detect_return_code, is_skipped_job
from tui.config import (
    get_max_concurrent_jobs, CONFIG_DIR, parse_conf,
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
        self._cache_time = 0.0
        self._cache_ttl = 1.5  # seconds
        self.load_registry()

    def create_and_start(self, kind, label, *cli_args):
        """Create a job. If under concurrency limit, start it; otherwise queue it."""
        self._invalidate_cache()
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

            proc = start_cli_background(*cli_args, log_file=str(log_path), job_id=job_id)
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
                proc = start_cli_background(*job.cli_args, log_file=job.log_file, job_id=job.id)
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
            logger.debug("Failed to get descendants of PID %s", pid, exc_info=True)
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
                "user": conf.get("REMOTE_USER", "gniza"),
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
                       "-o", "StrictHostKeyChecking=accept-new",
                       "-o", "LogLevel=ERROR"]
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
        self._invalidate_cache()
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
        self._invalidate_cache()
        self._jobs = {k: v for k, v in self._jobs.items() if v.status in ("running", "queued")}
        self._save_registry()

    def get_log_lines(self, job_id, tail=100):
        """Read last `tail` lines from the job's log file and transfer log. Returns (lines, total_lines)."""
        job = self._jobs.get(job_id)
        if not job or not job.log_file:
            return [], 0
        try:
            last_lines, total = self._tail_file(job.log_file, tail)
            # For running jobs, append recent transfer log lines (file-by-file details)
            if job.status == "running":
                transfer_lines = self._get_transfer_log_lines(job_id, tail=tail)
                if transfer_lines:
                    last_lines = last_lines[:-len(transfer_lines)] + transfer_lines if len(last_lines) >= tail else last_lines + transfer_lines
                    last_lines = last_lines[-tail:]
                    total += len(transfer_lines)
            return last_lines, total
        except (OSError, FileNotFoundError):
            return [], 0

    @staticmethod
    def _tail_file(filepath, n=100):
        """Read last n lines from a file efficiently without loading the whole file."""
        with open(filepath, 'rb') as f:
            # Get file size
            f.seek(0, 2)
            fsize = f.tell()
            if fsize == 0:
                return [], 0
            # Read chunks from the end to find enough lines
            block_size = 8192
            lines_found = []
            remaining = fsize
            while remaining > 0 and len(lines_found) <= n:
                read_size = min(block_size, remaining)
                remaining -= read_size
                f.seek(remaining)
                block = f.read(read_size)
                lines_found = block.splitlines() + lines_found
            # Estimate total lines from file size and avg line length
            result = lines_found[-n:]
            if len(lines_found) > n:
                avg_len = sum(len(l) for l in result) / len(result) if result else 80
                total_est = int(fsize / (avg_len + 1))
            else:
                total_est = len(lines_found)
            return [l.decode('utf-8', errors='replace').replace('\r', '') for l in result], total_est

    def _get_transfer_log_lines(self, job_id, tail=50):
        """Read recent lines from the rsync transfer log for a running job."""
        pointer_file = WORK_DIR / f"gniza-transferlog-{job_id}.txt"
        try:
            transfer_log = pointer_file.read_text().strip()
            if not transfer_log or not Path(transfer_log).is_file():
                return []
            with open(transfer_log) as f:
                lines = f.readlines()
            # Return only file transfer lines (skip rsync header/setup lines)
            result = []
            for line in lines[-tail:]:
                line = line.rstrip('\n')
                if not line:
                    continue
                # Extract just the filename from rsync log format:
                # "2026/03/09 05:03:07 [719348] <f+++++++++ path/to/file"
                m = re.match(r'\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} \[\d+\] [<>]f[\w.+]+ (.+)', line)
                if m:
                    result.append(m.group(1))
            return result
        except (OSError, FileNotFoundError):
            return []

    def get_progress(self, job_id):
        """Read rsync progress from the separate progress file."""
        job = self._jobs.get(job_id)
        if not job or job.status != "running":
            return None
        progress_file = WORK_DIR / f"gniza-progress-{job_id}.txt"
        try:
            line = progress_file.read_text().strip()
            if not line:
                return None
            m = re.search(r"(\d+)%", line)
            if m:
                pct = int(m.group(1))
                speed = ""
                sm = re.search(r"([\d.]+[KMGT]?B/s)", line)
                if sm:
                    speed = sm.group(1)
                # Use to-chk file ratio when it shows better progress than byte%
                cm = re.search(r"to-chk=(\d+)/(\d+)", line)
                if cm:
                    remaining, total = int(cm.group(1)), int(cm.group(2))
                    if total > 0:
                        file_pct = int((total - remaining) / total * 100)
                        pct = max(pct, file_pct)
                return {"pct": pct, "line": line, "speed": speed}
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
                logger.debug("Failed to read job registry from %s", REGISTRY_FILE, exc_info=True)
                return []
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)

    def _invalidate_cache(self):
        self._cache_time = 0.0

    def load_registry(self):
        """Load jobs from shared JSON registry (with TTL cache)."""
        import time as _time
        now = _time.monotonic()
        if now - self._cache_time < self._cache_ttl:
            return
        entries = self._flock_read()
        if not entries:
            self._jobs = {}
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
                            rc = detect_return_code(entry.get("log_file"))
                except ChildProcessError:
                    # Not our child — fall back to kill-0 check
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        alive = False
                        rc = detect_return_code(entry.get("log_file"))
                    except PermissionError:
                        pass  # alive but can't signal
                if not alive:
                    if rc is None:
                        rc = detect_return_code(entry.get("log_file"))
                    if rc == 0 and is_skipped_job(entry.get("log_file")):
                        status = "skipped"
                    else:
                        status = "success" if rc == 0 else "failed" if rc else "unknown"
                    entry["status"] = status
                    entry["return_code"] = rc
                    entry["finished_at"] = now.isoformat()
                    changed = True

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
        import time as _time
        self._cache_time = _time.monotonic()
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
            logger.debug("Failed to save job registry to %s", REGISTRY_FILE, exc_info=True)



# Module-level singleton
web_job_manager = WebJobManager()
