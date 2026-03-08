#!/usr/bin/env python3
"""Register CLI/cron-started jobs in the shared gniza-jobs.json registry.

Usage:
    python3 -m lib.job_register start <kind> <label> [--log-file=PATH]
    python3 -m lib.job_register finish <job_id> <status> [<return_code>]

Prints the job_id on 'start'.
"""
import fcntl
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from tui.config import WORK_DIR

REGISTRY_FILE = WORK_DIR / "gniza-jobs.json"


def _load():
    if REGISTRY_FILE.is_file():
        try:
            return json.loads(REGISTRY_FILE.read_text())
        except Exception:
            pass
    return []


def _save(entries):
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(REGISTRY_FILE.parent), suffix=".tmp")
    try:
        os.write(fd, json.dumps(entries, indent=2).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rename(tmp, str(REGISTRY_FILE))


def _locked_update(fn):
    """Load registry under flock, call fn(entries), save result."""
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = REGISTRY_FILE.with_suffix(".lock")
    with open(lock_path, "w") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            entries = _load()
            fn(entries)
            _save(entries)
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def cmd_start(kind, label, log_file=None, caller_pid=None):
    job_id = uuid.uuid4().hex[:8]
    pid = caller_pid or os.getppid()
    try:
        pgid = os.getpgid(pid)
    except OSError:
        pgid = pid
    entry = {
        "id": job_id,
        "kind": kind,
        "label": label,
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "return_code": None,
        "pid": pid,
        "pgid": pgid,
    }
    if log_file:
        entry["log_file"] = log_file

    def _append(entries):
        entries.append(entry)

    _locked_update(_append)
    print(job_id)


def cmd_finish(job_id, status, return_code=None):
    def _update(entries):
        for entry in entries:
            if entry.get("id") == job_id:
                entry["status"] = status
                entry["return_code"] = int(return_code) if return_code is not None else None
                entry["finished_at"] = datetime.now().isoformat()
                entry.pop("pid", None)
                entry.pop("pgid", None)
                break

    _locked_update(_update)


def main():
    if len(sys.argv) < 2:
        print("Usage: job_register.py start|finish ...", file=sys.stderr)
        sys.exit(1)

    action = sys.argv[1]
    if action == "start":
        if len(sys.argv) < 4:
            print("Usage: job_register.py start <kind> <label> [--log-file=PATH]", file=sys.stderr)
            sys.exit(1)
        kind = sys.argv[2]
        label = sys.argv[3]
        log_file = None
        caller_pid = None
        for arg in sys.argv[4:]:
            if arg.startswith("--log-file="):
                log_file = arg.split("=", 1)[1]
            elif arg.startswith("--pid="):
                caller_pid = int(arg.split("=", 1)[1])
        cmd_start(kind, label, log_file, caller_pid)
    elif action == "finish":
        if len(sys.argv) < 4:
            print("Usage: job_register.py finish <job_id> <status> [<return_code>]", file=sys.stderr)
            sys.exit(1)
        job_id = sys.argv[2]
        status = sys.argv[3]
        rc = sys.argv[4] if len(sys.argv) > 4 else None
        cmd_finish(job_id, status, rc)
    else:
        print(f"Unknown action: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
