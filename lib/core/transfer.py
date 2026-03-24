"""Transfer layer — rsync orchestration with retry logic, filters, and SSH piping.

Ports lib/transfer.sh to Python.  All rsync invocations use subprocess with
list arguments (no shell=True) to avoid injection.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lib.core.context import BackupContext
    from lib.models import Target

logger = logging.getLogger(__name__)


# ── RsyncOpts ────────────────────────────────────────────────────

@dataclass
class RsyncOpts:
    """Rsync command flags derived from BackupContext."""

    archive: bool = True
    hard_links: bool = True
    acls: bool = True
    xattrs: bool = True
    numeric_ids: bool = True
    delete: bool = True
    sparse: bool = True
    fake_super: bool = False
    rsync_path: str = ""
    mkpath: bool = False
    bwlimit: int = 0
    compress: str = ""           # "no", "yes", "zlib", "zstd"
    checksum: bool = False
    inc_recursive: bool = False  # when True, omit --no-inc-recursive
    link_dest: str = ""
    log_file: str = ""
    include_filters: list[str] = field(default_factory=list)
    extra_opts: list[str] = field(default_factory=list)

    @classmethod
    def from_context(cls, ctx: BackupContext) -> RsyncOpts:
        """Build from BackupContext."""
        compress = ctx.settings.rsync_compress or "no"
        checksum = (ctx.settings.rsync_checksum or "no").lower() == "yes"
        extra = ctx.settings.rsync_extra_opts or ""

        return cls(
            bwlimit=ctx.bwlimit,
            compress=compress,
            checksum=checksum,
            extra_opts=extra.split() if extra.strip() else [],
        )

    def as_args(self) -> list[str]:
        """Return rsync flag list."""
        args: list[str] = []
        if self.archive:
            args.append("-a")
        if self.hard_links:
            args.append("-H")
        if self.acls:
            args.append("-A")
        if self.xattrs:
            args.append("-X")
        if self.numeric_ids:
            args.append("--numeric-ids")
        if self.delete:
            args.append("--delete")
        if self.sparse:
            args.append("--sparse")
        if self.mkpath:
            args.append("--mkpath")
        if self.fake_super:
            args.append("--fake-super")
        if self.rsync_path:
            args.append("--rsync-path=%s" % self.rsync_path)
        if self.link_dest:
            args.append("--link-dest=%s" % self.link_dest)
        if self.bwlimit > 0:
            args.append("--bwlimit=%d" % self.bwlimit)

        compress = self.compress.lower() if self.compress else "no"
        if compress in ("yes", "zlib"):
            args.append("-z")
        elif compress == "zstd":
            args.extend(["-z", "--compress-choice=zstd"])

        if self.checksum:
            args.append("--checksum")

        args.extend(self.extra_opts)
        args.extend(self.include_filters)

        if self.log_file:
            args.extend(["--log-file=%s" % self.log_file, "--stats"])

        args.append("--info=progress2")
        if not self.inc_recursive:
            args.append("--no-inc-recursive")

        return args


# ── Filter building ──────────────────────────────────────────────

def build_filter_args(target: Target) -> list[str]:
    """Build --include/--exclude filter list from target config.

    Follows the Bash _build_filter_opts logic:
    - If TARGET_INCLUDE is set: --include='*/' then each pattern, then --exclude='*'
      plus --prune-empty-dirs.  Directory patterns (ending with /) also get a /** variant.
    - Elif TARGET_EXCLUDE is set: --exclude for each pattern.
    """
    filters: list[str] = []
    include_str = target.include or ""
    exclude_str = target.exclude or ""

    if include_str.strip():
        filters.append("--include=*/")
        for pat in include_str.split(","):
            pat = pat.strip()
            if not pat:
                continue
            filters.append("--include=%s" % pat)
            if pat.endswith("/"):
                filters.append("--include=%s**" % pat)
        filters.append("--exclude=*")
        filters.append("--prune-empty-dirs")
    elif exclude_str.strip():
        for pat in exclude_str.split(","):
            pat = pat.strip()
            if pat:
                filters.append("--exclude=%s" % pat)

    return filters


# ── Disk space check ─────────────────────────────────────────────

