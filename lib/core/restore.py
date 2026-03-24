"""Restore orchestration — restore from snapshots.

Ports lib/restore.sh to Python.  Supports full target restore,
single-folder restore, and listing snapshot contents.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.core.context import BackupContext

from lib.core.context import BackupContext
from lib.core.logging import get_logger
from lib.core.snapshot import resolve_snapshot_timestamp, get_snapshot_dir
from lib.core.utils import shquote
from lib.ssh import SSHOpts


def _rsync_download(ctx: BackupContext, remote_path: str, local_path: str) -> int:
    """Download from SSH remote to local via rsync.

    Mirrors the Bash _rsync_download() helper.
    Returns 0 on success, non-zero on failure.
    """
    ssh = SSHOpts.for_remote(ctx.remote)
    rsync_ssh = ssh.rsync_ssh_string()

    rsync_opts = ["-aHAX", "--numeric-ids"]

    restricted = False  # TODO: detect restricted shell if needed
    if not restricted:
        rsync_path = "rsync --fake-super"
        if (ctx.remote.sudo or "no").lower() == "yes":
            rsync_path = "sudo rsync --fake-super"
        rsync_opts.append("--rsync-path=%s" % rsync_path)

    source_spec = "%s@%s:%s" % (ssh.user, ssh.host, remote_path)

    args = ["rsync"] + rsync_opts + ["-e", rsync_ssh, source_spec, local_path]

    run_env = ssh.env()
    if ssh._is_password:
        args = ["sshpass", "-e"] + args

    try:
        r = subprocess.run(args, capture_output=True, env=run_env, timeout=3600)
        return r.returncode
    except Exception:
        return 1


def restore_target(
    target_name: str,
    snapshot_ts: str = "latest",
    remote_name: str = "",
    dest_dir: str = "",
    skip_mysql: bool = False,
    skip_postgresql: bool = False,
    skip_crontab: bool = False,
) -> int:
    """Restore all folders from a snapshot.

    Args:
        target_name: Name of the target to restore.
        snapshot_ts: Snapshot timestamp or "latest".
        remote_name: Remote to restore from.
        dest_dir: Destination directory (empty = restore to original locations).
        skip_mysql: Skip MySQL restore.
        skip_postgresql: Skip PostgreSQL restore.
        skip_crontab: Skip crontab restore.

    Returns 0 on success, 1 on error.
    """
    log = get_logger()

    # Load target and remote
    from lib.config import CONFIG_DIR, WORK_DIR, parse_conf
    from lib.models import Target, Remote, AppSettings

    target_conf = CONFIG_DIR / "targets.d" / ("%s.conf" % target_name)
    if not target_conf.exists():
        log.error("Failed to load target: %s", target_name)
        return 1
    target = Target.from_conf(target_name, parse_conf(target_conf))

    if not remote_name:
        log.error("No remote specified for restore")
        return 1

    remote_conf = CONFIG_DIR / "remotes.d" / ("%s.conf" % remote_name)
    if not remote_conf.exists():
        log.error("Failed to load remote: %s", remote_name)
        return 1

    # Build context
    ctx = BackupContext.create(target_name, remote_name)

    # Resolve snapshot timestamp
    ts = resolve_snapshot_timestamp(ctx, snapshot_ts)
    if not ts:
        log.error("Cannot resolve snapshot: %s", snapshot_ts)
        return 1

    log.info("Restoring target '%s' from snapshot %s (remote: %s)", target_name, ts, remote_name)

    if not dest_dir:
        log.warning("No destination specified; restoring to original locations (IN-PLACE)")

    snap_dir = ctx.snap_dir
    folders = [f.strip() for f in target.folders.split(",") if f.strip()]
    errors = 0

    # Restore folders
    for folder in folders:
        rel_path = folder.lstrip("/")
        if dest_dir:
            restore_dest = os.path.join(dest_dir, rel_path)
        else:
            restore_dest = folder

        try:
            os.makedirs(restore_dest, exist_ok=True)
        except OSError as e:
            log.error("Failed to create destination: %s", restore_dest)
            errors += 1
            continue

        log.info("Restoring %s -> %s", rel_path, restore_dest)

        if ctx.is_rclone_remote:
            from lib.core.rclone import rclone_from_remote
            current_subpath = "targets/%s/current/%s" % (target_name, rel_path)
            rc = rclone_from_remote(ctx, current_subpath, restore_dest)
            if rc != 0:
                log.error("Restore failed for folder: %s", folder)
                errors += 1

        elif ctx.is_local_remote:
            source_path = "%s/%s/%s/" % (snap_dir, ts, rel_path)
            r = subprocess.run(
                ["rsync", "-aHAX", "--numeric-ids", source_path, restore_dest + "/"],
                capture_output=True, timeout=3600,
            )
            if r.returncode != 0:
                log.error("Restore failed for folder: %s", folder)
                errors += 1

        elif ctx.is_ssh_remote:
            source_path = "%s/%s/%s/" % (snap_dir, ts, rel_path)
            rc = _rsync_download(ctx, source_path, restore_dest + "/")
            if rc != 0:
                log.error("Restore failed for folder: %s", folder)
                errors += 1

    # Restore MySQL databases
    if target.mysql_enabled == "yes" and not skip_mysql:
        log.info("Checking for MySQL dumps in snapshot...")
        mysql_restore_dir = tempfile.mkdtemp(prefix="gniza-mysql-restore-")
        mysql_sub = os.path.join(mysql_restore_dir, "_mysql")
        os.makedirs(mysql_sub, exist_ok=True)

        mysql_found = _fetch_dump_subdir(ctx, snap_dir, ts, "_mysql", mysql_sub)

        if mysql_found and _has_dump_files(mysql_sub, "*.sql.gz", "grants.sql"):
            log.info("Found MySQL dumps in snapshot, restoring...")
            from lib.core.db.mysql import restore_databases as mysql_restore
            if not mysql_restore(ctx, mysql_sub):
                log.error("MySQL restore had errors")
                errors += 1
        else:
            log.debug("No MySQL dumps found in snapshot")

        subprocess.run(["rm", "-rf", mysql_restore_dir], capture_output=True, timeout=30)

    elif skip_mysql:
        log.info("Skipping MySQL restore (--skip-mysql)")

    # Restore PostgreSQL databases
    if target.postgresql_enabled == "yes" and not skip_postgresql:
        log.info("Checking for PostgreSQL dumps in snapshot...")
        pgsql_restore_dir = tempfile.mkdtemp(prefix="gniza-pgsql-restore-")
        pgsql_sub = os.path.join(pgsql_restore_dir, "_postgresql")
        os.makedirs(pgsql_sub, exist_ok=True)

        pgsql_found = _fetch_dump_subdir(ctx, snap_dir, ts, "_postgresql", pgsql_sub)

        if pgsql_found and _has_dump_files(pgsql_sub, "*.sql.gz", "roles.sql"):
            log.info("Found PostgreSQL dumps in snapshot, restoring...")
            from lib.core.db.postgresql import restore_databases as pg_restore
            if not pg_restore(ctx, pgsql_sub):
                log.error("PostgreSQL restore had errors")
                errors += 1
        else:
            log.debug("No PostgreSQL dumps found in snapshot")

        subprocess.run(["rm", "-rf", pgsql_restore_dir], capture_output=True, timeout=30)

    elif skip_postgresql:
        log.info("Skipping PostgreSQL restore (--skip-postgresql)")

    # Restore crontabs
    if target.crontab_enabled == "yes" and not skip_crontab:
        log.info("Checking for crontab dumps in snapshot...")
        crontab_restore_dir = tempfile.mkdtemp(prefix="gniza-crontab-restore-")
        crontab_sub = os.path.join(crontab_restore_dir, "_crontab")
        os.makedirs(crontab_sub, exist_ok=True)

        crontab_found = _fetch_dump_subdir(ctx, snap_dir, ts, "_crontab", crontab_sub)

        if crontab_found and os.listdir(crontab_sub):
            log.info("Found crontab dumps in snapshot, files available for manual restore")
            from lib.core.db.crontab import restore_crontabs
            restore_crontabs(ctx, crontab_sub)
        else:
            log.debug("No crontab dumps found in snapshot")

        subprocess.run(["rm", "-rf", crontab_restore_dir], capture_output=True, timeout=30)

    elif skip_crontab:
        log.info("Skipping crontab restore (--skip-crontab)")

    if errors > 0:
        log.error("Restore completed with %d error(s)", errors)
        return 1

    log.info("Restore completed successfully for %s", target_name)
    return 0


def restore_folder(
    target_name: str,
    folder_path: str,
    snapshot_ts: str = "latest",
    remote_name: str = "",
    dest_dir: str = "",
) -> int:
    """Restore a single folder from a snapshot.

    Returns 0 on success, 1 on error.
    """
    log = get_logger()

    # Load target and remote
    from lib.config import CONFIG_DIR, parse_conf
    from lib.models import Target, Remote, AppSettings

    target_conf = CONFIG_DIR / "targets.d" / ("%s.conf" % target_name)
    if not target_conf.exists():
        log.error("Failed to load target: %s", target_name)
        return 1

    if not remote_name:
        log.error("No remote specified for restore")
        return 1

    remote_conf = CONFIG_DIR / "remotes.d" / ("%s.conf" % remote_name)
    if not remote_conf.exists():
        log.error("Failed to load remote: %s", remote_name)
        return 1

    # Build context
    ctx = BackupContext.create(target_name, remote_name)

    # Resolve snapshot timestamp
    ts = resolve_snapshot_timestamp(ctx, snapshot_ts)
    if not ts:
        log.error("Cannot resolve snapshot: %s", snapshot_ts)
        return 1

    rel_path = folder_path.lstrip("/")
    if dest_dir:
        restore_dest = os.path.join(dest_dir, rel_path)
    else:
        restore_dest = folder_path
        log.warning("No destination specified; restoring to original location (IN-PLACE): %s", folder_path)

    try:
        os.makedirs(restore_dest, exist_ok=True)
    except OSError as e:
        log.error("Failed to create destination: %s", restore_dest)
        return 1

    log.info("Restoring %s -> %s (snapshot: %s)", rel_path, restore_dest, ts)

    snap_dir = ctx.snap_dir
    rc = 0

    if ctx.is_rclone_remote:
        from lib.core.rclone import rclone_from_remote
        current_subpath = "targets/%s/current/%s" % (target_name, rel_path)
        rc = rclone_from_remote(ctx, current_subpath, restore_dest)

    elif ctx.is_local_remote:
        source_path = "%s/%s/%s/" % (snap_dir, ts, rel_path)
        r = subprocess.run(
            ["rsync", "-aHAX", "--numeric-ids", source_path, restore_dest + "/"],
            capture_output=True, timeout=3600,
        )
        rc = r.returncode

    elif ctx.is_ssh_remote:
        source_path = "%s/%s/%s/" % (snap_dir, ts, rel_path)
        rc = _rsync_download(ctx, source_path, restore_dest + "/")

    if rc != 0:
        log.error("Restore failed for %s", folder_path)
        return 1

    log.info("Restore completed for %s", folder_path)
    return 0


def list_snapshot_contents(
    target_name: str,
    snapshot_ts: str = "latest",
    remote_name: str = "",
) -> list[str]:
    """List files in a snapshot.

    Returns a list of file paths, or empty list on error.
    """
    log = get_logger()

    from lib.config import CONFIG_DIR, parse_conf

    if not remote_name:
        log.error("No remote specified")
        return []

    remote_conf = CONFIG_DIR / "remotes.d" / ("%s.conf" % remote_name)
    if not remote_conf.exists():
        log.error("Failed to load remote: %s", remote_name)
        return []

    ctx = BackupContext.create(target_name, remote_name)

    ts = resolve_snapshot_timestamp(ctx, snapshot_ts)
    if not ts:
        log.error("Cannot resolve snapshot: %s", snapshot_ts)
        return []

    snap_dir = ctx.snap_dir

    if ctx.is_rclone_remote:
        from lib.core.rclone import rclone_list_files
        current_subpath = "targets/%s/current" % target_name
        return rclone_list_files(ctx, current_subpath)

    elif ctx.is_local_remote:
        snap_path = "%s/%s" % (snap_dir, ts)
        files = []
        try:
            for root, _dirs, filenames in os.walk(snap_path):
                for fname in filenames:
                    files.append(os.path.join(root, fname))
        except OSError:
            pass
        return files

    elif ctx.is_ssh_remote:
        ssh = SSHOpts.for_remote(ctx.remote)
        snap_path = "%s/%s" % (snap_dir, ts)
        r = ssh.run(
            "find %s -type f 2>/dev/null" % shquote(snap_path),
            timeout=60,
        )
        if r.returncode == 0 and r.stdout.strip():
            return [line.strip() for line in r.stdout.strip().splitlines() if line.strip()]

    return []


# ── Private helpers ───────────────────────────────────────────────


def _fetch_dump_subdir(
    ctx: BackupContext,
    snap_dir: str,
    ts: str,
    subdir_name: str,
    local_dest: str,
) -> bool:
    """Fetch a dump subdirectory (_mysql, _postgresql, _crontab) from the snapshot.

    Returns True if the subdirectory was found and fetched.
    """
    if ctx.is_rclone_remote:
        from lib.core.rclone import rclone_from_remote
        subpath = "targets/%s/current/%s" % (ctx.target.name, subdir_name)
        try:
            rc = rclone_from_remote(ctx, subpath, local_dest)
            return rc == 0
        except Exception:
            return False

    elif ctx.is_local_remote:
        source = "%s/%s/%s/" % (snap_dir, ts, subdir_name)
        if os.path.isdir(source.rstrip("/")):
            r = subprocess.run(
                ["rsync", "-aHAX", source, local_dest + "/"],
                capture_output=True, timeout=300,
            )
            return r.returncode == 0
        return False

    elif ctx.is_ssh_remote:
        source = "%s/%s/%s/" % (snap_dir, ts, subdir_name)
        try:
            rc = _rsync_download(ctx, source, local_dest + "/")
            return rc == 0
        except Exception:
            return False

    return False


def _has_dump_files(directory: str, glob_pattern: str, alt_file: str) -> bool:
    """Check if a directory has dump files matching the pattern or alt file."""
    import glob as glob_mod
    found_glob = glob_mod.glob(os.path.join(directory, glob_pattern))
    found_alt = os.path.isfile(os.path.join(directory, alt_file))
    return bool(found_glob) or found_alt
