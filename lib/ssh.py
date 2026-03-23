"""Unified SSH command builder for gniza4linux.

SSHOpts is the single source of truth for SSH command construction.
All Python callers should use this module instead of building SSH
commands manually.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.models import Remote, Target

logger = logging.getLogger(__name__)

# ── Global defaults (lazy-loaded from gniza.conf) ───────────────

_global_defaults: dict[str, str] | None = None


def _load_global_defaults() -> dict[str, str]:
    """Read SSH_TIMEOUT and SSH_RETRIES from gniza.conf (once)."""
    global _global_defaults
    if _global_defaults is not None:
        return _global_defaults
    _global_defaults = {"SSH_TIMEOUT": "30", "SSH_RETRIES": "3"}
    try:
        from lib.config import CONFIG_DIR, parse_conf
        data = parse_conf(CONFIG_DIR / "gniza.conf")
        if data.get("SSH_TIMEOUT"):
            _global_defaults["SSH_TIMEOUT"] = data["SSH_TIMEOUT"]
        if data.get("SSH_RETRIES"):
            _global_defaults["SSH_RETRIES"] = data["SSH_RETRIES"]
    except Exception:
        pass
    return _global_defaults


# ── SSHOpts ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class SSHOpts:
    """Immutable SSH connection options.

    Build via factory constructors, then call output methods to get
    subprocess-ready command lists.
    """
    host: str = ""
    port: str = "22"
    user: str = "gniza"
    auth_method: str = "key"
    key: str = ""
    password: str = ""
    timeout: int | None = None         # None = read SSH_TIMEOUT from gniza.conf
    retries: int | None = None         # None = read SSH_RETRIES from gniza.conf
    control_master: bool = False
    strict_host_key: str = "accept-new"
    log_level: str = "ERROR"
    server_alive_interval: int = 60
    server_alive_count_max: int = 3

    # ── resolved helpers ────────────────────────────────────────

    @property
    def _timeout(self) -> int:
        if self.timeout is not None:
            return self.timeout
        try:
            return int(_load_global_defaults()["SSH_TIMEOUT"])
        except (ValueError, TypeError):
            return 30

    @property
    def _retries(self) -> int:
        if self.retries is not None:
            return self.retries
        try:
            return int(_load_global_defaults()["SSH_RETRIES"])
        except (ValueError, TypeError):
            return 3

    @property
    def _is_password(self) -> bool:
        return self.auth_method == "password" and bool(self.password)

    # ── factory constructors ────────────────────────────────────

    @classmethod
    def for_remote(cls, remote: Remote, **overrides) -> SSHOpts:
        """Build from a Remote model instance."""
        kw: dict = dict(
            host=remote.host,
            port=remote.port or "22",
            user=remote.user or "gniza",
            auth_method=remote.auth_method or "key",
            key=remote.key if remote.auth_method == "key" else "",
            password=remote.password if remote.auth_method == "password" else "",
        )
        kw.update(overrides)
        return cls(**kw)

    @classmethod
    def for_target_source(cls, target: Target, **overrides) -> SSHOpts:
        """Build from a Target's source_* fields."""
        kw: dict = dict(
            host=target.source_host,
            port=target.source_port or "22",
            user=target.source_user or "root",
            auth_method=target.source_auth_method or "key",
            key=target.source_key if target.source_auth_method == "key" else "",
            password=target.source_password if target.source_auth_method == "password" else "",
        )
        kw.update(overrides)
        return cls(**kw)

    @classmethod
    def for_remote_conf(cls, conf: dict, **overrides) -> SSHOpts:
        """Build from a raw remote config dict (e.g. parse_conf output)."""
        auth = conf.get("REMOTE_AUTH_METHOD", "key")
        kw: dict = dict(
            host=conf.get("REMOTE_HOST", ""),
            port=conf.get("REMOTE_PORT", "22"),
            user=conf.get("REMOTE_USER", "gniza"),
            auth_method=auth,
            key=conf.get("REMOTE_KEY", "") if auth == "key" else "",
            password=conf.get("REMOTE_PASSWORD", "") if auth == "password" else "",
        )
        kw.update(overrides)
        return cls(**kw)

    @classmethod
    def adhoc(cls, host, port="22", user="gniza", key="", password="", **overrides) -> SSHOpts:
        """Build a one-off SSHOpts for ad-hoc connections."""
        auth = "password" if password else "key"
        kw: dict = dict(
            host=host,
            port=port or "22",
            user=user or "gniza",
            auth_method=auth,
            key=key,
            password=password,
        )
        kw.update(overrides)
        return cls(**kw)

    # ── common SSH options (internal) ───────────────────────────

    def _base_opts(self) -> list[str]:
        """SSH options common to ssh_cmd and sftp_cmd."""
        opts: list[str] = []
        opts += ["-o", f"StrictHostKeyChecking={self.strict_host_key}"]
        opts += ["-o", f"LogLevel={self.log_level}"]
        opts += ["-o", f"ConnectTimeout={self._timeout}"]
        if not self._is_password:
            opts += ["-o", "BatchMode=yes"]
        if self.key and not self._is_password:
            opts += ["-i", self.key]
        if self.control_master:
            opts += ["-o", "ControlMaster=auto"]
            opts += ["-o", "ControlPath=/tmp/gniza-ssh-%r@%h:%p"]
            opts += ["-o", "ControlPersist=60"]
        opts += ["-o", f"ServerAliveInterval={self.server_alive_interval}"]
        opts += ["-o", f"ServerAliveCountMax={self.server_alive_count_max}"]
        return opts

    # ── output methods ──────────────────────────────────────────

    def ssh_cmd(self, remote_command=None) -> list[str]:
        """Build a subprocess-ready SSH command list.

        If remote_command is given, it is appended as arguments.
        """
        cmd = ["ssh"]
        cmd += self._base_opts()
        cmd += ["-p", self.port or "22"]
        cmd.append(f"{self.user}@{self.host}")
        if self._is_password:
            cmd = ["sshpass", "-e"] + cmd
        if remote_command is not None:
            if isinstance(remote_command, str):
                cmd.append(remote_command)
            else:
                cmd.extend(remote_command)
        return cmd

    def sftp_cmd(self) -> list[str]:
        """Build a subprocess-ready SFTP command list.

        Uses -o Port=N instead of -p N (sftp syntax).
        """
        cmd = ["sftp"]
        cmd += ["-o", f"Port={self.port or '22'}"]
        cmd += ["-o", f"StrictHostKeyChecking={self.strict_host_key}"]
        cmd += ["-o", f"ConnectTimeout={self._timeout}"]
        if not self._is_password:
            opts_extra = []
            if self.key:
                opts_extra += ["-o", f"IdentityFile={self.key}"]
            opts_extra += ["-o", "BatchMode=yes"]
            cmd += opts_extra
        cmd.append(f"{self.user}@{self.host}")
        if self._is_password:
            cmd = ["sshpass", "-e"] + cmd
        return cmd

    def rsync_ssh_string(self) -> str:
        """Build the SSH string for rsync -e (no ControlMaster/ServerAlive/user@host)."""
        parts = ["ssh", "-p", self.port or "22"]
        parts += ["-o", f"StrictHostKeyChecking={self.strict_host_key}"]
        parts += ["-o", f"ConnectTimeout={self._timeout}"]
        if not self._is_password:
            parts += ["-o", "BatchMode=yes"]
        if self.key and not self._is_password:
            parts += ["-i", self.key]
        return " ".join(parts)

    def env(self) -> dict | None:
        """Return environ dict with SSHPASS set, or None for key auth."""
        if self._is_password:
            e = os.environ.copy()
            e["SSHPASS"] = self.password
            return e
        return None

    def run(self, remote_command, *, timeout=None, **kw) -> subprocess.CompletedProcess:
        """Run a remote command via SSH.

        Returns CompletedProcess. Passes capture_output=True, text=True
        unless overridden in **kw.
        """
        cmd = self.ssh_cmd(remote_command)
        kw.setdefault("capture_output", True)
        kw.setdefault("text", True)
        kw.setdefault("env", self.env())
        if timeout is not None:
            kw["timeout"] = timeout
        return subprocess.run(cmd, **kw)

    def run_with_retry(self, remote_command, *, retries=None, backoff=10,
                       timeout=None, **kw) -> subprocess.CompletedProcess:
        """Run a remote command with exponential backoff on failure."""
        max_attempts = retries if retries is not None else self._retries
        last_result = None
        for attempt in range(max_attempts):
            last_result = self.run(remote_command, timeout=timeout, **kw)
            if last_result.returncode == 0:
                return last_result
            if attempt < max_attempts - 1:
                wait = backoff * (2 ** attempt)
                logger.warning(
                    "SSH command failed (attempt %d/%d), retrying in %ds...",
                    attempt + 1, max_attempts, wait,
                )
                time.sleep(wait)
        return last_result


# ── Standalone utility (migrated from ssh_utils.py) ─────────────

def get_ssh_keys():
    """Find existing SSH key pairs (private + public)."""
    ssh_dir = Path.home() / ".ssh"
    keys = []
    if ssh_dir.is_dir():
        for pub in sorted(ssh_dir.glob("*.pub")):
            private = pub.with_suffix("")
            try:
                content = pub.read_text().strip()
                keys.append({
                    "name": pub.stem,
                    "private_path": str(private),
                    "pub_path": str(pub),
                    "content": content,
                })
            except OSError:
                pass
    return keys