def _check_disk_space(ctx: BackupContext) -> bool:
    """Check remote disk space; return True if OK, False if threshold exceeded."""
    try:
        threshold = int(ctx.settings.disk_usage_threshold or "95")
    except (ValueError, TypeError):
        threshold = 95

    if threshold <= 0:
        return True

    from lib.ssh import SSHOpts
    from lib.core.utils import shquote

    if ctx.is_local_remote:
        snap_dir = ctx.snap_dir
        try:
            r = subprocess.run(
                ["df", "--output=pcent", snap_dir],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                for line in r.stdout.strip().splitlines()[1:]:
                    pct = int(line.strip().rstrip("%"))
                    if pct >= threshold:
                        logger.error(
                            "Disk space threshold exceeded during transfer — aborting backup"
                        )
                        return False
        except Exception:
            pass
        return True

    elif ctx.is_ssh_remote:
        ssh = SSHOpts.for_remote(ctx.remote)
        base = ctx.remote.base.rstrip("/")
        cmd = "df --output=pcent %s 2>/dev/null | tail -1" % shquote(base)
        try:
            r = ssh.run(cmd, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                pct = int(r.stdout.strip().rstrip("%"))
                if pct >= threshold:
                    logger.error(
                        "Disk space threshold exceeded during transfer — aborting backup"
                    )
                    return False
        except Exception:
            pass
        return True

    return True


# ── Retry wrapper ────────────────────────────────────────────────

def rsync_with_retry(
    cmd: list[str],
    max_retries: int,
    label: str,
    ctx: BackupContext,
    *,
    log_header: str = "",
    check_disk_space: bool = False,
    env: Optional[dict] = None,
    transfer_log: str = "",
) -> int:
    """Shared retry wrapper for rsync commands.

    Exit code semantics (matching Bash _rsync_with_retry):
      - 0: success
      - 23 (partial transfer): one extra retry, then accept as success
      - 24 (vanished source files): accept as success
      - Other: retry with backoff up to max_retries

    Returns 0 on success (including 23/24 warnings), 1 on failure.
    """
    attempt = 0

    while attempt < max_retries:
        attempt += 1
        logger.debug("%s attempt %d/%d", label, attempt, max_retries)

        if log_header and transfer_log:
            try:
                with open(transfer_log, "a") as f:
                    f.write("=== %s ===\n" % log_header)
            except OSError:
                pass

        rc = _run_rsync(cmd, env=env, transfer_log=transfer_log)

        if rc == 0:
            logger.debug("%s succeeded on attempt %d", label, attempt)
            return 0

        # Exit 23: partial transfer — one extra retry then accept
        if rc == 23:
            logger.warning(
                "%s partial transfer (exit 23): retrying to pick up failed files...",
                label,
            )
            time.sleep(2)

            if log_header and transfer_log:
                try:
                    with open(transfer_log, "a") as f:
                        f.write("=== %s (retry) ===\n" % log_header)
                except OSError:
                    pass

            rc2 = _run_rsync(cmd, env=env, transfer_log=transfer_log)
            if rc2 == 0:
                logger.info("%s retry succeeded — all files transferred", label)
                return 0
            logger.warning(
                "%s retry completed (exit %d): some files could not be transferred",
                label, rc2,
            )
            return 0

        # Exit 24: vanished source files — accept
        if rc == 24:
            logger.warning(
                "%s completed with warnings (exit %d): vanished source files",
                label, rc,
            )
            return 0

        logger.warning(
            "%s failed (exit %d), attempt %d/%d", label, rc, attempt, max_retries,
        )

        if check_disk_space:
            if not _check_disk_space(ctx):
                return 1

        if attempt < max_retries:
            backoff = attempt * 10
            logger.info("Retrying in %ds...", backoff)
            time.sleep(backoff)

    logger.error("%s failed after %d attempts", label, max_retries)
    return 1


def _run_rsync(
    cmd: list[str],
    *,
    env: Optional[dict] = None,
    transfer_log: str = "",
) -> int:
    """Run an rsync command, optionally teeing output to a transfer log.

    Returns the process exit code.
    """
    try:
        if transfer_log:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                stdin=subprocess.DEVNULL,
            )
            with open(transfer_log, "a") as log_f:
                for line in proc.stdout:
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")
                    log_f.write(line)
            proc.wait()
            return proc.returncode
        else:
            r = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                env=env,
            )
            return r.returncode
    except FileNotFoundError:
        logger.error("rsync not found — is it installed?")
        return 1
    except Exception as e:
        logger.error("rsync execution error: %s", e)
        return 1


