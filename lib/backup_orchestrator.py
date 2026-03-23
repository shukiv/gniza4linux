"""Backup orchestration -- Python wrapper around the Bash backup core."""

from __future__ import annotations

from pathlib import Path

import lib.config as _config
from lib.config import parse_conf, list_conf_dir
from lib.models import Target, Remote, Schedule


class BackupOrchestrator:
    """High-level backup operations API.

    Wraps the existing Bash backup scripts via subprocess.
    Provides a testable interface for the daemon and web UI.
    """

    def __init__(self, gniza_bin: str | None = None):
        """Initialize with path to gniza binary."""
        self._bin = gniza_bin or self._find_gniza_bin()

    @staticmethod
    def _find_gniza_bin() -> str:
        """Locate the gniza binary."""
        for path in [
            Path(__file__).resolve().parent.parent / "bin" / "gniza",
            Path("/usr/local/bin/gniza"),
            Path.home() / ".local" / "share" / "gniza" / "bin" / "gniza",
        ]:
            if path.exists():
                return str(path)
        return "gniza"  # fall back to PATH

    def list_targets(self) -> list[str]:
        """List configured target names."""
        return list_conf_dir("targets.d")

    def list_remotes(self) -> list[str]:
        """List configured remote names."""
        return list_conf_dir("remotes.d")

    def list_schedules(self) -> list[str]:
        """List configured schedule names."""
        return list_conf_dir("schedules.d")

    def get_target(self, name: str) -> Target:
        """Load a Target config by name."""
        conf_path = _config.CONFIG_DIR / "targets.d" / f"{name}.conf"
        if not conf_path.is_file():
            raise FileNotFoundError(f"Target config not found: {conf_path}")
        data = parse_conf(conf_path)
        return Target.from_conf(name, data)

    def get_remote(self, name: str) -> Remote:
        """Load a Remote config by name."""
        conf_path = _config.CONFIG_DIR / "remotes.d" / f"{name}.conf"
        if not conf_path.is_file():
            raise FileNotFoundError(f"Remote config not found: {conf_path}")
        data = parse_conf(conf_path)
        return Remote.from_conf(name, data)

    def get_schedule(self, name: str) -> Schedule:
        """Load a Schedule config by name."""
        conf_path = _config.CONFIG_DIR / "schedules.d" / f"{name}.conf"
        if not conf_path.is_file():
            raise FileNotFoundError(f"Schedule config not found: {conf_path}")
        data = parse_conf(conf_path)
        return Schedule.from_conf(name, data)

    def build_backup_command(
        self,
        target: str | None = None,
        remote: str | None = None,
        all_targets: bool = False,
    ) -> list[str]:
        """Build the CLI command for a backup job.

        Returns a list suitable for subprocess.Popen().
        """
        cmd = [self._bin, "backup"]
        if all_targets:
            cmd.append("--all")
        elif target:
            cmd.append(f"--source={target}")
            if remote:
                cmd.append(f"--destination={remote}")
        return cmd

    def build_restore_command(
        self,
        target: str,
        remote: str,
        snapshot: str,
        folder: str | None = None,
        dest: str | None = None,
        skip_mysql: bool = False,
        skip_postgresql: bool = False,
    ) -> list[str]:
        """Build the CLI command for a restore job."""
        cmd = [self._bin, "restore",
               f"--source={target}",
               f"--destination={remote}",
               f"--snapshot={snapshot}"]
        if folder:
            cmd.append(f"--folder={folder}")
        if dest:
            cmd.append(f"--dest={dest}")
        if skip_mysql:
            cmd.append("--skip-mysql")
        if skip_postgresql:
            cmd.append("--skip-postgresql")
        return cmd

    def build_scheduled_run_command(self, schedule_name: str) -> list[str]:
        """Build the CLI command for a scheduled backup run."""
        return [self._bin, "scheduled-run", f"--schedule={schedule_name}"]

    def validate_target(self, name: str) -> tuple[bool, str]:
        """Validate that a target exists and is enabled."""
        try:
            target = self.get_target(name)
            if target.enabled != "yes":
                return False, f"Target '{name}' is disabled."
            if not target.folders:
                return False, f"Target '{name}' has no folders configured."
            return True, "OK"
        except FileNotFoundError:
            return False, f"Target '{name}' not found."
        except Exception as e:
            return False, str(e)

    def validate_remote(self, name: str) -> tuple[bool, str]:
        """Validate that a remote exists and is loadable."""
        try:
            self.get_remote(name)
            return True, "OK"
        except FileNotFoundError:
            return False, f"Remote '{name}' not found."
        except Exception as e:
            return False, str(e)

    def cli_args(self, cmd: list[str]) -> tuple[str, ...]:
        """Extract CLI args from a full command (strips the binary path).

        Useful for passing to WebJobManager.create_and_start() which
        prepends the binary path itself.
        """
        return tuple(cmd[1:])
