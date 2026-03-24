"""Tests for lib.core.transfer — rsync orchestration, retry logic, and transfer functions."""
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call, ANY

import pytest

from lib.core.transfer import (
    RsyncOpts,
    build_filter_args,
    rsync_with_retry,
    transfer_to_remote,
    transfer_local,
    transfer_ssh_to_local,
    transfer_ssh_to_ssh,
    _check_disk_space,
    _run_rsync,
)
from lib.models import Target, Remote, AppSettings
from lib.core.context import BackupContext
from lib.ssh import SSHOpts


def _make_ctx(
    remote_type="ssh",
    base="/backups",
    target_name="web",
    hostname="myhost",
    timestamp="2026-03-24T120000",
    remote_sudo="yes",
    source_type="local",
    source_host="10.0.0.2",
    source_user="root",
    source_port="22",
    source_auth_method="key",
    source_key="/root/.ssh/id_rsa",
    source_password="",
    source_sudo="yes",
    rsync_compress="no",
    rsync_checksum="no",
    rsync_extra_opts="",
    bwlimit="0",
    target_include="",
    target_exclude="",
    remote_host="10.0.0.1",
    remote_user="gniza",
    remote_port="22",
    remote_auth_method="key",
    remote_key="/home/gniza/.ssh/id_rsa",
    remote_password="",
    ssh_retries="3",
    ssh_timeout="30",
    disk_usage_threshold="95",
    prev_snapshot=None,
):
    """Helper to build a BackupContext for tests."""
    target = Target(
        name=target_name,
        folders="/etc",
        source_type=source_type,
        source_host=source_host,
        source_user=source_user,
        source_port=source_port,
        source_auth_method=source_auth_method,
        source_key=source_key,
        source_password=source_password,
        source_sudo=source_sudo,
        include=target_include,
        exclude=target_exclude,
    )
    remote = Remote(
        name="r",
        type=remote_type,
        host=remote_host,
        port=remote_port,
        user=remote_user,
        auth_method=remote_auth_method,
        key=remote_key,
        password=remote_password,
        sudo=remote_sudo,
        base=base,
        bwlimit=bwlimit,
    )
    settings = AppSettings(
        rsync_compress=rsync_compress,
        rsync_checksum=rsync_checksum,
        rsync_extra_opts=rsync_extra_opts,
        ssh_retries=ssh_retries,
        ssh_timeout=ssh_timeout,
        disk_usage_threshold=disk_usage_threshold,
        bwlimit=bwlimit,
    )
    return BackupContext(
        target=target,
        remote=remote,
        settings=settings,
        hostname=hostname,
        timestamp=timestamp,
        prev_snapshot=prev_snapshot,
        work_dir=Path("/tmp"),
        log_dir=Path("/tmp"),
    )


# ── RsyncOpts ────────────────────────────────────────────────────