# ── Transfer functions ───────────────────────────────────────────

def transfer_to_remote(
    ctx: BackupContext,
    source_dir: str,
    rel_path: str,
    timestamp: str,
    link_dest: str = "",
    *,
    restricted_shell: bool = False,
    transfer_log: str = "",
) -> int:
    """Push local folder to SSH remote via rsync.

    Mirrors Bash rsync_to_remote().
    Returns 0 on success, 1 on failure.
    """
    from lib.ssh import SSHOpts

    ssh = SSHOpts.for_remote(ctx.remote)
    max_retries = ssh._retries

    opts = RsyncOpts.from_context(ctx)
    opts.mkpath = True

    # --fake-super / --rsync-path
    if restricted_shell:
        logger.debug("Restricted shell — skipping --fake-super")
    elif (ctx.remote.sudo or "no").lower() == "yes":
        opts.rsync_path = "sudo rsync --fake-super"
    else:
        opts.rsync_path = "rsync --fake-super"

    if link_dest:
        opts.link_dest = link_dest

    if transfer_log:
        opts.log_file = transfer_log

    # Build filter args
    opts.include_filters = build_filter_args(ctx.target)

    rsync_ssh = ssh.rsync_ssh_string()

    # Ensure source ends with /
    if not source_dir.endswith("/"):
        source_dir = source_dir + "/"

    snap_dir = ctx.snap_dir
    dest = "%s/%s.partial/%s/" % (snap_dir, timestamp, rel_path)
    remote_dest = "%s@%s:%s" % (ssh.user, ssh.host, dest)

    args = ["rsync"] + opts.as_args() + ["-e", rsync_ssh, source_dir, remote_dest]

    logger.info("CMD: %s", " ".join(args))

    # Password mode: prepend sshpass
    run_env = ssh.env()
    if ssh._is_password:
        args = ["sshpass", "-e"] + args

    log_header = "rsync: %s -> %s@%s:%s" % (source_dir, ssh.user, ssh.host, dest)

    return rsync_with_retry(
        args, max_retries, "rsync", ctx,
        log_header=log_header,
        check_disk_space=True,
        env=run_env,
        transfer_log=transfer_log,
    )


def transfer_local(
    ctx: BackupContext,
    source_dir: str,
    rel_path: str,
    timestamp: str,
    link_dest: str = "",
    *,
    transfer_log: str = "",
) -> int:
    """Local-to-local rsync with --link-dest.

    Mirrors Bash rsync_local().
    Returns 0 on success, 1 on failure.
    """
    from lib.ssh import SSHOpts

    # Use SSH retries default for max_retries (matches Bash)
    try:
        max_retries = int(ctx.settings.ssh_retries or "3")
    except (ValueError, TypeError):
        max_retries = 3

    opts = RsyncOpts.from_context(ctx)
    # Local mode does not use compress (no network)
    opts.compress = "no"

    if link_dest:
        opts.link_dest = link_dest

    if transfer_log:
        opts.log_file = transfer_log

    opts.include_filters = build_filter_args(ctx.target)

    # Ensure source ends with /
    if not source_dir.endswith("/"):
        source_dir = source_dir + "/"

    snap_dir = ctx.snap_dir
    dest = "%s/%s.partial/%s/" % (snap_dir, timestamp, rel_path)

    # Create destination directory
    os.makedirs(dest, exist_ok=True)

    args = ["rsync"] + opts.as_args() + [source_dir, dest]

    logger.info("CMD: %s", " ".join(args))

    log_header = "rsync (local): %s -> %s" % (source_dir, dest)

    return rsync_with_retry(
        args, max_retries, "rsync (local)", ctx,
        log_header=log_header,
        check_disk_space=True,
        transfer_log=transfer_log,
    )


