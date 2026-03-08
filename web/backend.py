import subprocess

from lib.cli_runner import gniza_bin, start_cli_background  # noqa: F401


def run_cli_sync(*args, timeout=300):
    cmd = [gniza_bin(), "--cli"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr
