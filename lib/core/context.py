"""Backup context — replaces Bash global variables with an immutable context object."""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lib.models import Target, Remote, AppSettings


@dataclass(frozen=True)
class BackupContext:
    """Immutable context for a single backup/restore operation.

    Replaces the 60+ Bash global variables (TARGET_*, REMOTE_*, CONFIG_*)
    with a single object passed to every function.
    """
    target: Target
    remote: Remote
    settings: AppSettings
    hostname: str
    timestamp: str                              # YYYY-MM-DDTHHMMSS
    prev_snapshot: Optional[str] = None         # for --link-dest
    job_id: str = ""
    work_dir: Path = field(default_factory=lambda: Path("/tmp"))
    log_dir: Path = field(default_factory=lambda: Path("/tmp"))

    @classmethod
    def create(
        cls,
        target_name: str,
        remote_name: str,
        timestamp: Optional[str] = None,
        job_id: str = "",
    ) -> BackupContext:
        """Factory that loads configs and builds a complete context."""
        from lib.config import CONFIG_DIR, WORK_DIR, LOG_DIR, parse_conf
        from lib.models import Target, Remote, AppSettings

        target_data = parse_conf(CONFIG_DIR / "targets.d" / ("%s.conf" % target_name))
        target = Target.from_conf(target_name, target_data)

        remote_data = parse_conf(CONFIG_DIR / "remotes.d" / ("%s.conf" % remote_name))
        remote = Remote.from_conf(remote_name, remote_data)

        settings_data = parse_conf(CONFIG_DIR / "gniza.conf")
        settings = AppSettings.from_conf(settings_data)

        ts = timestamp or datetime.now().strftime("%Y-%m-%dT%H%M%S")
        hn = socket.gethostname()

        return cls(
            target=target,
            remote=remote,
            settings=settings,
            hostname=hn,
            timestamp=ts,
            job_id=job_id or os.environ.get("GNIZA_JOB_ID", ""),
            work_dir=WORK_DIR,
            log_dir=LOG_DIR,
        )

    @property
    def snap_dir(self) -> str:
        """Snapshot directory path on the remote: base/hostname/targets/target_name/snapshots"""
        base = self.remote.base.rstrip("/")
        return "%s/%s/targets/%s/snapshots" % (base, self.hostname, self.target.name)

    @property
    def is_local_remote(self) -> bool:
        return self.remote.type == "local"

    @property
    def is_rclone_remote(self) -> bool:
        return self.remote.type in ("s3", "gdrive", "rclone")

    @property
    def is_ssh_remote(self) -> bool:
        return self.remote.type == "ssh"

    @property
    def is_ssh_source(self) -> bool:
        return self.target.source_type == "ssh"

    @property
    def bwlimit(self) -> int:
        """Bandwidth limit in KB/s (0 = unlimited). Remote override > global."""
        try:
            remote_bw = int(self.remote.bwlimit or "0")
            if remote_bw > 0:
                return remote_bw
        except (ValueError, TypeError):
            pass
        try:
            return int(self.settings.bwlimit or "0")
        except (ValueError, TypeError):
            return 0

    @property
    def retention_count(self) -> int:
        """Retention count. Schedule override > global default."""
        try:
            return int(self.settings.retention_count or "30")
        except (ValueError, TypeError):
            return 30
