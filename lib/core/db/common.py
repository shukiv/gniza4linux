"""Shared database helpers — port of lib/db_common.sh.

Provides SSH execution and password-passing for database operations.
All passwords are passed via environment variables, never on the command line.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lib.core.context import BackupContext

from lib.ssh import SSHOpts

logger = logging.getLogger(__name__)

# Regex for validating database names (prevent path traversal / injection)
_VALID_DB_NAME_RE = re.compile(r'^[a-zA-Z0-9._-]+$')

# Regex for validating extra opts (alphanumeric, spaces, dots, equals, hyphens, slashes)
_VALID_EXTRA_OPTS_RE = re.compile(r'^[a-zA-Z0-9 ._=/-]+$')

# Regex for validating usernames
_VALID_USERNAME_RE = re.compile(r'^[a-zA-Z0-9._-]+$')


def validate_db_name(name: str) -> bool:
    """Validate a database name to prevent path traversal."""
    return bool(_VALID_DB_NAME_RE.match(name))


def validate_extra_opts(opts: str) -> bool:
    """Validate extra command-line options string."""
    return bool(_VALID_EXTRA_OPTS_RE.match(opts))


def validate_username(name: str) -> bool:
    """Validate a system username."""
    return bool(_VALID_USERNAME_RE.match(name))


def is_db_remote(target) -> bool:
    """True if the target's source_type is 'ssh'."""
    return target.source_type == "ssh"


def _build_ssh_opts(ctx: BackupContext) -> SSHOpts:
    """Build SSHOpts from the target's source_* fields."""
    return SSHOpts.for_target_source(ctx.target)


def ssh_run_raw(ctx: BackupContext, cmd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a raw SSH command on the source host (no sudo, no password env).

    Used for binary detection where sudo is unnecessary.
    """
    ssh = _build_ssh_opts(ctx)
    return ssh.run(cmd, timeout=timeout)


def run_db_command(
    ctx: BackupContext,
    cmd_args: list[str],
    password_env: Optional[str] = None,
    password_val: Optional[str] = None,
    use_sudo: bool = False,
    timeout: int = 120,
    capture_output: bool = True,
    stdin: Optional[int] = None,
    stdout: Optional[int] = None,
) -> subprocess.CompletedProcess:
    """Run a database command locally or via SSH.

    Handles password passing via environment variable (never on command line).
    For remote execution, the command is sent over SSH with the password env
    var prepended in the remote shell.

    Args:
        ctx: BackupContext with target info.
        cmd_args: Command as a list of strings.
        password_env: Environment variable name for password (e.g. MYSQL_PWD).
        password_val: The password value.
        use_sudo: Whether to prepend sudo.
        timeout: Command timeout in seconds.
        capture_output: Whether to capture stdout/stderr.
        stdin: File descriptor for stdin piping.
        stdout: File descriptor for stdout piping.
    """
    remote = is_db_remote(ctx.target)

    if remote:
        return _run_remote(
            ctx, cmd_args,
            password_env=password_env,
            password_val=password_val,
            use_sudo=use_sudo,
            timeout=timeout,
            capture_output=capture_output,
            stdin=stdin,
            stdout=stdout,
        )
    else:
        return _run_local(
            cmd_args,
            password_env=password_env,
            password_val=password_val,
            use_sudo=use_sudo,
            timeout=timeout,
            capture_output=capture_output,
            stdin=stdin,
            stdout=stdout,
        )


def _run_local(
    cmd_args: list[str],
    password_env: Optional[str] = None,
    password_val: Optional[str] = None,
    use_sudo: bool = False,
    timeout: int = 120,
    capture_output: bool = True,
    stdin: Optional[int] = None,
    stdout: Optional[int] = None,
) -> subprocess.CompletedProcess:
    """Run a command locally with optional password env and sudo."""
    env = os.environ.copy()
    if password_env and password_val:
        env[password_env] = password_val

    full_cmd = list(cmd_args)
    if use_sudo:
        full_cmd = ["sudo"] + full_cmd

    kw = dict(text=True, env=env, timeout=timeout)
    if capture_output and stdout is None and stdin is None:
        kw["capture_output"] = True
    else:
        if stdin is not None:
            kw["stdin"] = stdin
        if stdout is not None:
            kw["stdout"] = stdout
        if capture_output:
            kw["stderr"] = subprocess.PIPE

    return subprocess.run(full_cmd, **kw)


def _run_remote(
    ctx: BackupContext,
    cmd_args: list[str],
    password_env: Optional[str] = None,
    password_val: Optional[str] = None,
    use_sudo: bool = False,
    timeout: int = 120,
    capture_output: bool = True,
    stdin: Optional[int] = None,
    stdout: Optional[int] = None,
) -> subprocess.CompletedProcess:
    """Run a command on the remote source host via SSH.

    The password is passed as an environment variable in the remote shell
    (prepended to the command string).
    """
    import shlex

    # Build the remote command string
    remote_cmd = " ".join(shlex.quote(a) for a in cmd_args)

    # Prepend password env var on the remote side
    if password_env and password_val:
        remote_cmd = "%s=%s %s" % (password_env, shlex.quote(password_val), remote_cmd)
    elif use_sudo:
        remote_cmd = "sudo %s" % remote_cmd

    ssh = _build_ssh_opts(ctx)
    ssh_cmd = ssh.ssh_cmd(remote_cmd)
    ssh_env = ssh.env() or os.environ.copy()

    kw = dict(text=True, env=ssh_env, timeout=timeout)
    if capture_output and stdout is None and stdin is None:
        kw["capture_output"] = True
    else:
        if stdin is not None:
            kw["stdin"] = stdin
        if stdout is not None:
            kw["stdout"] = stdout
        if capture_output:
            kw["stderr"] = subprocess.PIPE

    return subprocess.run(ssh_cmd, **kw)
