import asyncio
import os
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