class TestRsyncOpts:
    def test_default_as_args(self):
        opts = RsyncOpts()
        args = opts.as_args()
        assert "-a" in args
        assert "-H" in args
        assert "-A" in args
        assert "-X" in args
        assert "--numeric-ids" in args
        assert "--delete" in args
        assert "--sparse" in args
        assert "--info=progress2" in args
        assert "--no-inc-recursive" in args

    def test_from_context_basic(self):
        ctx = _make_ctx()
        opts = RsyncOpts.from_context(ctx)
        assert opts.archive is True
        assert opts.bwlimit == 0
        assert opts.compress == "no"
        assert opts.checksum is False
        assert opts.extra_opts == []

    def test_from_context_with_bwlimit(self):
        ctx = _make_ctx(bwlimit="5000")
        opts = RsyncOpts.from_context(ctx)
        assert opts.bwlimit == 5000
        assert "--bwlimit=5000" in opts.as_args()

    def test_from_context_compress_zstd(self):
        ctx = _make_ctx(rsync_compress="zstd")
        opts = RsyncOpts.from_context(ctx)
        args = opts.as_args()
        assert "-z" in args
        assert "--compress-choice=zstd" in args

    def test_from_context_compress_yes(self):
        ctx = _make_ctx(rsync_compress="yes")
        opts = RsyncOpts.from_context(ctx)
        args = opts.as_args()
        assert "-z" in args
        assert "--compress-choice=zstd" not in args

    def test_from_context_checksum(self):
        ctx = _make_ctx(rsync_checksum="yes")
        opts = RsyncOpts.from_context(ctx)
        assert opts.checksum is True
        assert "--checksum" in opts.as_args()

    def test_from_context_extra_opts(self):
        ctx = _make_ctx(rsync_extra_opts="--timeout=300 --contimeout=60")
        opts = RsyncOpts.from_context(ctx)
        assert "--timeout=300" in opts.extra_opts
        assert "--contimeout=60" in opts.extra_opts

    def test_link_dest_in_args(self):
        opts = RsyncOpts(link_dest="/backups/prev")
        args = opts.as_args()
        assert "--link-dest=/backups/prev" in args

    def test_fake_super_in_args(self):
        opts = RsyncOpts(fake_super=True)
        args = opts.as_args()
        assert "--fake-super" in args

    def test_rsync_path_in_args(self):
        opts = RsyncOpts(rsync_path="sudo rsync --fake-super")
        args = opts.as_args()
        assert "--rsync-path=sudo rsync --fake-super" in args

    def test_mkpath_in_args(self):
        opts = RsyncOpts(mkpath=True)
        args = opts.as_args()
        assert "--mkpath" in args

    def test_log_file_adds_stats(self):
        opts = RsyncOpts(log_file="/tmp/transfer.log")
        args = opts.as_args()
        assert "--log-file=/tmp/transfer.log" in args
        assert "--stats" in args

    def test_inc_recursive_true_omits_no_flag(self):
        opts = RsyncOpts(inc_recursive=True)
        args = opts.as_args()
        assert "--no-inc-recursive" not in args
        assert "--info=progress2" in args

    def test_no_bwlimit_when_zero(self):
        opts = RsyncOpts(bwlimit=0)
        args = opts.as_args()
        for a in args:
            assert not a.startswith("--bwlimit")

    def test_include_filters_appended(self):
        opts = RsyncOpts(include_filters=["--include=*.log", "--exclude=*"])
        args = opts.as_args()
        assert "--include=*.log" in args
        assert "--exclude=*" in args


# ── build_filter_args ────────────────────────────────────────────

class TestBuildFilterArgs:
    def test_no_filters(self):
        target = Target(name="t")
        assert build_filter_args(target) == []

    def test_include_patterns(self):
        target = Target(name="t", include="*.log, *.txt")
        result = build_filter_args(target)
        assert result[0] == "--include=*/"
        assert "--include=*.log" in result
        assert "--include=*.txt" in result
        assert "--exclude=*" in result
        assert "--prune-empty-dirs" in result

    def test_include_directory_pattern(self):
        target = Target(name="t", include="logs/")
        result = build_filter_args(target)
        assert "--include=logs/" in result
        assert "--include=logs/**" in result
        assert "--exclude=*" in result

    def test_exclude_patterns(self):
        target = Target(name="t", exclude="*.tmp, .cache")
        result = build_filter_args(target)
        assert "--exclude=*.tmp" in result
        assert "--exclude=.cache" in result
        assert "--include=*/" not in result
        assert "--prune-empty-dirs" not in result

    def test_include_takes_precedence_over_exclude(self):
        target = Target(name="t", include="*.log", exclude="*.tmp")
        result = build_filter_args(target)
        # When include is set, exclude is ignored
        assert "--include=*.log" in result
        assert "--exclude=*.tmp" not in result
        assert "--exclude=*" in result

    def test_empty_patterns_skipped(self):
        target = Target(name="t", include="*.log, , *.txt, ")
        result = build_filter_args(target)
        # Empty entries between commas should be skipped — only */, *.log, *.txt
        include_entries = [r for r in result if r.startswith("--include=")]
        assert include_entries == ["--include=*/", "--include=*.log", "--include=*.txt"]

    def test_whitespace_only_include(self):
        target = Target(name="t", include="   ")
        assert build_filter_args(target) == []