def transfer_ssh_to_local(
    ctx: BackupContext,
    source_path: str,
    rel_path: str,
    timestamp: str,
    link_dest: str = "",
    *,
    transfer_log: str = "",
) -> int:
    """Pull from SSH source to local destination.

    Mirrors Bash transfer_folder_ssh_to_local().
    Returns 0 on success, 1 on failure.
    """
    from lib.ssh import SSHOpts

    src_ssh = SSHOpts.for_target_source(ctx.target)
    try:
        max_retries = int(ctx.settings.ssh_retries or "3")
    except (ValueError, TypeError):
        max_retries = 3

    snap_dir = ctx.snap_dir
    dest = "%s/%s.partial/%s/" % (snap_dir, timestamp, rel_path)

    os.makedirs(dest, exist_ok=True)

    # Build rsync-path for the source side
    src_sudo = (ctx.target.source_sudo or "no").lower() == "yes"
    if src_sudo:
        rsync_path = "sudo rsync --fake-super"
    else:
        rsync_path = "rsync --fake-super"

    opts = RsyncOpts.from_context(ctx)
    opts.rsync_path = rsync_path
    # No compress setting override for SSH-to-local (matches Bash: no -z added)
    opts.compress = "no"

    if link_dest:
        opts.link_dest = link_dest

    if transfer_log:
        opts.log_file = transfer_log

    opts.include_filters = build_filter_args(ctx.target)

    # Build SSH string for source
    rsync_ssh = src_ssh.rsync_ssh_string()

    # Ensure source ends with /
    if not source_path.endswith("/"):
        source_path = source_path + "/"

    source_spec = "%s@%s:%s" % (src_ssh.user, src_ssh.host, source_path)

    args = ["rsync"] + opts.as_args() + ["-e", rsync_ssh, source_spec, dest]

    # Password mode for source
    run_env = src_ssh.env()
    if src_ssh._is_password:
        args = ["sshpass", "-e"] + args

    logger.info(
        "Transferring %s for %s (ssh->local direct)...",
        source_path, ctx.target.name,
    )
    logger.info("CMD: %s", " ".join(args))

    log_header = "rsync (ssh->local): %s -> %s" % (source_spec, dest)

    return rsync_with_retry(
        args, max_retries, "rsync (ssh->local)", ctx,
        log_header=log_header,
        check_disk_space=True,
        env=run_env,
        transfer_log=transfer_log,
    )


