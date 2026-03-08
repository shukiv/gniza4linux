import json
import fcntl
import os
import signal
import time
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from tui.config import (
    get_log_retain_days, get_max_concurrent_jobs, LOG_DIR
)

logger = logging.getLogger("gniza-daemon")

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info(f"Received signal {signum}, shutting down...")
    _shutdown = True


def _work_dir():
    if os.geteuid() == 0:
        return Path("/usr/local/gniza/workdir")
    state_home = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(state_home) / "gniza" / "workdir"


def _registry_path():
    return _work_dir() / "gniza-jobs.json"


def _load_registry():
    """Read the registry file. Returns list of dicts."""
    reg = _registry_path()
    if not reg.is_file():
        return []
    try:
        return json.loads(reg.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_registry(entries):
    """Write the registry file atomically via temp file + rename."""
    reg = _registry_path()
    try:
        reg.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(reg.parent), suffix=".tmp")
        try:
            os.write(fd, json.dumps(entries, indent=2).encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(tmp, str(reg))
    except OSError as e:
        logger.error(f"Failed to save registry: {e}")
        # Clean up temp file on failure
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _locked_update(fn):
    """Load registry under flock, call fn(entries), save if fn returns True."""
    reg = _registry_path()
    reg.parent.mkdir(parents=True, exist_ok=True)
    lock_path = reg.with_suffix(".lock")
    with open(lock_path, "w") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            entries = _load_registry()
            if fn(entries):
                _save_registry(entries)
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def _is_pid_alive(pid):
    """Check if a PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive but can't signal
    except OSError:
        return False


def _valid_log_path(log_file):
    """Validate that a log file path is within expected directories."""
    if not log_file:
        return False
    try:
        resolved = Path(log_file).resolve()
        work = _work_dir().resolve()
        log_dir = Path(LOG_DIR).resolve()
        return str(resolved).startswith(str(work)) or str(resolved).startswith(str(log_dir))
    except (OSError, ValueError):
        return False


def _detect_return_code(log_file):
    """Determine exit code from log file content."""
    if not _valid_log_path(log_file) or not Path(log_file).is_file():
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


def _is_skipped(log_file):
    """Check if all targets were skipped."""
    if not _valid_log_path(log_file) or not Path(log_file).is_file():
        return False
    try:
        text = Path(log_file).read_text()
        return ("is disabled, skipping" in text
                and "Backup completed" not in text
                and "Backup Summary" not in text)
    except OSError:
        return False


def _start_cli_background(*args, log_file=None):
    """Start a gniza CLI command in the background. Returns Popen."""
    import subprocess
    gniza_dir = Path(__file__).resolve().parent.parent
    gniza_bin = gniza_dir / "bin" / "gniza"
    cmd = [str(gniza_bin), "--cli", *args]
    fh = None
    try:
        fh = open(log_file, "a") if log_file else None
        proc = subprocess.Popen(
            cmd,
            stdout=fh if fh else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if fh else subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc
    except Exception:
        raise
    finally:
        if fh is not None:
            fh.close()


# Track Popen objects for proper reaping
_child_procs = {}


def check_jobs():
    """Main health check: detect dead jobs, update registry."""

    def _check(entries):
        if not entries:
            return False
        now = datetime.now()
        changed = False

        for entry in entries:
            if entry.get("status") != "running":
                continue
            pid = entry.get("pid")
            if not pid:
                continue
            if _is_pid_alive(pid):
                continue

            # Process is dead — try to reap via Popen if we have it
            rc = None
            if pid in _child_procs:
                proc = _child_procs.pop(pid)
                rc = proc.wait()

            # Fallback: try waitpid
            if rc is None:
                try:
                    wpid, wstatus = os.waitpid(pid, os.WNOHANG)
                    if wpid != 0:
                        if os.WIFEXITED(wstatus):
                            rc = os.WEXITSTATUS(wstatus)
                        elif os.WIFSIGNALED(wstatus):
                            rc = 1
                except ChildProcessError:
                    pass

            if rc is None:
                rc = _detect_return_code(entry.get("log_file"))

            if rc == 0 and _is_skipped(entry.get("log_file")):
                entry["status"] = "skipped"
            elif rc == 0:
                entry["status"] = "success"
            elif rc is not None:
                entry["status"] = "failed"
            else:
                entry["status"] = "unknown"

            entry["return_code"] = rc
            entry["finished_at"] = now.isoformat()
            entry.pop("pid", None)
            entry.pop("pgid", None)
            changed = True
            logger.info(f"Job {entry['id']} ({entry['label']}): detected dead PID {pid} → {entry['status']}")

        return changed

    _locked_update(_check)


def dispatch_queue():
    """Start queued jobs if under the concurrency limit."""

    def _dispatch(entries):
        if not entries:
            return False
        max_jobs = get_max_concurrent_jobs()
        running = sum(1 for e in entries if e.get("status") == "running")
        changed = False

        for entry in sorted(entries, key=lambda e: e.get("started_at", "")):
            if entry.get("status") != "queued":
                continue
            cli_args = entry.get("cli_args")
            if not cli_args:
                continue
            if max_jobs > 0 and running >= max_jobs:
                break

            log_file = entry.get("log_file")
            if not log_file:
                log_file = str(_work_dir() / f"gniza-job-{entry['id']}.log")
                entry["log_file"] = log_file

            proc = _start_cli_background(*cli_args, log_file=log_file)
            _child_procs[proc.pid] = proc
            entry["status"] = "running"
            entry["pid"] = proc.pid
            try:
                entry["pgid"] = os.getpgid(proc.pid)
            except OSError:
                pass
            entry.pop("cli_args", None)
            running += 1
            changed = True
            logger.info(f"Job {entry['id']} ({entry['label']}): dispatched from queue (PID {proc.pid})")

        return changed

    _locked_update(_dispatch)


def cleanup_old_entries():
    """Remove finished job entries and their log files older than LOG_RETAIN days."""

    def _cleanup(entries):
        retain_days = get_log_retain_days()
        now = datetime.now()
        to_remove = []

        for i, entry in enumerate(entries):
            if entry.get("status") in ("running", "queued"):
                continue
            finished_at = entry.get("finished_at")
            if not finished_at:
                continue
            try:
                age_days = (now - datetime.fromisoformat(finished_at)).total_seconds() / 86400
            except (ValueError, TypeError):
                continue
            if age_days > retain_days:
                log_file = entry.get("log_file")
                if log_file and _valid_log_path(log_file):
                    try:
                        Path(log_file).unlink(missing_ok=True)
                    except OSError:
                        pass
                to_remove.append(i)

        if to_remove:
            for i in reversed(to_remove):
                entries.pop(i)
            logger.info(f"Cleaned up {len(to_remove)} expired job entries")
            return True
        return False

    _locked_update(_cleanup)


def cleanup_old_logs():
    """Remove backup log files older than LOG_RETAIN days from LOG_DIR."""
    retain_days = get_log_retain_days()
    log_dir = Path(LOG_DIR)
    if not log_dir.is_dir():
        return
    now = time.time()
    cutoff = now - (retain_days * 86400)
    removed = 0
    for f in log_dir.glob("gniza-*.log"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    if removed > 0:
        logger.info(f"Cleaned up {removed} old backup log files from {log_dir}")


def cleanup_orphan_job_logs():
    """Remove job log files in workdir that are not referenced by any registry entry."""
    work_dir = _work_dir()
    if not work_dir.is_dir():
        return
    entries = _load_registry()
    referenced = {e.get("log_file") for e in entries if e.get("log_file")}
    removed = 0
    for f in work_dir.glob("gniza-job-*.log"):
        if str(f) not in referenced:
            # Only remove if older than 1 hour (avoid race with just-created jobs)
            try:
                if time.time() - f.stat().st_mtime > 3600:
                    f.unlink()
                    removed += 1
            except OSError:
                pass
    if removed > 0:
        logger.info(f"Cleaned up {removed} orphaned job log files")


def enforce_retention():
    """Run snapshot retention cleanup via the CLI."""
    import subprocess
    gniza_dir = Path(__file__).resolve().parent.parent
    gniza_bin = gniza_dir / "bin" / "gniza"
    try:
        result = subprocess.run(
            [str(gniza_bin), "--cli", "retention", "--all"],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            if output:
                logger.info(f"Retention cleanup: {output}")
        else:
            stderr = result.stderr.strip()
            if stderr:
                logger.warning(f"Retention cleanup failed: {stderr}")
    except subprocess.TimeoutExpired:
        logger.warning("Retention cleanup timed out (10 min)")
    except OSError as e:
        logger.error(f"Retention cleanup error: {e}")


def run(interval=10):
    """Main daemon loop."""
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info(f"gniza-daemon started (interval={interval}s, pid={os.getpid()})")
    cleanup_counter = 0
    while not _shutdown:
        try:
            check_jobs()
            dispatch_queue()
            # Run cleanup less frequently (every 60 cycles = ~10 minutes at default interval)
            cleanup_counter += 1
            if cleanup_counter >= 60:
                cleanup_counter = 0
                cleanup_old_entries()
                cleanup_old_logs()
                cleanup_orphan_job_logs()
                enforce_retention()
        except Exception:
            logger.exception("Health check error")
        time.sleep(interval)
    logger.info("gniza-daemon stopped")
