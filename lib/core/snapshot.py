"""Snapshot management — list, resolve, finalize, partial cleanup."""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.core.context import BackupContext
    from lib.models import Remote

from lib.ssh import SSHOpts

_TS_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{6}$')


def get_snapshot_dir(target_name: str, remote: Remote, hostname: str) -> str:
    """Get the snapshot directory path: base/hostname/targets/target_name/snapshots"""
    base = remote.base.rstrip("/")
    return "%s/%s/targets/%s/snapshots" % (base, hostname, target_name)


def list_snapshots(ctx: BackupContext) -> list[str]:
    """List completed snapshots (no .partial), sorted newest first.

    Handles local, SSH, and rclone remotes.
    """
    snap_dir = ctx.snap_dir

    if ctx.is_local_remote:
        try:
            entries = os.listdir(snap_dir)
        except FileNotFoundError:
            return []
        snaps = [e for e in entries if _TS_RE.match(e) and not e.endswith('.partial')]
        return sorted(snaps, reverse=True)

    elif ctx.is_ssh_remote:
        ssh = SSHOpts.for_remote(ctx.remote)
        from lib.core.utils import shquote
        cmd = "ls -1d %s/[0-9]* 2>/dev/null | grep -v '\\.partial$' | sort -r" % shquote(snap_dir)
        r = ssh.run(cmd, timeout=30)
        if r.returncode != 0 or not r.stdout.strip():
            return []
        lines = r.stdout.strip().splitlines()
        return [os.path.basename(line.strip()) for line in lines if line.strip()]

    elif ctx.is_rclone_remote:
        from lib.core.rclone import rclone_list_remote_snapshots
        return rclone_list_remote_snapshots(ctx, ctx.target.name)

    else:
        return []


def get_latest_snapshot(ctx: BackupContext) -> str | None:
    """Get the most recent completed snapshot timestamp."""
    snaps = list_snapshots(ctx)
    return snaps[0] if snaps else None


def resolve_snapshot_timestamp(ctx: BackupContext, requested: str) -> str | None:
    """Resolve a snapshot timestamp — 'latest'/empty returns latest, otherwise verify it exists."""
    from lib.core.logging import get_logger
    log = get_logger()

    if not requested or requested.upper() == "LATEST":
        return get_latest_snapshot(ctx)

    snap_dir = ctx.snap_dir

    if ctx.is_local_remote:
        snap_path = os.path.join(snap_dir, requested)
        if os.path.isdir(snap_path):
            return requested
        log.error("Snapshot not found for %s: %s" % (ctx.target.name, requested))
        return None

    elif ctx.is_ssh_remote:
        ssh = SSHOpts.for_remote(ctx.remote)
        from lib.core.utils import shquote
        r = ssh.run("test -d %s" % shquote("%s/%s" % (snap_dir, requested)), timeout=15)
        if r.returncode == 0:
            return requested
        log.error("Snapshot not found for %s: %s" % (ctx.target.name, requested))
        return None

    return None


