"""Backup orchestration — the main backup_target() flow.

Ports lib/backup.sh to Python.  Replicates the exact 20-step flow,
delegating to Phase 0-4 core modules for all heavy lifting.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lib.models import AppSettings

from lib.core.context import BackupContext
from lib.core.locking import TargetLock
from lib.core.logging import get_logger, setup_backup_logger
from lib.core.snapshot import (
    list_snapshots,
    get_latest_snapshot,
    clean_partial_snapshots,
    finalize_snapshot,
)
from lib.core.retention import enforce_retention
from lib.core.transfer import (
    transfer_to_remote,
    transfer_local,
    transfer_ssh_to_local,
    transfer_ssh_to_ssh,
    build_filter_args,
)
from lib.core.source import pull_folder_from_source
from lib.core.utils import make_timestamp, human_size, human_duration, shquote


def backup_target(
    target_name: str,
    remote_name: str | None = None,
    settings: AppSettings | None = None,
    schedule_retention_count: int | None = None,
) -> int:
    """Run a backup for a single target.

    Returns 0 on success, 1 on error, 2 on skip (disabled / lock conflict).

    The orchestration flow (matching backup.sh):
      0.  Acquire per-target lock
      1.  Load and validate target config
      2.  Determine remote (explicit or from target/schedule/default)
      3.  Load remote config, create BackupContext
      4.  Test remote connectivity
      4.5 Check remote disk space
      5.  Get timestamp
      6.  Get previous snapshot (for --link-dest)
      7.  Clean partial snapshots
      8.  Run pre-backup hook
      8.5 Dump databases (MySQL, PostgreSQL, crontab)
      8.9 Create .partial directory on destination
      9.  Transfer all folders + dump artifacts
      9.9 (snaplog — deferred)
      10. Generate meta.json
      11. (snaplog upload — deferred)
      12. Finalize snapshot (.partial -> final)
      13. Update meta.json with total_size
      14. Run post-backup hook
      15. Enforce retention
    """
    log = get_logger()

    # Step 1: Load and validate target
    from lib.config import CONFIG_DIR, WORK_DIR, parse_conf, list_conf_dir
    from lib.models import Target, Remote, AppSettings as AS

    target_conf = CONFIG_DIR / "targets.d" / ("%s.conf" % target_name)
    if not target_conf.exists():
        log.error("Target not found: %s", target_name)
        return 1
    target = Target.from_conf(target_name, parse_conf(target_conf))

    if target.enabled != "yes":
        log.info("Target '%s' is disabled, skipping", target_name)
        return 0  # match Bash: returns 0 for disabled

    # Step 0: Acquire per-target lock
    lock = TargetLock(target_name, WORK_DIR)
    if not lock.acquire():
        log.warning("Skipping target '%s': previous backup still running", target_name)
        return 2

    try:
        # Step 2: Determine which remote to use
        if not remote_name:
            if target.remote:
                remote_name = target.remote
            else:
                remotes = list_conf_dir("remotes.d")
                if remotes:
                    remote_name = remotes[0]

        if not remote_name:
            log.error("No remote specified and none configured")
            return 1

        # Step 3: Load remote, build context
        remote_conf = CONFIG_DIR / "remotes.d" / ("%s.conf" % remote_name)
        if not remote_conf.exists():
            log.error("Failed to load remote: %s", remote_name)
            return 1

        if not settings:
            settings = AS.from_conf(parse_conf(CONFIG_DIR / "gniza.conf"))

        ts = make_timestamp()
        ctx = BackupContext.create(target_name, remote_name, timestamp=ts,
                                   job_id=os.environ.get("GNIZA_JOB_ID", ""))

        rc = _backup_target_impl(ctx, target_name, remote_name, ts, settings,
                                  schedule_retention_count=schedule_retention_count)
        return rc

    finally:
        lock.release()


def _backup_target_impl(
    ctx: BackupContext,
    target_name: str,
    remote_name: str,
    ts: str,
    settings: "AppSettings",
    schedule_retention_count: int | None = None,
) -> int:
    """Internal backup implementation after lock is acquired and context is loaded."""
    log = get_logger()
    start_time = time.time()
    target = ctx.target
    restricted_shell = False

    # Step 4: Test remote connectivity
    if ctx.is_ssh_remote:
        from lib.ssh import SSHOpts
        ssh = SSHOpts.for_remote(ctx.remote)
        r = ssh.run("echo ok", timeout=30)
        if r.returncode == 0:
            log.info("SSH connection successful")
        else:
            # Try restricted shell detection (e.g. Hetzner Storage Box)
            r2 = ssh.run("ls .", timeout=30)
            if r2.returncode == 0:
                log.info("SSH connection successful (restricted shell detected)")
                restricted_shell = True
            else:
                log.error("Cannot connect to remote '%s'", remote_name)
                return 1
    elif ctx.is_local_remote:
        base = ctx.remote.base.rstrip("/")
        if not os.path.isdir(base):
            log.info("Creating local remote base directory: %s", base)
            try:
                os.makedirs(base, exist_ok=True)
            except OSError as e:
                log.error("Failed to create remote base directory: %s", e)
                return 1
    elif ctx.is_rclone_remote:
        from lib.core.rclone import rclone_cmd
        r = rclone_cmd(ctx, "about", "remote:", timeout=30)
        if r.returncode != 0:
            log.error("Cannot connect to remote '%s' (%s)", remote_name, ctx.remote.type)
            return 1

    # Step 4.5: Check remote disk space
    try:
        threshold = int(ctx.settings.disk_usage_threshold or "95")
    except (ValueError, TypeError):
        threshold = 95

    if threshold > 0:
        if not _check_remote_disk_space(ctx, threshold):
            log.error("Remote '%s' has insufficient disk space", remote_name)
            return 1

    # Step 5: Timestamp already set (ts)

    # Step 6: Get previous snapshot for --link-dest
    prev = get_latest_snapshot(ctx)
    if prev:
        log.debug("Previous snapshot for %s: %s", target_name, prev)
        # Update context with prev_snapshot (frozen dataclass — rebuild)
        ctx = BackupContext(
            target=ctx.target, remote=ctx.remote, settings=ctx.settings,
            hostname=ctx.hostname, timestamp=ctx.timestamp,
            prev_snapshot=prev, job_id=ctx.job_id,
            work_dir=ctx.work_dir, log_dir=ctx.log_dir,
        )

    # Step 7: Clean partial snapshots
    clean_partial_snapshots(ctx)

    # Step 8: Run pre-hook
    if target.pre_hook:
        log.info("Running pre-hook for %s...", target_name)
        try:
            r = subprocess.run(
                target.pre_hook, shell=True,  # noqa: S602  — intentional, user-configured
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode != 0:
                log.error("Pre-hook failed for %s", target_name)
                return 1
        except subprocess.TimeoutExpired:
            log.error("Pre-hook timed out for %s", target_name)
            return 1

    # Steps 8.5-8.7: Dump databases and crontabs
    mysql_dump_dir = ""
    pgsql_dump_dir = ""
    crontab_dump_dir = ""

    source_type = target.source_type or "local"
    cloud_sources = ("s3", "gdrive", "rclone")

    if target.mysql_enabled == "yes" and source_type not in cloud_sources:
        dump_dir = tempfile.mkdtemp(prefix="gniza-mysql-dump-")
        log.info("Dumping MySQL databases for %s...", target_name)
        try:
            from lib.core.db.mysql import dump_databases as mysql_dump, dump_grants as mysql_grants
            if mysql_dump(ctx, dump_dir):
                mysql_grants(ctx, dump_dir) or log.warning("Grants dump failed, continuing with database dumps")
                mysql_dump_dir = dump_dir
            else:
                log.warning("MySQL dump failed for %s -- continuing with file backup", target_name)
                subprocess.run(["rm", "-rf", dump_dir], capture_output=True, timeout=30)
        except Exception as e:
            log.warning("MySQL dump failed for %s: %s -- continuing with file backup", target_name, e)
            subprocess.run(["rm", "-rf", dump_dir], capture_output=True, timeout=30)

    if target.postgresql_enabled == "yes" and source_type not in cloud_sources:
        dump_dir = tempfile.mkdtemp(prefix="gniza-pgsql-dump-")
        log.info("Dumping PostgreSQL databases for %s...", target_name)
        try:
            from lib.core.db.postgresql import dump_databases as pg_dump, dump_roles as pg_roles
            if pg_dump(ctx, dump_dir):
                pg_roles(ctx, dump_dir) or log.warning("Roles dump failed, continuing with database dumps")
                pgsql_dump_dir = dump_dir
            else:
                log.warning("PostgreSQL dump failed for %s -- continuing with file backup", target_name)
                subprocess.run(["rm", "-rf", dump_dir], capture_output=True, timeout=30)
        except Exception as e:
            log.warning("PostgreSQL dump failed for %s: %s -- continuing with file backup", target_name, e)
            subprocess.run(["rm", "-rf", dump_dir], capture_output=True, timeout=30)

    if target.crontab_enabled == "yes":
        dump_dir = tempfile.mkdtemp(prefix="gniza-crontab-dump-")
        log.info("Dumping crontabs for %s...", target_name)
        try:
            from lib.core.db.crontab import dump_crontabs
            if dump_crontabs(ctx, dump_dir):
                crontab_dump_dir = dump_dir
            else:
                log.warning("Crontab dump failed for %s -- continuing with file backup", target_name)
                subprocess.run(["rm", "-rf", dump_dir], capture_output=True, timeout=30)
        except Exception as e:
            log.warning("Crontab dump failed for %s: %s -- continuing with file backup", target_name, e)
            subprocess.run(["rm", "-rf", dump_dir], capture_output=True, timeout=30)

    # Step 8.9: Create .partial snapshot directory on destination
    snap_dir = ctx.snap_dir
    if ctx.is_rclone_remote:
        pass  # rclone handles directory creation automatically
    elif ctx.is_local_remote:
        partial_path = "%s/%s.partial" % (snap_dir, ts)
        try:
            os.makedirs(partial_path, exist_ok=True)
        except OSError as e:
            log.error("Failed to create local .partial directory: %s", e)
            _cleanup_dump_dirs(mysql_dump_dir, pgsql_dump_dir, crontab_dump_dir)
            return 1
    elif ctx.is_ssh_remote:
        from lib.ssh import SSHOpts
        ssh = SSHOpts.for_remote(ctx.remote)
        partial_path = "%s/%s.partial" % (snap_dir, ts)
        r = ssh.run("mkdir -p %s" % shquote(partial_path), timeout=30)
        if r.returncode != 0:
            log.error("Failed to create remote .partial directory")
            _cleanup_dump_dirs(mysql_dump_dir, pgsql_dump_dir, crontab_dump_dir)
            return 1

    # Step 9: Transfer all folders and dump artifacts
    transfer_failed = False
    transfer_failed = _transfer_all_folders(
        ctx, target_name, ts, prev, threshold, restricted_shell,
    )

    if not transfer_failed:
        transfer_failed = _transfer_dump_artifacts(
            ctx, target_name, ts, prev, threshold,
            mysql_dump_dir, pgsql_dump_dir, crontab_dump_dir,
        )

    if transfer_failed:
        log.error("One or more folder transfers failed for %s", target_name)
        _cleanup_dump_dirs(mysql_dump_dir, pgsql_dump_dir, crontab_dump_dir)
        return 1

    # Step 10: Generate meta.json
    _generate_meta_json(ctx, target_name, ts, start_time)

    # Step 12: Finalize snapshot (.partial -> final)
    if not finalize_snapshot(ctx):
        log.error("Failed to finalize snapshot for %s", target_name)
        _cleanup_dump_dirs(mysql_dump_dir, pgsql_dump_dir, crontab_dump_dir)
        return 1

    # Step 13: Update meta.json with total_size (best effort)
    end_time = time.time()
    duration = int(end_time - start_time)
    # total_size update is deferred (matches Bash: needs rsync stats parsing)

    log.info("Backup completed for %s: %s (%s)", target_name, ts, human_duration(duration))

    # Step 14: Run post-hook
    if target.post_hook:
        log.info("Running post-hook for %s...", target_name)
        try:
            subprocess.run(
                target.post_hook, shell=True,  # noqa: S602  — intentional, user-configured
                capture_output=True, text=True, timeout=300,
            )
        except Exception as e:
            log.warning("Post-hook failed for %s: %s", target_name, e)

    # Step 15: Enforce retention
    try:
        enforce_retention(ctx, override_count=schedule_retention_count)
    except Exception as e:
        log.warning("Retention cleanup failed: %s", e)

    # Cleanup
    _cleanup_dump_dirs(mysql_dump_dir, pgsql_dump_dir, crontab_dump_dir)

    return 0


def backup_all_targets(
    remote_name: str | None = None,
    settings: AppSettings | None = None,
) -> int:
    """Backup all enabled targets.

    Returns 0 on full success, 1 on all-fail, EXIT_PARTIAL (3) on mixed.
    """
    from lib.config import list_conf_dir, CONFIG_DIR, parse_conf
    from lib.models import AppSettings as AS

    log = get_logger()
    targets = list_conf_dir("targets.d")
    if not targets:
        log.error("No targets configured")
        return 1

    if not settings:
        settings = AS.from_conf(parse_conf(CONFIG_DIR / "gniza.conf"))

    # Determine remotes list
    remotes = [remote_name] if remote_name else list_conf_dir("remotes.d")
    if not remotes:
        log.error("No remotes configured")
        return 1

    start_time = time.time()
    total = 0
    succeeded = 0
    failed = 0

    for t in targets:
        # Pre-load target to check enabled status
        target_conf = CONFIG_DIR / "targets.d" / ("%s.conf" % t)
        if not target_conf.exists():
            continue
        target_data = parse_conf(target_conf)
        if target_data.get("TARGET_ENABLED", "yes") != "yes":
            log.debug("Target '%s' is disabled, skipping", t)
            continue

        total += 1
        log.info("=== Backing up target: %s (%d) ===", t, total)

        target_failed = False
        for rname in remotes:
            if not rname:
                continue
            log.info("--- Transferring %s to remote '%s' ---", t, rname)
            rc = backup_target(t, rname, settings=settings)
            if rc == 1:
                log.error("Backup to remote '%s' failed for %s", rname, t)
                target_failed = True
            elif rc == 2:
                log.info("Target '%s' skipped: previous backup still running", t)

        if target_failed:
            failed += 1
        else:
            succeeded += 1
            log.info("Backup completed for %s (all remotes)", t)

    end_time = time.time()
    duration = int(end_time - start_time)

    log.info("Backup summary: %d total, %d succeeded, %d failed (%s)",
             total, succeeded, failed, human_duration(duration))

    if failed > 0 and succeeded > 0:
        return 3  # EXIT_PARTIAL
    elif failed > 0:
        return 1
    return 0


# ── Private helpers ───────────────────────────────────────────────


def _check_remote_disk_space(ctx: BackupContext, threshold: int) -> bool:
    """Check remote disk usage. Returns True if OK, False if threshold exceeded."""
    log = get_logger()

    if threshold <= 0:
        return True

    if ctx.is_local_remote:
        try:
            r = subprocess.run(
                ["df", "--output=pcent", ctx.snap_dir],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                for line in r.stdout.strip().splitlines()[1:]:
                    pct = int(line.strip().rstrip("%"))
                    if pct >= threshold:
                        log.error("Disk space threshold exceeded (%d%% >= %d%%)", pct, threshold)
                        return False
        except Exception:
            pass
        return True

    elif ctx.is_ssh_remote:
        from lib.ssh import SSHOpts
        ssh = SSHOpts.for_remote(ctx.remote)
        base = ctx.remote.base.rstrip("/")
        cmd = "df --output=pcent %s 2>/dev/null | tail -1" % shquote(base)
        try:
            r = ssh.run(cmd, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                pct = int(r.stdout.strip().rstrip("%"))
                if pct >= threshold:
                    log.error("Disk space threshold exceeded (%d%% >= %d%%)", pct, threshold)
                    return False
        except Exception:
            pass
        return True

    elif ctx.is_rclone_remote:
        from lib.core.rclone import rclone_disk_usage_pct
        pct = rclone_disk_usage_pct(ctx)
        if pct > 0 and pct >= threshold:
            log.error("Disk space threshold exceeded (%d%% >= %d%%)", pct, threshold)
            return False
        return True

    return True


def _transfer_all_folders(
    ctx: BackupContext,
    target_name: str,
    ts: str,
    prev: str | None,
    threshold: int,
    restricted_shell: bool,
) -> bool:
    """Transfer all target folders. Returns True if any transfer failed."""
    log = get_logger()
    target = ctx.target
    snap_dir = ctx.snap_dir
    source_type = target.source_type or "local"
    folders = [f.strip() for f in target.folders.split(",") if f.strip()]
    transfer_failed = False
    folder_index = 0

    for folder in folders:
        # Check disk space between folders (skip first)
        if folder_index > 0 and threshold > 0:
            if not _check_remote_disk_space(ctx, threshold):
                log.error("Disk space threshold exceeded -- aborting after %d folder(s)", folder_index)
                return True
        folder_index += 1

        rel_path = folder.lstrip("/")
        if not rel_path:
            rel_path = "."
        link_dest = "%s/%s/%s" % (snap_dir, prev, rel_path) if prev else ""

        if source_type != "local":
            if (source_type == "ssh" and ctx.is_ssh_remote and not restricted_shell):
                # Pipelined: direct SSH source -> SSH destination
                log.info("Pipelined transfer from %s: %s", target.source_host, folder)
                rc = transfer_ssh_to_ssh(
                    ctx, folder, rel_path, ts, link_dest,
                    restricted_shell=restricted_shell,
                )
                if rc != 0:
                    log.error("Pipelined transfer failed for folder: %s", folder)
                    transfer_failed = True

            elif source_type == "ssh" and ctx.is_local_remote:
                # Direct: SSH source -> local .partial
                log.info("Direct transfer from %s: %s", target.source_host, folder)
                rc = transfer_ssh_to_local(ctx, folder, rel_path, ts, link_dest)
                if rc != 0:
                    log.error("Direct transfer failed for folder: %s", folder)
                    transfer_failed = True

            else:
                # Two-hop: pull to local staging, then transfer
                from lib.config import WORK_DIR
                staging_dir = tempfile.mkdtemp(
                    prefix="gniza-source-", dir=str(WORK_DIR),
                )
                log.info("Pulling from %s source: %s", source_type, folder)
                staging_dest = os.path.join(staging_dir, folder.lstrip("/"))
                rc = pull_folder_from_source(ctx, folder, staging_dest)
                if rc != 0:
                    log.error("Source pull failed for: %s", folder)
                    subprocess.run(["rm", "-rf", staging_dir], capture_output=True, timeout=30)
                    transfer_failed = True
                    continue

                rc = _transfer_folder(ctx, staging_dest, rel_path, ts, link_dest)
                if rc != 0:
                    log.error("Transfer failed for folder: %s", folder)
                    transfer_failed = True
                subprocess.run(["rm", "-rf", staging_dir], capture_output=True, timeout=30)
        else:
            # Local source
            rc = _transfer_folder(ctx, folder, rel_path, ts, link_dest)
            if rc != 0:
                log.error("Transfer failed for folder: %s", folder)
                transfer_failed = True

    return transfer_failed


def _transfer_dump_artifacts(
    ctx: BackupContext,
    target_name: str,
    ts: str,
    prev: str | None,
    threshold: int,
    mysql_dump_dir: str,
    pgsql_dump_dir: str,
    crontab_dump_dir: str,
) -> bool:
    """Transfer database dump artifacts. Returns True if any transfer failed."""
    log = get_logger()
    snap_dir = ctx.snap_dir
    transfer_failed = False

    # MySQL dumps
    if mysql_dump_dir:
        mysql_src = os.path.join(mysql_dump_dir, "_mysql")
        if os.path.isdir(mysql_src):
            if threshold > 0 and not _check_remote_disk_space(ctx, threshold):
                log.error("Disk space threshold exceeded -- aborting before MySQL dump transfer")
                return True
            log.info("Transferring MySQL dumps for %s...", target_name)
            link_dest = "%s/%s/_mysql" % (snap_dir, prev) if prev else ""
            rc = _transfer_folder(ctx, mysql_src, "_mysql", ts, link_dest)
            if rc != 0:
                log.error("Transfer failed for MySQL dumps")
                return True

    # PostgreSQL dumps
    if pgsql_dump_dir:
        pgsql_src = os.path.join(pgsql_dump_dir, "_postgresql")
        if os.path.isdir(pgsql_src):
            if threshold > 0 and not _check_remote_disk_space(ctx, threshold):
                log.error("Disk space threshold exceeded -- aborting before PostgreSQL dump transfer")
                return True
            log.info("Transferring PostgreSQL dumps for %s...", target_name)
            link_dest = "%s/%s/_postgresql" % (snap_dir, prev) if prev else ""
            rc = _transfer_folder(ctx, pgsql_src, "_postgresql", ts, link_dest)
            if rc != 0:
                log.error("Transfer failed for PostgreSQL dumps")
                return True

    # Crontab dumps
    if crontab_dump_dir:
        crontab_src = os.path.join(crontab_dump_dir, "_crontab")
        if os.path.isdir(crontab_src):
            if threshold > 0 and not _check_remote_disk_space(ctx, threshold):
                log.error("Disk space threshold exceeded -- aborting before crontab dump transfer")
                return True
            log.info("Transferring crontab dumps for %s...", target_name)
            link_dest = "%s/%s/_crontab" % (snap_dir, prev) if prev else ""
            rc = _transfer_folder(ctx, crontab_src, "_crontab", ts, link_dest)
            if rc != 0:
                log.error("Transfer failed for crontab dumps")
                return True

    return transfer_failed


def _transfer_folder(
    ctx: BackupContext,
    source_dir: str,
    rel_path: str,
    timestamp: str,
    link_dest: str,
) -> int:
    """Transfer a single folder/directory using the appropriate method."""
    if ctx.is_local_remote:
        return transfer_local(ctx, source_dir, rel_path, timestamp, link_dest)
    elif ctx.is_ssh_remote:
        return transfer_to_remote(ctx, source_dir, rel_path, timestamp, link_dest)
    elif ctx.is_rclone_remote:
        from lib.core.rclone import rclone_sync_incremental
        return rclone_sync_incremental(ctx, source_dir, ctx.target.name, rel_path, timestamp)
    return 1


def _generate_meta_json(
    ctx: BackupContext,
    target_name: str,
    ts: str,
    start_time: float,
) -> None:
    """Build and write meta.json to the .partial snapshot directory."""
    log = get_logger()
    target = ctx.target
    snap_dir = ctx.snap_dir

    end_time = time.time()
    duration = int(end_time - start_time)

    meta = {
        "target": target_name,
        "hostname": ctx.hostname,
        "timestamp": ts,
        "duration": duration,
        "folders": target.folders,
        "mysql_dumps": target.mysql_enabled == "yes",
        "postgresql_dumps": target.postgresql_enabled == "yes",
        "crontab_dumps": target.crontab_enabled == "yes",
        "total_size": 0,
        "mode": ctx.settings.backup_mode or "incremental",
        "pinned": False,
    }

    meta_json = json.dumps(meta, indent=2)

    if ctx.is_rclone_remote:
        from lib.core.rclone import rclone_rcat
        meta_subpath = "targets/%s/snapshots/%s/meta.json" % (target_name, ts)
        if rclone_rcat(ctx, meta_subpath, meta_json) != 0:
            log.warning("Failed to write meta.json")

    elif ctx.is_local_remote:
        meta_path = "%s/%s.partial/meta.json" % (snap_dir, ts)
        try:
            with open(meta_path, "w") as f:
                f.write(meta_json)
        except OSError as e:
            log.warning("Failed to write meta.json: %s", e)

    elif ctx.is_ssh_remote:
        from lib.ssh import SSHOpts
        ssh = SSHOpts.for_remote(ctx.remote)
        meta_path = "%s/%s.partial/meta.json" % (snap_dir, ts)
        ssh.run(
            "cat > %s" % shquote(meta_path),
            timeout=15,
            input=meta_json,
            capture_output=False,
        )


def _cleanup_dump_dirs(*dirs: str) -> None:
    """Remove temporary dump directories."""
    for d in dirs:
        if d and os.path.isdir(d):
            subprocess.run(["rm", "-rf", d], capture_output=True, timeout=30)
