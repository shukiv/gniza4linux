import asyncio

from lib.cli_runner import gniza_bin, start_cli_background  # noqa: F401


async def run_cli(*args: str) -> tuple[int, str, str]:
    cmd = [gniza_bin(), "--cli"] + list(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def stream_cli(callback, *args: str) -> int:
    cmd = [gniza_bin(), "--cli"] + list(args)
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
