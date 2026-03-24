"""Rclone transport layer — S3, Google Drive, and generic rclone remotes.

Ports lib/rclone.sh to Python.  All rclone invocations use subprocess with
list arguments (no shell=True) to avoid injection.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lib.core.context import BackupContext

logger = logging.getLogger(__name__)


# ── Mode Detection ────────────────────────────────────────────────

def is_rclone_mode(remote_type: str) -> bool:
    """Check if remote type uses rclone transport."""
    return remote_type in ("s3", "gdrive", "rclone")


# ── Rclone Config Context Managers ───────────────────────────────

class RcloneConfig:
    """Context manager that creates/cleans a temp rclone config for remote (destination) operations."""

    def __init__(self, ctx: "BackupContext"):
        self.ctx = ctx
        self._path: str = ""

    def __enter__(self) -> str:
        self._path = _build_rclone_config(self.ctx.remote, self.ctx.work_dir)
        return self._path

    def __exit__(self, *exc):
        _cleanup_config(self._path)
        self._path = ""
        return False


class RcloneSourceConfig:
    """Context manager that creates/cleans a temp rclone config for source operations."""

    def __init__(self, ctx: "BackupContext"):
        self.ctx = ctx
        self._path: str = ""

    def __enter__(self) -> str:
        self._path = _build_source_rclone_config(self.ctx.target, self.ctx.work_dir)
        return self._path

    def __exit__(self, *exc):
        _cleanup_config(self._path)
        self._path = ""
        return False


def _cleanup_config(path: str) -> None:
    """Remove a temp rclone config file."""
    if path and os.path.isfile(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _build_rclone_config(remote, work_dir) -> str:
    """Build a temporary rclone config file for destination remote operations.

    Returns the path to the temp config file.
    """
    old_umask = os.umask(0o077)
    try:
        fd, tmpfile = tempfile.mkstemp(
            prefix="gniza-rclone-", suffix=".conf",
            dir=str(work_dir),
        )
    finally:
        os.umask(old_umask)

    try:
        remote_type = remote.type

        if remote_type == "s3":
            lines = [
                "[remote]",
                "type = s3",
                "provider = %s" % (remote.s3_provider or "AWS"),
                "access_key_id = %s" % remote.s3_access_key_id,
                "secret_access_key = %s" % remote.s3_secret_access_key,
                "region = %s" % (remote.s3_region or "us-east-1"),
            ]
            if remote.s3_endpoint:
                lines.append("endpoint = %s" % remote.s3_endpoint)

        elif remote_type == "gdrive":
            lines = [
                "[remote]",
                "type = drive",
                "scope = drive",
                "service_account_file = %s" % remote.gdrive_sa_file,
            ]
            if remote.gdrive_root_folder_id:
                lines.append("root_folder_id = %s" % remote.gdrive_root_folder_id)

        elif remote_type == "rclone":
            os.close(fd)
            _extract_rclone_section(
                remote.rclone_config_path,
                remote.rclone_remote_name,
                tmpfile,
                section_name="remote",
            )
            return tmpfile

        else:
            os.close(fd)
            os.unlink(tmpfile)
            raise ValueError("Unknown REMOTE_TYPE for rclone: %s" % remote_type)

        content = "\n".join(lines) + "\n"
        os.write(fd, content.encode())
        os.close(fd)

    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmpfile)
        except OSError:
            pass
        raise

    return tmpfile


def _build_source_rclone_config(target, work_dir) -> str:
    """Build a temporary rclone config for source-side rclone operations.

    Returns the path to the temp config file.
    """
    old_umask = os.umask(0o077)
    try:
        fd, tmpfile = tempfile.mkstemp(
            prefix="gniza-source-rclone-", suffix=".conf",
            dir=str(work_dir),
        )
    finally:
        os.umask(old_umask)

    try:
        source_type = target.source_type

        if source_type == "s3":
            lines = [
                "[gniza-source]",
                "type = s3",
                "provider = %s" % (target.source_s3_provider or "AWS"),
                "access_key_id = %s" % (target.source_s3_access_key_id or ""),
                "secret_access_key = %s" % (target.source_s3_secret_access_key or ""),
                "region = %s" % (target.source_s3_region or "us-east-1"),
                "endpoint = %s" % (target.source_s3_endpoint or ""),
            ]

        elif source_type == "gdrive":
            lines = [
                "[gniza-source]",
                "type = drive",
                "service_account_file = %s" % (target.source_gdrive_sa_file or ""),
                "root_folder_id = %s" % (target.source_gdrive_root_folder_id or ""),
            ]

        elif source_type == "rclone":
            os.close(fd)
            _extract_rclone_section(
                target.source_rclone_config_path,
                target.source_rclone_remote_name,
                tmpfile,
                section_name="gniza-source",
            )
            return tmpfile

        else:
            os.close(fd)
            os.unlink(tmpfile)
            raise ValueError("Unknown source type for rclone: %s" % source_type)

        content = "\n".join(lines) + "\n"
        os.write(fd, content.encode())
        os.close(fd)

    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmpfile)
        except OSError:
            pass
        raise

    return tmpfile


def _extract_rclone_section(
    config_path: str,
    remote_name: str,
    output_path: str,
    section_name: str = "remote",
) -> None:
    """Extract a named section from an rclone config file, renaming it."""
    if not config_path:
        r = subprocess.run(
            ["rclone", "config", "file"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            raise RuntimeError("Cannot determine rclone config path")
        config_path = r.stdout.strip().splitlines()[-1]

    if not os.path.isfile(config_path):
        raise FileNotFoundError("Rclone config file not found: %s" % config_path)

    found = False
    in_section = False
    output_lines = []

    with open(config_path) as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                sec_name = stripped[1:-1]
                if sec_name == remote_name:
                    found = True
                    in_section = True
                    output_lines.append("[%s]\n" % section_name)
                    continue
                else:
                    in_section = False
            if in_section:
                output_lines.append(line)

    if not found:
        raise ValueError("Remote section [%s] not found in %s" % (remote_name, config_path))

    with open(output_path, "w") as f:
        f.writelines(output_lines)
    os.chmod(output_path, 0o600)


# ── Path Construction ─────────────────────────────────────────────

def _rclone_remote_path(ctx: "BackupContext", subpath: str = "") -> str:
    """Build the full rclone remote:path string."""
    remote = ctx.remote
    hostname = ctx.hostname
    base = remote.base.rstrip("/")

    if remote.type == "s3":
        path = "%s/%s" % (base, hostname)
        if subpath:
            path = "%s/%s" % (path, subpath)
        return "remote:%s%s" % (remote.s3_bucket, path)
    else:
        # gdrive and generic rclone
        path = "%s/%s" % (base, hostname)
        if subpath:
            path = "%s/%s" % (path, subpath)
        return "remote:%s" % path


# ── Core Command Runner ──────────────────────────────────────────

def rclone_cmd(
    ctx: "BackupContext",
    subcmd: str,
    *args: str,
    timeout: int = 120,
    input_data: Optional[bytes] = None,
    transfer_log: str = "",
) -> subprocess.CompletedProcess:
    """Run an rclone subcommand with auto config lifecycle.

    Creates a temp config, runs the command, cleans up.
    Returns CompletedProcess.
    """
    with RcloneConfig(ctx) as conf:
        cmd = ["rclone", subcmd, "--config", conf]

        bwlimit = ctx.bwlimit
        if bwlimit > 0:
            cmd.append("--bwlimit=%dk" % bwlimit)

        cmd.extend(args)

        logger.debug("rclone %s %s", subcmd, " ".join(args))

        if transfer_log and subcmd in ("copy", "sync"):
            cmd.extend(["--verbose", "--log-file=%s" % transfer_log])
            try:
                with open(transfer_log, "a") as f:
                    f.write("=== rclone %s %s ===\n" % (subcmd, " ".join(args)))
            except OSError:
                pass

        run_kwargs = dict(
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if input_data is not None:
            run_kwargs["input"] = input_data.decode()
        else:
            run_kwargs["stdin"] = subprocess.DEVNULL

        return subprocess.run(cmd, **run_kwargs)


# ── Transfer Functions ────────────────────────────────────────────

def rclone_sync_incremental(
    ctx: "BackupContext",
    local_source: str,
    target_name: str,
    rel_path: str,
    timestamp: str,
    *,
    transfer_log: str = "",
) -> int:
    """Incremental sync: mirrors source to 'current' on remote, moving diffs to snapshot dir.

    Returns 0 on success, 1 on failure.
    """
    try:
        max_retries = int(ctx.settings.ssh_retries or "3")
    except (ValueError, TypeError):
        max_retries = 3

    current_path = _rclone_remote_path(
        ctx, "targets/%s/current/%s" % (target_name, rel_path))
    backup_dir = _rclone_remote_path(
        ctx, "targets/%s/snapshots/%s/%s" % (target_name, timestamp, rel_path))

    if not local_source.endswith("/"):
        local_source = local_source + "/"

    logger.info("CMD: rclone sync %s -> %s (backup-dir: %s)",
                local_source, current_path, backup_dir)

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        logger.debug("rclone sync attempt %d/%d: %s -> %s",
                      attempt, max_retries, local_source, current_path)

        r = rclone_cmd(
            ctx, "sync", local_source, current_path,
            "--backup-dir", backup_dir,
            timeout=3600,
            transfer_log=transfer_log,
        )

        if r.returncode == 0:
            logger.debug("rclone sync succeeded on attempt %d", attempt)
            return 0

        logger.warning("rclone sync failed, attempt %d/%d", attempt, max_retries)
        if attempt < max_retries:
            backoff = attempt * 10
            logger.info("Retrying in %ds...", backoff)
            time.sleep(backoff)

    logger.error("rclone sync failed after %d attempts", max_retries)
    return 1


def rclone_from_remote(
    ctx: "BackupContext",
    subpath: str,
    local_dest: str,
    *,
    transfer_log: str = "",
) -> int:
    """Download from rclone remote to local directory.

    Returns 0 on success, 1 on failure.
    """
    try:
        max_retries = int(ctx.settings.ssh_retries or "3")
    except (ValueError, TypeError):
        max_retries = 3

    remote_src = _rclone_remote_path(ctx, subpath)
    os.makedirs(local_dest, exist_ok=True)

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        logger.debug("rclone copy attempt %d/%d: %s -> %s",
                      attempt, max_retries, remote_src, local_dest)

        r = rclone_cmd(
            ctx, "copy", remote_src, local_dest,
            timeout=3600,
            transfer_log=transfer_log,
        )

        if r.returncode == 0:
            logger.debug("rclone download succeeded on attempt %d", attempt)
            return 0

        logger.warning("rclone download failed, attempt %d/%d", attempt, max_retries)
        if attempt < max_retries:
            backoff = attempt * 10
            logger.info("Retrying in %ds...", backoff)
            time.sleep(backoff)

    logger.error("rclone download failed after %d attempts", max_retries)
    return 1


# ── Snapshot Management ───────────────────────────────────────────

def rclone_list_dirs(ctx: "BackupContext", subpath: str) -> list[str]:
    """List directories at a remote subpath."""
    remote_path = _rclone_remote_path(ctx, subpath)
    r = rclone_cmd(ctx, "lsf", "--dirs-only", remote_path, timeout=60)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    return [d.rstrip("/") for d in r.stdout.strip().splitlines() if d.strip()]


def rclone_list_files(ctx: "BackupContext", subpath: str) -> list[str]:
    """List files at a remote subpath."""
    remote_path = _rclone_remote_path(ctx, subpath)
    r = rclone_cmd(ctx, "lsf", remote_path, timeout=60)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    return [f.strip() for f in r.stdout.strip().splitlines() if f.strip()]


def rclone_cat(ctx: "BackupContext", subpath: str) -> str:
    """Read a remote file's content."""
    remote_path = _rclone_remote_path(ctx, subpath)
    r = rclone_cmd(ctx, "cat", remote_path, timeout=60)
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def rclone_rcat(ctx: "BackupContext", subpath: str, content: str) -> int:
    """Write content to a remote file via rclone rcat.

    Returns 0 on success, 1 on failure.
    """
    remote_path = _rclone_remote_path(ctx, subpath)
    r = rclone_cmd(
        ctx, "rcat", remote_path,
        timeout=60,
        input_data=content.encode(),
    )
    return 0 if r.returncode == 0 else 1