# ── rsync_with_retry ─────────────────────────────────────────────

class TestRsyncWithRetry:
    def test_success_on_first_attempt(self):
        ctx = _make_ctx()
        with patch("lib.core.transfer._run_rsync", return_value=0) as mock_run:
            rc = rsync_with_retry(
                ["rsync", "-a", "/src/", "/dst/"],
                3, "rsync", ctx,
            )
        assert rc == 0
        assert mock_run.call_count == 1

    def test_exit_23_partial_retry_success(self):
        ctx = _make_ctx()
        with patch("lib.core.transfer._run_rsync", side_effect=[23, 0]) as mock_run:
            with patch("time.sleep"):
                rc = rsync_with_retry(
                    ["rsync", "-a", "/src/", "/dst/"],
                    3, "rsync", ctx,
                )
        assert rc == 0
        assert mock_run.call_count == 2

    def test_exit_23_partial_retry_still_partial(self):
        """Exit 23 retry that also fails should still return 0 (accept as success)."""
        ctx = _make_ctx()
        with patch("lib.core.transfer._run_rsync", side_effect=[23, 5]) as mock_run:
            with patch("time.sleep"):
                rc = rsync_with_retry(
                    ["rsync", "-a", "/src/", "/dst/"],
                    3, "rsync", ctx,
                )
        assert rc == 0
        assert mock_run.call_count == 2

    def test_exit_24_vanished_files(self):
        ctx = _make_ctx()
        with patch("lib.core.transfer._run_rsync", return_value=24) as mock_run:
            rc = rsync_with_retry(
                ["rsync", "-a", "/src/", "/dst/"],
                3, "rsync", ctx,
            )
        assert rc == 0
        assert mock_run.call_count == 1

    def test_retry_with_backoff(self):
        ctx = _make_ctx()
        # Fail twice, succeed on third
        with patch("lib.core.transfer._run_rsync", side_effect=[1, 1, 0]) as mock_run:
            with patch("time.sleep") as mock_sleep:
                rc = rsync_with_retry(
                    ["rsync", "-a", "/src/", "/dst/"],
                    3, "rsync", ctx,
                )
        assert rc == 0
        assert mock_run.call_count == 3
        # Backoff: attempt1 * 10 = 10, attempt2 * 10 = 20
        mock_sleep.assert_any_call(10)
        mock_sleep.assert_any_call(20)

    def test_max_retries_exceeded(self):
        ctx = _make_ctx()
        with patch("lib.core.transfer._run_rsync", return_value=1) as mock_run:
            with patch("time.sleep"):
                rc = rsync_with_retry(
                    ["rsync", "-a", "/src/", "/dst/"],
                    3, "rsync", ctx,
                )
        assert rc == 1
        assert mock_run.call_count == 3

    def test_disk_space_check_aborts(self):
        ctx = _make_ctx()
        with patch("lib.core.transfer._run_rsync", return_value=1):
            with patch("lib.core.transfer._check_disk_space", return_value=False):
                with patch("time.sleep"):
                    rc = rsync_with_retry(
                        ["rsync", "-a", "/src/", "/dst/"],
                        3, "rsync", ctx,
                        check_disk_space=True,
                    )
        assert rc == 1

    def test_log_header_written_to_transfer_log(self, tmp_path):
        log_file = str(tmp_path / "transfer.log")
        ctx = _make_ctx()
        with patch("lib.core.transfer._run_rsync", return_value=0):
            rsync_with_retry(
                ["rsync", "-a", "/src/", "/dst/"],
                3, "rsync", ctx,
                log_header="test header",
                transfer_log=log_file,
            )
        content = open(log_file).read()
        assert "=== test header ===" in content

    def test_exit_23_log_header_retry(self, tmp_path):
        log_file = str(tmp_path / "transfer.log")
        ctx = _make_ctx()
        with patch("lib.core.transfer._run_rsync", side_effect=[23, 0]):
            with patch("time.sleep"):
                rsync_with_retry(
                    ["rsync", "-a", "/src/", "/dst/"],
                    3, "rsync", ctx,
                    log_header="test header",
                    transfer_log=log_file,
                )
        content = open(log_file).read()
        assert "=== test header ===" in content
        assert "=== test header (retry) ===" in content

    def test_env_passed_through(self):
        ctx = _make_ctx()
        test_env = {"SSHPASS": "secret"}
        with patch("lib.core.transfer._run_rsync", return_value=0) as mock_run:
            rsync_with_retry(
                ["rsync", "-a"],
                1, "rsync", ctx,
                env=test_env,
            )
        mock_run.assert_called_once_with(
            ["rsync", "-a"], env=test_env, transfer_log="",
        )


