#!/usr/bin/env python3
"""Register CLI/cron-started jobs in the shared gniza-jobs.json registry.

Usage:
    python3 -m lib.job_register start <kind> <label> [--log-file=PATH]
    python3 -m lib.job_register finish <job_id> <status> [<return_code>]

Prints the job_id on 'start'.
"""
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path


def _work_dir():
    if os.geteuid() == 0:
        return Path("/usr/local/gniza/workdir")
    state_home = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(state_home) / "gniza" / "workdir"


REGISTRY_FILE = _work_dir() / "gniza-jobs.json"


def _load():
    if REGISTRY_FILE.is_file():
        try:
            return json.loads(REGISTRY_FILE.read_text())
        except Exception:
            pass
    return []


def _save(entries):
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(entries, indent=2))


def cmd_start(kind, label, log_file=None):
    entries = _load()
    job_id = uuid.uuid4().hex[:8]
    pid = os.getppid()  # The bash caller's PID
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
    entries.append(entry)
    _save(entries)
    print(job_id)


def cmd_finish(job_id, status, return_code=None):
    entries = _load()
    for entry in entries:
        if entry.get("id") == job_id:
            entry["status"] = status
            entry["return_code"] = int(return_code) if return_code is not None else None
            entry["finished_at"] = datetime.now().isoformat()
            entry.pop("pid", None)
            entry.pop("pgid", None)
            break
    _save(entries)


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
        for arg in sys.argv[4:]:
            if arg.startswith("--log-file="):
                log_file = arg.split("=", 1)[1]
        cmd_start(kind, label, log_file)
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
