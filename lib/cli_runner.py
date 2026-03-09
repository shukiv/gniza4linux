"""Shared CLI runner used by TUI and web backends."""

import os
import subprocess
from pathlib import Path


def gniza_bin():
    env = os.environ.get("GNIZA_DIR")
    if env:
        p = Path(env) / "bin" / "gniza"
        if p.exists():
            return str(p)
    rel = Path(__file__).resolve().parent.parent / "bin" / "gniza"
    if rel.exists():
        return str(rel)
    return "gniza"


def start_cli_background(*args, log_file, job_id=None):
    cmd = [gniza_bin(), "--cli"] + list(args)
    fh = open(log_file, "w")
    env = os.environ.copy()
    env["GNIZA_DAEMON_TRACKED"] = "1"
    if job_id:
        env["GNIZA_JOB_ID"] = job_id
    proc = subprocess.Popen(
        cmd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True, env=env
    )
    # Child process has its own fd now; close ours to avoid leak
    fh.close()
    return proc