def rclone_purge(ctx: "BackupContext", subpath: str) -> int:
    """Purge (recursively delete) a remote directory.

    Returns 0 on success, 1 on failure.
    """
    remote_path = _rclone_remote_path(ctx, subpath)
    r = rclone_cmd(ctx, "purge", remote_path, timeout=300)
    return 0 if r.returncode == 0 else 1


def _rclone_exists(ctx: "BackupContext", subpath: str) -> bool:
    """Check if a remote path exists."""
    remote_path = _rclone_remote_path(ctx, subpath)
    r = rclone_cmd(ctx, "lsf", remote_path, timeout=30)
    return r.returncode == 0


def rclone_size(ctx: "BackupContext", subpath: str) -> int:
    """Get total size in bytes at a remote subpath."""
    remote_path = _rclone_remote_path(ctx, subpath)
    r = rclone_cmd(ctx, "size", "--json", remote_path, timeout=120)
    if r.returncode != 0:
        return 0
    try:
        data = json.loads(r.stdout)
        return int(data.get("bytes", 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0


def rclone_disk_usage_pct(ctx: "BackupContext") -> int:
    """Return disk usage percentage for rclone remotes.

    gdrive/generic: computed from about --json. s3: returns 0 (no quota).
    """
    remote_type = ctx.remote.type

    if remote_type == "s3":
        return 0

    # gdrive and generic rclone: try rclone about
    r = rclone_cmd(ctx, "about", "remote:", "--json", timeout=30)
    if r.returncode != 0:
        return 0
    try:
        data = json.loads(r.stdout)
        total = data.get("total", 0)
        used = data.get("used", 0)
        if total > 0:
            return int(used * 100 / total)
        return 0
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0


def rclone_list_remote_snapshots(ctx: "BackupContext", target_name: str) -> list[str]:
    """List completed (finalized) remote snapshots, sorted newest first.

    A snapshot is considered complete if it has a .complete marker file.
    """
    snap_subpath = "targets/%s/snapshots" % target_name
    all_dirs = rclone_list_dirs(ctx, snap_subpath)
    if not all_dirs:
        return []

    completed = []
    for d in all_dirs:
        if not d:
            continue
        if _rclone_exists(ctx, "%s/%s/.complete" % (snap_subpath, d)):
            completed.append(d)

    return sorted(completed, reverse=True)


def rclone_finalize_snapshot(
    ctx: "BackupContext",
    target_name: str,
    timestamp: str,
) -> bool:
    """Finalize a remote snapshot by creating .complete marker and updating latest.txt.

    Returns True on success.
    """
    snap_subpath = "targets/%s/snapshots" % target_name

    from datetime import datetime, timezone
    marker = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    rc = rclone_rcat(ctx, "%s/%s/.complete" % (snap_subpath, timestamp), marker)
    if rc != 0:
        logger.error("Failed to create .complete marker for %s/%s", target_name, timestamp)
        return False

    rc = rclone_rcat(ctx, "%s/latest.txt" % snap_subpath, timestamp)
    if rc != 0:
        logger.warning("Failed to update latest.txt for %s", target_name)
    else:
        logger.debug("Updated latest.txt for %s -> %s", target_name, timestamp)

    return True


def rclone_clean_partial_snapshots(ctx: "BackupContext", target_name: str) -> None:
    """Purge incomplete (no .complete marker) snapshot directories."""
    snap_subpath = "targets/%s/snapshots" % target_name
    all_dirs = rclone_list_dirs(ctx, snap_subpath)
    if not all_dirs:
        return

    log = logger

    for d in all_dirs:
        if not d:
            continue
        if not _rclone_exists(ctx, "%s/%s/.complete" % (snap_subpath, d)):
            log.info("Purging incomplete snapshot for %s: %s", target_name, d)
            rc = rclone_purge(ctx, "%s/%s" % (snap_subpath, d))
            if rc != 0:
                log.warning("Failed to purge incomplete snapshot: %s", d)
