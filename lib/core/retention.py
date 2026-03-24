"""Retention policy — prune old snapshots beyond the configured count."""
from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.core.context import BackupContext

from lib.core.logging import get_logger
from lib.core.snapshot import get_snapshot_dir, is_snapshot_pinned, list_snapshots
from lib.ssh import SSHOpts


def enforce_retention(ctx: BackupContext, override_count: int | None = None) -> int:
    """Delete snapshots beyond retention count. Returns number pruned.

    Pinned snapshots are never deleted and don't count toward the limit.
    """
    keep = override_count if override_count is not None else ctx.retention_count
    log = get_logger()

    log.debug("Enforcing retention for %s: keeping %d snapshots" % (ctx.target.name, keep))

    snapshots = list_snapshots(ctx)
    if not snapshots:
        log.debug("No snapshots found for %s, nothing to prune" % ctx.target.name)
        return 0

    # Pre-fetch pinned snapshots for efficiency (avoid N separate checks)
    pinned_set = _prefetch_pinned(ctx, snapshots)

    count = 0
    pruned = 0

    for snap in snapshots:
        if snap in pinned_set:
            log.info("Skipping pinned snapshot for %s: %s" % (ctx.target.name, snap))
            continue

        count += 1
        if count > keep:
            log.info("Pruning old snapshot for %s: %s" % (ctx.target.name, snap))
            if _delete_snapshot(ctx, snap):
                pruned += 1
            else:
                log.warning("Failed to prune snapshot: %s" % snap)

    if pruned > 0:
        log.info("Pruned %d old snapshot(s) for %s" % (pruned, ctx.target.name))

    return pruned


def _prefetch_pinned(ctx: BackupContext, snapshots: list[str]) -> set[str]:
    """Pre-fetch the set of pinned snapshot names (batch for efficiency).

    Matches the Bash optimization that does a single grep -rl for local/SSH
    instead of N per-snapshot checks.
    """
    from lib.core.utils import shquote

    snap_dir = ctx.snap_dir
    pinned: set[str] = set()

    if ctx.is_local_remote:
        import os
        for snap in snapshots:
            meta_path = os.path.join(snap_dir, snap, "meta.json")
            try:
                with open(meta_path) as f:
                    import json
                    meta = json.load(f)
                if meta.get("pinned", False) is True:
                    pinned.add(snap)
            except (OSError, json.JSONDecodeError, ValueError):
                pass

    elif ctx.is_ssh_remote:
        ssh = SSHOpts.for_remote(ctx.remote)
        sq = shquote(snap_dir)
        r = ssh.run(
            "grep -rl '\"pinned\".*true' %s/*/meta.json 2>/dev/null"
            " | while read -r f; do basename \"$(dirname \"$f\")\"; done" % sq,
            timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                name = line.strip()
                if name:
                    pinned.add(name)

    return pinned


def _delete_snapshot(ctx: BackupContext, snapshot: str) -> bool:
    """Delete a single snapshot directory. Returns True on success."""
    snap_dir = get_snapshot_dir(ctx.target.name, ctx.remote, ctx.hostname)
    snap_path = "%s/%s" % (snap_dir, snapshot)

    if ctx.is_local_remote:
        try:
            r = subprocess.run(["rm", "-rf", snap_path], capture_output=True, timeout=120)
            if r.returncode == 0:
                return True
            # Fallback to sudo
            r = subprocess.run(["sudo", "rm", "-rf", snap_path], capture_output=True, timeout=120)
            return r.returncode == 0
        except Exception:
            return False

    elif ctx.is_ssh_remote:
        ssh = SSHOpts.for_remote(ctx.remote)
        from lib.core.utils import shquote
        sq = shquote(snap_path)
        r = ssh.run("rm -rf %s 2>/dev/null || sudo rm -rf %s 2>/dev/null" % (sq, sq), timeout=120)
        return r.returncode == 0

    elif ctx.is_rclone_remote:
        from lib.core.rclone import rclone_purge
        return rclone_purge(ctx, "targets/%s/snapshots/%s" % (ctx.target.name, snapshot)) == 0

    return False
