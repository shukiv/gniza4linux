"""Source-side pull operations — fetch files from SSH, S3, GDrive, or rclone sources.

Ports lib/source.sh to Python.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.core.context import BackupContext

logger = logging.getLogger(__name__)


def pull_folder_from_source(
    ctx: "BackupContext",
    folder_path: str,
    local_dest: str,
    link_dest: str = "",
    *,
    transfer_log: str = "",
) -> int:
    """Pull a folder from the configured source to a local directory.

    Dispatches based on target.source_type: ssh, s3, gdrive, rclone.
    Returns 0 on success, 1 on failure.
    """
    os.makedirs(local_dest, exist_ok=True)

    source_type = ctx.target.source_type or "local"

    if source_type == "ssh":
        return _pull_ssh(ctx, folder_path, local_dest, link_dest,
                         transfer_log=transfer_log)
    elif source_type in ("s3", "gdrive", "rclone"):
        return _pull_rclone_source(ctx, folder_path, local_dest)
    else:
        logger.error("Unknown source type: %s", source_type)
        return 1


def _pull_ssh(
    ctx: "BackupContext",
    source_path: str,
    local_dest: str,
    link_dest: str = "",
    *,
    transfer_log: str = "",
) -> int:
    """Pull from SSH source using rsync with retry."""
    from lib.ssh import SSHOpts
    from lib.core.transfer import RsyncOpts, build_filter_args, rsync_with_retry

    src_ssh = SSHOpts.for_target_source(ctx.target)
    max_retries = src_ssh._retries

    src_sudo = (ctx.target.source_sudo or "no").lower() == "yes"
    if src_sudo:
        rsync_path = "sudo rsync --fake-super"
    else:
        rsync_path = "rsync --fake-super"

    opts = RsyncOpts()
    opts.delete = False
    opts.rsync_path = rsync_path
    opts.compress = "no"

    if link_dest:
        opts.link_dest = link_dest

    if transfer_log:
        opts.log_file = transfer_log

    opts.include_filters = build_filter_args(ctx.target)

    rsync_ssh = src_ssh.rsync_ssh_string()

    if not source_path.endswith("/"):
        source_path = source_path + "/"
    if not local_dest.endswith("/"):
        local_dest = local_dest + "/"

    source_spec = "%s@%s:%s" % (src_ssh.user, src_ssh.host, source_path)

    args = ["rsync"] + opts.as_args() + ["-e", rsync_ssh, source_spec, local_dest]

    run_env = src_ssh.env()
    if src_ssh._is_password:
        args = ["sshpass", "-e"] + args

    logger.info("CMD: %s", " ".join(args))

    log_header = "rsync (source pull): %s -> %s" % (source_spec, local_dest)

    return rsync_with_retry(
        args, max_retries, "rsync (source pull)", ctx,
        log_header=log_header,
        env=run_env,
        transfer_log=transfer_log,
    )


def _pull_rclone_source(
    ctx: "BackupContext",
    remote_path: str,
    local_dest: str,
) -> int:
    """Pull from S3/GDrive/rclone source using rclone copy."""
    from lib.core.rclone import RcloneSourceConfig

    source_type = ctx.target.source_type

    try:
        with RcloneSourceConfig(ctx) as conf_path:
            rclone_src = _build_rclone_source_spec(ctx, remote_path)

            logger.debug("rclone (source pull): %s -> %s", rclone_src, local_dest)

            cmd = ["rclone", "copy", "--config", conf_path, rclone_src, local_dest]

            rc = subprocess.run(
                cmd, capture_output=True, stdin=subprocess.DEVNULL,
            ).returncode

            if rc != 0:
                logger.error("rclone (source pull) failed (exit %d)", rc)
                return 1
            return 0

    except Exception as e:
        logger.error("rclone source pull failed: %s", e)
        return 1


def _build_rclone_source_spec(ctx: "BackupContext", remote_path: str) -> str:
    """Build the rclone source specification string."""
    source_type = ctx.target.source_type

    if source_type == "s3" and ctx.target.source_s3_bucket:
        return "gniza-source:%s/%s" % (
            ctx.target.source_s3_bucket, remote_path.lstrip("/"))
    elif source_type == "rclone":
        return "gniza-source:%s" % remote_path.lstrip("/")
    else:
        return "gniza-source:%s" % remote_path