# ── _run_rsync ───────────────────────────────────────────────────

class TestRunRsync:
    def test_basic_run(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            rc = _run_rsync(["rsync", "-a", "/src/", "/dst/"])
        assert rc == 0
        mock_run.assert_called_once()

    def test_with_transfer_log(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.stdout = [b"transferring file.txt\n", b"done\n"]
            proc.returncode = 0
            proc.wait.return_value = 0
            mock_popen.return_value = proc
            rc = _run_rsync(
                ["rsync", "-a", "/src/", "/dst/"],
                transfer_log=log_file,
            )
        assert rc == 0
        content = open(log_file).read()
        assert "transferring file.txt" in content

    def test_command_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            rc = _run_rsync(["rsync", "-a"])
        assert rc == 1

    def test_uses_devnull_stdin(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _run_rsync(["rsync", "-a"])
        _, kwargs = mock_run.call_args
        assert kwargs.get("stdin") == subprocess.DEVNULL

    def test_env_forwarded(self):
        test_env = {"SSHPASS": "secret"}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _run_rsync(["rsync", "-a"], env=test_env)
        _, kwargs = mock_run.call_args
        assert kwargs["env"] == test_env


# ── transfer_to_remote ───────────────────────────────────────────

class TestTransferToRemote:
    def test_basic_command_structure(self):
        ctx = _make_ctx()
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            rc = transfer_to_remote(
                ctx, "/data/web", "data/web", "2026-03-24T120000",
                link_dest="/backups/myhost/targets/web/snapshots/prev/data/web",
            )
        assert rc == 0
        mock_retry.assert_called_once()
        cmd = mock_retry.call_args[0][0]

        # Verify rsync is the first command
        assert cmd[0] == "rsync"

        # Verify key flags
        cmd_str = " ".join(cmd)
        assert "--link-dest=/backups/myhost/targets/web/snapshots/prev/data/web" in cmd_str
        assert "--rsync-path=sudo rsync --fake-super" in cmd_str
        assert "--mkpath" in cmd_str
        assert "-a" in cmd
        assert "--info=progress2" in cmd

    def test_source_ends_with_slash(self):
        ctx = _make_ctx()
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_to_remote(ctx, "/data/web", "data/web", "2026-03-24T120000")
        cmd = mock_retry.call_args[0][0]
        # Source should end with /
        sources = [a for a in cmd if a.startswith("/data/web")]
        assert any(s.endswith("/") for s in sources)

    def test_remote_dest_format(self):
        ctx = _make_ctx(remote_user="gniza", remote_host="10.0.0.1")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_to_remote(ctx, "/data/web", "data/web", "2026-03-24T120000")
        cmd = mock_retry.call_args[0][0]
        dest = cmd[-1]
        assert dest.startswith("gniza@10.0.0.1:")
        assert "2026-03-24T120000.partial" in dest

    def test_restricted_shell_no_fake_super(self):
        ctx = _make_ctx()
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_to_remote(
                ctx, "/data/web", "data/web", "2026-03-24T120000",
                restricted_shell=True,
            )
        cmd = mock_retry.call_args[0][0]
        cmd_str = " ".join(cmd)
        assert "--rsync-path" not in cmd_str
        assert "--fake-super" not in cmd_str

    def test_no_sudo_uses_plain_fake_super(self):
        ctx = _make_ctx(remote_sudo="no")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_to_remote(ctx, "/data/web", "data/web", "2026-03-24T120000")
        cmd = mock_retry.call_args[0][0]
        cmd_str = " ".join(cmd)
        assert "--rsync-path=rsync --fake-super" in cmd_str

    def test_password_mode_prepends_sshpass(self):
        ctx = _make_ctx(remote_auth_method="password", remote_password="s3cret", remote_key="")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_to_remote(ctx, "/data/web", "data/web", "2026-03-24T120000")
        cmd = mock_retry.call_args[0][0]
        assert cmd[0] == "sshpass"
        assert cmd[1] == "-e"
        assert cmd[2] == "rsync"
        # Environment should have SSHPASS
        env = mock_retry.call_args[1]["env"]
        assert env is not None
        assert env.get("SSHPASS") == "s3cret"

    def test_bwlimit_in_command(self):
        ctx = _make_ctx(bwlimit="5000")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_to_remote(ctx, "/data/web", "data/web", "2026-03-24T120000")
        cmd = mock_retry.call_args[0][0]
        assert "--bwlimit=5000" in cmd

    def test_rsync_e_flag_present(self):
        ctx = _make_ctx()
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_to_remote(ctx, "/data/web", "data/web", "2026-03-24T120000")
        cmd = mock_retry.call_args[0][0]
        assert "-e" in cmd
        e_idx = cmd.index("-e")
        ssh_string = cmd[e_idx + 1]
        assert "ssh" in ssh_string


# ── transfer_local ───────────────────────────────────────────────

class TestTransferLocal:
    def test_basic_command(self):
        ctx = _make_ctx(remote_type="local")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                rc = transfer_local(
                    ctx, "/data/web", "data/web", "2026-03-24T120000",
                    link_dest="/backups/prev/data/web",
                )
        assert rc == 0
        cmd = mock_retry.call_args[0][0]
        assert cmd[0] == "rsync"
        assert "--link-dest=/backups/prev/data/web" in cmd

    def test_no_ssh_flags(self):
        ctx = _make_ctx(remote_type="local")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                transfer_local(ctx, "/data/web", "data/web", "2026-03-24T120000")
        cmd = mock_retry.call_args[0][0]
        assert "-e" not in cmd
        assert "sshpass" not in cmd

    def test_creates_destination_dir(self):
        ctx = _make_ctx(remote_type="local")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0):
            with patch("os.makedirs") as mock_makedirs:
                transfer_local(ctx, "/data/web", "data/web", "2026-03-24T120000")
        mock_makedirs.assert_called_once()
        dest_path = mock_makedirs.call_args[0][0]
        assert "2026-03-24T120000.partial" in dest_path

    def test_source_trailing_slash(self):
        ctx = _make_ctx(remote_type="local")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                transfer_local(ctx, "/data/web", "data/web", "2026-03-24T120000")
        cmd = mock_retry.call_args[0][0]
        source = cmd[-2]
        assert source.endswith("/")

    def test_no_compress_for_local(self):
        ctx = _make_ctx(remote_type="local", rsync_compress="zstd")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                transfer_local(ctx, "/data/web", "data/web", "2026-03-24T120000")
        cmd = mock_retry.call_args[0][0]
        assert "-z" not in cmd
        assert "--compress-choice=zstd" not in cmd

    def test_label_is_rsync_local(self):
        ctx = _make_ctx(remote_type="local")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                transfer_local(ctx, "/data/web", "data/web", "2026-03-24T120000")
        label = mock_retry.call_args[0][2]
        assert label == "rsync (local)"


# ── transfer_ssh_to_local ────────────────────────────────────────

class TestTransferSshToLocal:
    def test_basic_command(self):
        ctx = _make_ctx(source_type="ssh", source_host="10.0.0.2")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                rc = transfer_ssh_to_local(
                    ctx, "/remote/data", "remote/data", "2026-03-24T120000",
                    link_dest="/backups/prev/remote/data",
                )
        assert rc == 0
        cmd = mock_retry.call_args[0][0]
        assert cmd[0] == "rsync"
        assert "--link-dest=/backups/prev/remote/data" in cmd

    def test_source_spec_format(self):
        ctx = _make_ctx(
            source_type="ssh", source_host="10.0.0.2",
            source_user="root", source_port="22",
        )
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                transfer_ssh_to_local(
                    ctx, "/remote/data", "remote/data", "2026-03-24T120000",
                )
        cmd = mock_retry.call_args[0][0]
        # Find the source spec (user@host:path)
        source_args = [a for a in cmd if "@" in a and ":" in a]
        assert len(source_args) == 1
        assert source_args[0].startswith("root@10.0.0.2:")
        assert source_args[0].endswith("/")

    def test_rsync_path_with_sudo(self):
        ctx = _make_ctx(source_type="ssh", source_sudo="yes")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                transfer_ssh_to_local(
                    ctx, "/remote/data", "remote/data", "2026-03-24T120000",
                )
        cmd = mock_retry.call_args[0][0]
        assert "--rsync-path=sudo rsync --fake-super" in cmd

    def test_rsync_path_without_sudo(self):
        ctx = _make_ctx(source_type="ssh", source_sudo="no")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                transfer_ssh_to_local(
                    ctx, "/remote/data", "remote/data", "2026-03-24T120000",
                )
        cmd = mock_retry.call_args[0][0]
        assert "--rsync-path=rsync --fake-super" in cmd

    def test_password_source_sshpass(self):
        ctx = _make_ctx(
            source_type="ssh",
            source_auth_method="password",
            source_password="srcpass",
            source_key="",
        )
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                transfer_ssh_to_local(
                    ctx, "/remote/data", "remote/data", "2026-03-24T120000",
                )
        cmd = mock_retry.call_args[0][0]
        assert cmd[0] == "sshpass"
        assert cmd[1] == "-e"
        env = mock_retry.call_args[1]["env"]
        assert env is not None
        assert env.get("SSHPASS") == "srcpass"

    def test_creates_destination_dir(self):
        ctx = _make_ctx(source_type="ssh")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0):
            with patch("os.makedirs") as mock_makedirs:
                transfer_ssh_to_local(
                    ctx, "/remote/data", "remote/data", "2026-03-24T120000",
                )
        mock_makedirs.assert_called_once()

    def test_ssh_e_flag(self):
        ctx = _make_ctx(source_type="ssh", source_port="2222")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                transfer_ssh_to_local(
                    ctx, "/remote/data", "remote/data", "2026-03-24T120000",
                )
        cmd = mock_retry.call_args[0][0]
        assert "-e" in cmd
        e_idx = cmd.index("-e")
        ssh_str = cmd[e_idx + 1]
        assert "-p" in ssh_str
        assert "2222" in ssh_str


# ── transfer_ssh_to_ssh ──────────────────────────────────────────

class TestTransferSshToSsh:
    def test_basic_command_structure(self):
        ctx = _make_ctx(
            source_type="ssh", source_host="10.0.0.2",
            remote_host="10.0.0.1", remote_sudo="yes",
        )
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            rc = transfer_ssh_to_ssh(
                ctx, "/remote/data", "remote/data", "2026-03-24T120000",
                link_dest="/backups/prev/remote/data",
            )
        assert rc == 0
        cmd = mock_retry.call_args[0][0]
        # Should SSH into destination
        assert "ssh" in cmd
        assert "%s@%s" % ("gniza", "10.0.0.1") in cmd

    def test_destination_ssh_port(self):
        ctx = _make_ctx(
            source_type="ssh", source_host="10.0.0.2",
            remote_host="10.0.0.1", remote_port="2222",
        )
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_ssh_to_ssh(
                ctx, "/remote/data", "remote/data", "2026-03-24T120000",
            )
        cmd = mock_retry.call_args[0][0]
        p_idx = cmd.index("-p")
        assert cmd[p_idx + 1] == "2222"

    def test_agent_forwarding_for_key_auth(self):
        ctx = _make_ctx(source_type="ssh", source_auth_method="key")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_ssh_to_ssh(
                ctx, "/remote/data", "remote/data", "2026-03-24T120000",
            )
        cmd = mock_retry.call_args[0][0]
        assert "-A" in cmd

    def test_no_agent_forwarding_for_password(self):
        ctx = _make_ctx(
            source_type="ssh",
            source_auth_method="password",
            source_password="srcpass",
            source_key="",
        )
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_ssh_to_ssh(
                ctx, "/remote/data", "remote/data", "2026-03-24T120000",
            )
        cmd = mock_retry.call_args[0][0]
        assert "-A" not in cmd

    def test_restricted_shell_no_fake_super(self):
        ctx = _make_ctx(source_type="ssh")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_ssh_to_ssh(
                ctx, "/remote/data", "remote/data", "2026-03-24T120000",
                restricted_shell=True,
            )
        # The remote command is the last argument to ssh
        cmd = mock_retry.call_args[0][0]
        remote_cmd = cmd[-1]
        assert "--fake-super" not in remote_cmd

    def test_remote_cmd_has_sudo_rsync(self):
        ctx = _make_ctx(source_type="ssh", remote_sudo="yes")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_ssh_to_ssh(
                ctx, "/remote/data", "remote/data", "2026-03-24T120000",
            )
        cmd = mock_retry.call_args[0][0]
        remote_cmd = cmd[-1]
        assert remote_cmd.startswith("sudo rsync")

    def test_remote_cmd_no_sudo(self):
        ctx = _make_ctx(source_type="ssh", remote_sudo="no")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_ssh_to_ssh(
                ctx, "/remote/data", "remote/data", "2026-03-24T120000",
            )
        cmd = mock_retry.call_args[0][0]
        remote_cmd = cmd[-1]
        assert remote_cmd.startswith("rsync")
        assert not remote_cmd.startswith("sudo")

    def test_source_password_temp_file_pattern(self):
        ctx = _make_ctx(
            source_type="ssh",
            source_auth_method="password",
            source_password="srcpass",
            source_key="",
        )
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_ssh_to_ssh(
                ctx, "/remote/data", "remote/data", "2026-03-24T120000",
            )
        cmd = mock_retry.call_args[0][0]
        remote_cmd = cmd[-1]
        assert "_GNIZA_PW=$(mktemp" in remote_cmd
        assert "sshpass -f" in remote_cmd
        assert 'rm -f "$_GNIZA_PW"' in remote_cmd

    def test_destination_password_sshpass(self):
        ctx = _make_ctx(
            source_type="ssh",
            remote_auth_method="password",
            remote_password="dstpass",
            remote_key="",
        )
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_ssh_to_ssh(
                ctx, "/remote/data", "remote/data", "2026-03-24T120000",
            )
        cmd = mock_retry.call_args[0][0]
        assert cmd[0] == "sshpass"
        assert cmd[1] == "-e"
        env = mock_retry.call_args[1]["env"]
        assert env is not None
        assert env.get("SSHPASS") == "dstpass"

    def test_link_dest_in_remote_cmd(self):
        ctx = _make_ctx(source_type="ssh")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_ssh_to_ssh(
                ctx, "/remote/data", "remote/data", "2026-03-24T120000",
                link_dest="/backups/prev/remote/data",
            )
        cmd = mock_retry.call_args[0][0]
        remote_cmd = cmd[-1]
        assert "--link-dest=" in remote_cmd

    def test_source_trailing_slash_in_spec(self):
        ctx = _make_ctx(source_type="ssh", source_host="10.0.0.2", source_user="root")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_ssh_to_ssh(
                ctx, "/remote/data", "remote/data", "2026-03-24T120000",
            )
        cmd = mock_retry.call_args[0][0]
        remote_cmd = cmd[-1]
        assert "root@10.0.0.2:/remote/data/" in remote_cmd


# ── _check_disk_space ────────────────────────────────────────────

class TestCheckDiskSpace:
    def test_disabled_when_threshold_zero(self):
        ctx = _make_ctx(disk_usage_threshold="0")
        assert _check_disk_space(ctx) is True

    def test_local_ok(self):
        ctx = _make_ctx(remote_type="local", disk_usage_threshold="95")
        mock_result = MagicMock(returncode=0, stdout="Use%\n 50%\n")
        with patch("subprocess.run", return_value=mock_result):
            assert _check_disk_space(ctx) is True

    def test_local_exceeded(self):
        ctx = _make_ctx(remote_type="local", disk_usage_threshold="95")
        mock_result = MagicMock(returncode=0, stdout="Use%\n 96%\n")
        with patch("subprocess.run", return_value=mock_result):
            assert _check_disk_space(ctx) is False

    def test_ssh_ok(self):
        ctx = _make_ctx(remote_type="ssh", disk_usage_threshold="95")
        mock_result = MagicMock(returncode=0, stdout=" 50%\n")
        with patch.object(SSHOpts, "run", return_value=mock_result):
            assert _check_disk_space(ctx) is True

    def test_ssh_exceeded(self):
        ctx = _make_ctx(remote_type="ssh", disk_usage_threshold="95")
        mock_result = MagicMock(returncode=0, stdout=" 96%\n")
        with patch.object(SSHOpts, "run", return_value=mock_result):
            assert _check_disk_space(ctx) is False


# ── Command safety (no shell injection) ──────────────────────────

class TestCommandSafety:
    def test_paths_with_spaces_in_transfer_to_remote(self):
        ctx = _make_ctx()
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_to_remote(
                ctx, "/data/my folder", "data/my folder", "2026-03-24T120000",
            )
        cmd = mock_retry.call_args[0][0]
        # Command should be a list (no shell=True needed)
        assert isinstance(cmd, list)
        # Source path should be a single list element (not split on space)
        assert "/data/my folder/" in cmd

    def test_paths_with_special_chars_local(self):
        ctx = _make_ctx(remote_type="local")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            with patch("os.makedirs"):
                transfer_local(
                    ctx, "/data/$pecial", "data/$pecial", "2026-03-24T120000",
                )
        cmd = mock_retry.call_args[0][0]
        assert isinstance(cmd, list)
        assert "/data/$pecial/" in cmd

    def test_ssh_to_ssh_remote_cmd_uses_shlex_quote(self):
        ctx = _make_ctx(
            source_type="ssh",
            source_host="10.0.0.2",
            source_user="root",
        )
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            transfer_ssh_to_ssh(
                ctx, "/path with spaces", "path with spaces", "2026-03-24T120000",
            )
        cmd = mock_retry.call_args[0][0]
        remote_cmd = cmd[-1]
        # The source spec and dest should be shell-quoted in the remote cmd
        # shlex.quote wraps the whole user@host:path in quotes
        assert "'root@10.0.0.2:/path with spaces/'" in remote_cmd
        # Dest path is the full snapshot .partial path, also quoted
        assert "path with spaces/" in remote_cmd
        # The dest should be wrapped in quotes (contains spaces)
        assert "'/backups/" in remote_cmd
