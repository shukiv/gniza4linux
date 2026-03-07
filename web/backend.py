import subprocess
from pathlib import Path
import os


def _gniza_bin():
    env = os.environ.get("GNIZA_DIR")
    if env:
        p = Path(env) / "bin" / "gniza"
        if p.exists():
            return str(p)
    rel = Path(__file__).resolve().parent.parent / "bin" / "gniza"
    if rel.exists():
        return str(rel)
    return "gniza"


def run_cli_sync(*args, timeout=300):
    cmd = [_gniza_bin(), "--cli"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def start_cli_background(*args, log_file):
    cmd = [_gniza_bin(), "--cli"] + list(args)
    fh = open(log_file, "w")
    proc = subprocess.Popen(
        cmd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True
    )
    return proc
