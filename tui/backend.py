import asyncio
import os
import subprocess
from pathlib import Path


def _gniza_bin() -> str:
    gniza_dir = os.environ.get("GNIZA_DIR", "")
    if gniza_dir:
        return str(Path(gniza_dir) / "bin" / "gniza")
    here = Path(__file__).resolve().parent.parent / "bin" / "gniza"
    if here.is_file():
        return str(here)
    return "gniza"


async def run_cli(*args: str) -> tuple[int, str, str]:
    cmd = [_gniza_bin(), "--cli"] + list(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


def start_cli_background(*args: str, log_file: str) -> subprocess.Popen:
    """Start a CLI process that survives TUI exit.

    Uses subprocess.Popen directly (not asyncio) so there is no
    SubprocessTransport that would SIGKILL the child on event-loop cleanup.
    """
    cmd = [_gniza_bin(), "--cli"] + list(args)
    fh = open(log_file, "w")
    proc = subprocess.Popen(
        cmd,
        stdout=fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    fh.close()
    return proc


async def stream_cli(callback, *args: str) -> int:
    cmd = [_gniza_bin(), "--cli"] + list(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        callback(line.decode().rstrip("\n"))
    await proc.wait()
    return proc.returncode or 0