def transfer_ssh_to_ssh(
    ctx: BackupContext,
    source_path: str,
    rel_path: str,
    timestamp: str,
    link_dest: str = "",
    *,
    restricted_shell: bool = False,
    transfer_log: str = "",
) -> int:
    """SSH-to-SSH pipelined transfer.

    SSHes into the destination and runs rsync there, pulling directly from
    the SSH source.  Data flows source -> destination without touching
    local disk.

    Mirrors Bash rsync_ssh_to_ssh().
    Returns 0 on success, 1 on failure.
    """
    from lib.ssh import SSHOpts

    dst_ssh = SSHOpts.for_remote(ctx.remote)
    src_ssh = SSHOpts.for_target_source(ctx.target)
    max_retries = dst_ssh._retries

    snap_dir = ctx.snap_dir
    dest = "%s/%s.partial/%s/" % (snap_dir, timestamp, rel_path)

    # --- Build the rsync command string to run ON the destination ---
    ropts: list[str] = ["-aHAX", "--numeric-ids", "--delete", "--sparse"]

    if restricted_shell:
        logger.debug("Restricted destination shell — skipping --fake-super for ssh->ssh")
    else:
        ropts.append("--fake-super")
        # --rsync-path controls what runs on the SOURCE side
        src_sudo = (ctx.target.source_sudo or "no").lower() == "yes"
        src_rsync_path = "sudo rsync --fake-super" if src_sudo else "rsync --fake-super"
        ropts.append("--rsync-path=%s" % src_rsync_path)

    if link_dest:
        ropts.append("--link-dest=%s" % link_dest)

    bwlimit = ctx.bwlimit
    if bwlimit > 0:
        ropts.append("--bwlimit=%d" % bwlimit)

    compress = (ctx.settings.rsync_compress or "no").lower()
    if compress in ("yes", "zlib"):
        ropts.append("-z")
    elif compress == "zstd":
        ropts.extend(["-z", "--compress-choice=zstd"])

    checksum = (ctx.settings.rsync_checksum or "no").lower() == "yes"
    if checksum:
        ropts.append("--checksum")

    extra = ctx.settings.rsync_extra_opts or ""
    if extra.strip():
        ropts.extend(extra.split())

    ropts.extend(build_filter_args(ctx.target))

    if transfer_log:
        ropts.extend(["--verbose", "--stats"])

    ropts.append("--info=progress2")
    ropts.append("--no-inc-recursive")

    # Build the SSH command the remote rsync will use to reach the source
    src_ssh_e = "ssh -p %s" % (src_ssh.port or "22")
    src_ssh_e += " -o StrictHostKeyChecking=accept-new"
    try:
        timeout = int(ctx.settings.ssh_timeout or "30")
    except (ValueError, TypeError):
        timeout = 30
    src_ssh_e += " -o ConnectTimeout=%d" % timeout
    if src_ssh.auth_method != "password":
        src_ssh_e += " -o BatchMode=yes"

    # Ensure source_path ends with /
    if not source_path.endswith("/"):
        source_path = source_path + "/"

    source_spec = "%s@%s:%s" % (src_ssh.user, src_ssh.host, source_path)

    # Assemble the remote command string with safe quoting
    dst_sudo = (ctx.remote.sudo or "no").lower() == "yes"
    remote_cmd = "sudo rsync" if dst_sudo else "rsync"
    for opt in ropts:
        remote_cmd += " %s" % shlex.quote(opt)
    remote_cmd += " -e %s" % shlex.quote(src_ssh_e)
    remote_cmd += " %s %s" % (shlex.quote(source_spec), shlex.quote(dest))

    # Source password auth: write password to temp file on destination
    src_is_password = (
        src_ssh.auth_method == "password" and bool(src_ssh.password)
    )
    if src_is_password:
        pw_escaped = shlex.quote(src_ssh.password)
        remote_cmd = (
            '_GNIZA_PW=$(mktemp /tmp/.gniza-pw-XXXXXX) && chmod 600 "$_GNIZA_PW"'
            " && printf '%%s' %s > \"$_GNIZA_PW\""
            " && sshpass -f \"$_GNIZA_PW\" %s"
            '; _rc=$?; rm -f "$_GNIZA_PW"; exit $_rc'
            % (pw_escaped, remote_cmd)
        )

    # --- Build the SSH command to the destination ---
    dst_cmd: list[str] = []
    dst_env = dst_ssh.env()
    if dst_ssh._is_password:
        dst_cmd.extend(["sshpass", "-e"])

    dst_cmd.append("ssh")

    # Enable agent forwarding when source uses key auth
    if src_ssh.auth_method == "key":
        dst_cmd.append("-A")

    if not dst_ssh._is_password:
        if dst_ssh.key:
            dst_cmd.extend(["-i", dst_ssh.key])
        dst_cmd.extend(["-o", "BatchMode=yes"])

    dst_cmd.extend(["-p", dst_ssh.port or "22"])
    dst_cmd.extend(["-o", "StrictHostKeyChecking=yes"])
    dst_cmd.extend(["-o", "ConnectTimeout=%d" % timeout])
    dst_cmd.extend(["-o", "ServerAliveInterval=60", "-o", "ServerAliveCountMax=3"])
    dst_cmd.append("%s@%s" % (dst_ssh.user, dst_ssh.host))
    dst_cmd.append(remote_cmd)

    logger.info(
        "CMD (ssh->ssh): rsync %s -e '...' %s %s (via %s@%s)",
        " ".join(ropts), source_spec, dest, dst_ssh.user, dst_ssh.host,
    )

    log_header = "rsync (ssh->ssh): %s -> %s@%s:%s" % (
        source_spec, dst_ssh.user, dst_ssh.host, dest,
    )

    rc = rsync_with_retry(
        dst_cmd, max_retries, "rsync (ssh->ssh)", ctx,
        log_header=log_header,
        check_disk_space=True,
        env=dst_env,
        transfer_log=transfer_log,
    )

    return rc