def clean_partial_snapshots(ctx: BackupContext) -> None:
    """Remove any leftover .partial snapshot directories."""
    snap_dir = ctx.snap_dir
    from lib.core.logging import get_logger
    log = get_logger()

    if ctx.is_local_remote:
        import glob
        partials = glob.glob(os.path.join(snap_dir, "*.partial"))
        if partials:
            log.info("Cleaning partial snapshots for %s..." % ctx.target.name)
            for p in partials:
                try:
                    subprocess.run(["rm", "-rf", p], capture_output=True, timeout=60)
                except Exception:
                    try:
                        subprocess.run(["sudo", "rm", "-rf", p], capture_output=True, timeout=60)
                    except Exception:
                        log.warning("Failed to clean partial snapshot: %s" % p)

    elif ctx.is_ssh_remote:
        ssh = SSHOpts.for_remote(ctx.remote)
        from lib.core.utils import shquote
        sq = shquote(snap_dir)
        r = ssh.run("ls -1d %s/*.partial 2>/dev/null" % sq, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            log.info("Cleaning partial snapshots for %s..." % ctx.target.name)
            ssh.run("rm -rf %s/*.partial 2>/dev/null || sudo rm -rf %s/*.partial 2>/dev/null" % (sq, sq), timeout=120)

    elif ctx.is_rclone_remote:
        from lib.core.rclone import rclone_clean_partial_snapshots as _rclone_clean
        _rclone_clean(ctx, ctx.target.name)


def finalize_snapshot(ctx: BackupContext) -> bool:
    """Rename .partial to final, update 'latest' symlink.

    Returns True on success.
    """
    snap_dir = ctx.snap_dir
    partial = "%s/%s.partial" % (snap_dir, ctx.timestamp)
    final = "%s/%s" % (snap_dir, ctx.timestamp)
    from lib.core.logging import get_logger
    log = get_logger()

    if ctx.is_local_remote:
        try:
            os.rename(partial, final)
        except OSError as e:
            log.error("Failed to finalize snapshot: %s" % e)
            return False
        # Update latest symlink
        try:
            latest_path = os.path.join(snap_dir, "..", "latest")
            if os.path.islink(latest_path):
                os.unlink(latest_path)
            os.symlink("snapshots/%s" % ctx.timestamp, latest_path)
        except OSError:
            pass
        return True

    elif ctx.is_ssh_remote:
        ssh = SSHOpts.for_remote(ctx.remote)
        from lib.core.utils import shquote
        sq_partial = shquote(partial)
        sq_final = shquote(final)
        r = ssh.run("mv %s %s" % (sq_partial, sq_final), timeout=30)
        if r.returncode != 0:
            log.error("Failed to finalize snapshot: %s" % r.stderr.strip())
            return False
        # Update latest symlink
        latest = "%s/../latest" % snap_dir
        sq_latest = shquote(latest)
        ssh.run("rm -f %s && ln -s snapshots/%s %s" % (sq_latest, ctx.timestamp, sq_latest), timeout=10)
        return True

    elif ctx.is_rclone_remote:
        from lib.core.rclone import rclone_finalize_snapshot as _rclone_finalize
        return _rclone_finalize(ctx, ctx.target.name, ctx.timestamp)

    return False


def update_latest_symlink(ctx: BackupContext, timestamp: str) -> bool:
    """Update the 'latest' symlink to point to a specific snapshot."""
    snap_dir = ctx.snap_dir
    base = snap_dir.rsplit("/snapshots", 1)[0]
    from lib.core.logging import get_logger
    log = get_logger()

    if ctx.is_local_remote:
        latest_path = os.path.join(base, "latest")
        try:
            if os.path.islink(latest_path):
                os.unlink(latest_path)
            os.symlink("%s/%s" % (snap_dir, timestamp), latest_path)
            return True
        except OSError:
            log.warning("Failed to update latest symlink for %s" % ctx.target.name)
            return False

    elif ctx.is_ssh_remote:
        ssh = SSHOpts.for_remote(ctx.remote)
        from lib.core.utils import shquote
        sq_snap_ts = shquote("%s/%s" % (snap_dir, timestamp))
        sq_latest = shquote("%s/latest" % base)
        r = ssh.run("ln -sfn %s %s" % (sq_snap_ts, sq_latest), timeout=10)
        if r.returncode != 0:
            log.warning("Failed to update latest symlink for %s" % ctx.target.name)
            return False
        return True

    return False


def count_partial_snapshots(ctx: BackupContext) -> int:
    """Count .partial snapshot directories."""
    snap_dir = ctx.snap_dir

    if ctx.is_local_remote:
        import glob
        return len(glob.glob(os.path.join(snap_dir, "*.partial")))

    elif ctx.is_ssh_remote:
        ssh = SSHOpts.for_remote(ctx.remote)
        from lib.core.utils import shquote
        r = ssh.run("ls -1d %s/*.partial 2>/dev/null | wc -l" % shquote(snap_dir), timeout=15)
        try:
            return int(r.stdout.strip())
        except (ValueError, AttributeError):
            return 0

    return 0


def is_snapshot_pinned(ctx: BackupContext, snapshot: str) -> bool:
    """Check if a snapshot has pinned=true in its meta.json."""
    snap_dir = ctx.snap_dir
    meta_path = "%s/%s/meta.json" % (snap_dir, snapshot)

    if ctx.is_local_remote:
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            return meta.get("pinned", False) is True
        except (OSError, json.JSONDecodeError):
            return False

    elif ctx.is_ssh_remote:
        ssh = SSHOpts.for_remote(ctx.remote)
        from lib.core.utils import shquote
        r = ssh.run("cat %s 2>/dev/null" % shquote(meta_path), timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            try:
                meta = json.loads(r.stdout)
                return meta.get("pinned", False) is True
            except json.JSONDecodeError:
                pass

    return False
