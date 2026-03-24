"""Crontab dump and restore — port of lib/crontab.sh.

Dumps per-user crontabs, /etc/crontab, and /etc/cron.d/ files.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.core.context import BackupContext

from lib.core.db.common import (
    is_db_remote,
    run_db_command,
    ssh_run_raw,
    validate_username,
)

logger = logging.getLogger(__name__)

# Regex for valid cron.d filenames (same as username validation)
_VALID_CRON_FILE_RE = validate_username  # reuse the same pattern


def _run_crontab_cmd(
    ctx: BackupContext,
    cmd_args: list[str],
    use_sudo: bool = True,
) -> subprocess.CompletedProcess:
    """Run a crontab-related command locally or via SSH.

    For crontab, sudo is typically required to read other users' crontabs.
    """
    target = ctx.target
    sudo = use_sudo and (target.source_sudo or "yes") == "yes"

    return run_db_command(
        ctx, cmd_args,
        use_sudo=sudo,
    )


def dump_crontabs(ctx: BackupContext, dump_dir: str) -> bool:
    """Dump all user crontabs, /etc/crontab, and /etc/cron.d/ files.

    Creates a _crontab/ subdirectory under dump_dir.
    Returns True on success, False if any dump failed.
    """
    crontab_dir = Path(dump_dir) / "_crontab"
    crontab_dir.mkdir(parents=True, exist_ok=True)

    failed = False
    target = ctx.target

    # Dump per-user crontabs
    users_str = target.crontab_users or "root"
    users = [u.strip() for u in users_str.split(",") if u.strip()]

    for user in users:
        if not validate_username(user):
            logger.error("Invalid crontab username, skipping: %s", user)
            failed = True
            continue

        logger.info("Dumping crontab for user: %s", user)
        r = _run_crontab_cmd(ctx, ["crontab", "-l", "-u", user])

        if r.returncode == 0:
            outfile = crontab_dir / ("%s.crontab" % user)
            outfile.write_text(r.stdout or "")
            logger.debug("Dumped crontab for %s -> %s.crontab", user, user)
        elif r.returncode == 1:
            # Exit code 1 = no crontab for this user
            logger.debug("No crontab for user %s -- skipping", user)
        else:
            logger.error("Failed to dump crontab for user: %s", user)
            failed = True

    # Dump /etc/crontab
    logger.info("Dumping /etc/crontab")
    r = _run_crontab_cmd(ctx, ["cat", "/etc/crontab"])
    if r.returncode == 0:
        outfile = crontab_dir / "etc-crontab"
        outfile.write_text(r.stdout or "")
        logger.debug("Dumped /etc/crontab -> etc-crontab")
    else:
        logger.warning("Failed to read /etc/crontab -- skipping")

    # Dump /etc/cron.d/ contents
    logger.info("Dumping /etc/cron.d/ files")
    r = _run_crontab_cmd(ctx, ["ls", "-1", "/etc/cron.d/"])
    if r.returncode == 0 and r.stdout:
        for cron_file in r.stdout.splitlines():
            cron_file = cron_file.strip()
            if not cron_file:
                continue
            if not validate_username(cron_file):
                logger.debug("Skipping unusual cron.d filename: %s", cron_file)
                continue

            cr = _run_crontab_cmd(ctx, ["cat", "/etc/cron.d/%s" % cron_file])
            if cr.returncode == 0:
                outfile = crontab_dir / ("cron.d-%s" % cron_file)
                outfile.write_text(cr.stdout or "")
                logger.debug("Dumped /etc/cron.d/%s -> cron.d-%s", cron_file, cron_file)
            else:
                logger.debug("Failed to read /etc/cron.d/%s -- skipping", cron_file)

    if failed:
        logger.error("One or more crontab dumps failed")
        return False

    logger.info("Crontab dumps completed in %s", crontab_dir)
    return True


def restore_crontabs(ctx: BackupContext, dump_dir: str) -> bool:
    """Log that crontab files are available for manual restore.

    Auto-installing with 'crontab -u' would overwrite existing crontabs,
    so we only provide guidance.
    Returns True always.
    """
    crontab_dir = Path(dump_dir)
    logger.info("Crontab files restored to: %s", crontab_dir)
    logger.info("To manually restore a user crontab: crontab -u <user> <file>.crontab")
    logger.info("System files (etc-crontab, cron.d-*) can be manually copied to /etc/")
    return True
