"""Tests for lib.core.source — source-side pull operations."""
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY

import pytest

from lib.core.source import (
    pull_folder_from_source,
    _pull_ssh,
    _pull_rclone_source,
    _build_rclone_source_spec,
)
from lib.models import Target, Remote, AppSettings
from lib.core.context import BackupContext
from lib.ssh import SSHOpts


def _make_ctx(
    source_type="ssh",
    source_host="10.0.0.2",
    source_user="root",
    source_port="22",
    source_auth_method="key",
    source_key="/root/.ssh/id_rsa",
    source_password="",
    source_sudo="yes",
    remote_type="local",
    base="/backups",
    target_name="web",
    hostname="myhost",
    timestamp="2026-03-24T120000",
    source_s3_bucket="",
    source_s3_provider="AWS",
    source_s3_access_key_id="",
    source_s3_secret_access_key="",
    source_s3_region="us-east-1",
    source_s3_endpoint="",
    source_gdrive_sa_file="",
    source_gdrive_root_folder_id="",
    source_rclone_config_path="",
    source_rclone_remote_name="",
):
    """Helper to build a BackupContext for source tests."""
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
        source_s3_bucket=source_s3_bucket,
        source_s3_provider=source_s3_provider,
        source_s3_access_key_id=source_s3_access_key_id,
        source_s3_secret_access_key=source_s3_secret_access_key,
        source_s3_region=source_s3_region,
        source_s3_endpoint=source_s3_endpoint,
        source_gdrive_sa_file=source_gdrive_sa_file,
        source_gdrive_root_folder_id=source_gdrive_root_folder_id,
        source_rclone_config_path=source_rclone_config_path,
        source_rclone_remote_name=source_rclone_remote_name,
    )
    remote = Remote(name="r", type=remote_type, base=base)
    settings = AppSettings()
    return BackupContext(
        target=target, remote=remote, settings=settings,
        hostname=hostname, timestamp=timestamp,
        work_dir=Path("/tmp"), log_dir=Path("/tmp"),
    )


class TestPullFolderFromSource:
    def test_ssh_dispatches(self):
        ctx = _make_ctx(source_type="ssh")
        with patch("lib.core.source._pull_ssh", return_value=0) as mock_ssh:
            with patch("os.makedirs"):
                result = pull_folder_from_source(ctx, "/etc", "/local/dest")
        assert result == 0
        mock_ssh.assert_called_once()

    def test_s3_dispatches(self):
        ctx = _make_ctx(source_type="s3")
        with patch("lib.core.source._pull_rclone_source", return_value=0) as mock_rc:
            with patch("os.makedirs"):
                result = pull_folder_from_source(ctx, "/data", "/local/dest")
        assert result == 0
        mock_rc.assert_called_once()

    def test_gdrive_dispatches(self):
        ctx = _make_ctx(source_type="gdrive")
        with patch("lib.core.source._pull_rclone_source", return_value=0) as mock_rc:
            with patch("os.makedirs"):
                result = pull_folder_from_source(ctx, "/data", "/local/dest")
        assert result == 0

    def test_rclone_dispatches(self):
        ctx = _make_ctx(source_type="rclone")
        with patch("lib.core.source._pull_rclone_source", return_value=0) as mock_rc:
            with patch("os.makedirs"):
                result = pull_folder_from_source(ctx, "/data", "/local/dest")
        assert result == 0

    def test_unknown_source_type(self):
        ctx = _make_ctx(source_type="ftp")
        with patch("os.makedirs"):
            result = pull_folder_from_source(ctx, "/data", "/local/dest")
        assert result == 1

    def test_local_source_type(self):
        ctx = _make_ctx(source_type="local")
        with patch("os.makedirs"):
            result = pull_folder_from_source(ctx, "/etc", "/local/dest")
        assert result == 1


class TestPullSSH:
    def test_builds_rsync_with_ssh(self):
        ctx = _make_ctx(source_type="ssh")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            result = _pull_ssh(ctx, "/etc", "/local/staging")
        assert result == 0
        mock_retry.assert_called_once()
        call_args = mock_retry.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "rsync"
        assert "-e" in cmd
        assert "root@10.0.0.2:/etc/" in cmd

    def test_appends_trailing_slash(self):
        ctx = _make_ctx(source_type="ssh")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            _pull_ssh(ctx, "/etc", "/local/staging")
        cmd = mock_retry.call_args[0][0]
        source_spec = [a for a in cmd if "@" in a and ":" in a][0]
        assert source_spec.endswith("/")
        dest = cmd[-1]
        assert dest.endswith("/")

    def test_sudo_rsync_path(self):
        ctx = _make_ctx(source_type="ssh", source_sudo="yes")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            _pull_ssh(ctx, "/etc", "/local/staging")
        cmd = mock_retry.call_args[0][0]
        rsync_path_args = [a for a in cmd if a.startswith("--rsync-path=")]
        assert len(rsync_path_args) == 1
        assert "sudo" in rsync_path_args[0]

    def test_no_sudo_rsync_path(self):
        ctx = _make_ctx(source_type="ssh", source_sudo="no")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            _pull_ssh(ctx, "/etc", "/local/staging")
        cmd = mock_retry.call_args[0][0]
        rsync_path_args = [a for a in cmd if a.startswith("--rsync-path=")]
        assert len(rsync_path_args) == 1
        assert "sudo" not in rsync_path_args[0]
        assert "rsync --fake-super" in rsync_path_args[0]

    def test_password_auth_uses_sshpass(self):
        ctx = _make_ctx(source_type="ssh", source_auth_method="password",
                        source_password="secret123", source_key="")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            _pull_ssh(ctx, "/etc", "/local/staging")
        cmd = mock_retry.call_args[0][0]
        assert cmd[0] == "sshpass"
        assert cmd[1] == "-e"
        env = mock_retry.call_args[1].get("env") or {}
        assert env.get("SSHPASS") == "secret123"

    def test_link_dest_passed(self):
        ctx = _make_ctx(source_type="ssh")
        with patch("lib.core.transfer.rsync_with_retry", return_value=0) as mock_retry:
            _pull_ssh(ctx, "/etc", "/local/staging", link_dest="/prev/snap")
        cmd = mock_retry.call_args[0][0]
        link_args = [a for a in cmd if a.startswith("--link-dest=")]
        assert len(link_args) == 1
        assert link_args[0] == "--link-dest=/prev/snap"

    def test_retry_failure_returns_1(self):
        ctx = _make_ctx(source_type="ssh")
        with patch("lib.core.transfer.rsync_with_retry", return_value=1) as mock_retry:
            result = _pull_ssh(ctx, "/etc", "/local/staging")
        assert result == 1


class TestBuildRcloneSourceSpec:
    def test_s3_with_bucket(self):
        ctx = _make_ctx(source_type="s3", source_s3_bucket="mybucket")
        result = _build_rclone_source_spec(ctx, "/data/files")
        assert result == "gniza-source:mybucket/data/files"

    def test_s3_no_bucket(self):
        ctx = _make_ctx(source_type="s3", source_s3_bucket="")
        result = _build_rclone_source_spec(ctx, "/data/files")
        assert result == "gniza-source:/data/files"

    def test_gdrive(self):
        ctx = _make_ctx(source_type="gdrive")
        result = _build_rclone_source_spec(ctx, "folder/sub")
        assert result == "gniza-source:folder/sub"

    def test_rclone_generic(self):
        ctx = _make_ctx(source_type="rclone")
        result = _build_rclone_source_spec(ctx, "/mydata")
        assert result == "gniza-source:mydata"


class TestPullRcloneSource:
    def test_success(self):
        ctx = _make_ctx(source_type="s3", source_s3_bucket="mybucket",
                        source_s3_access_key_id="AK", source_s3_secret_access_key="SK")

        mock_result = MagicMock(returncode=0)

        with patch("lib.core.rclone.RcloneSourceConfig") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.__enter__ = MagicMock(return_value="/tmp/fake.conf")
            mock_cfg.__exit__ = MagicMock(return_value=False)
            mock_cfg_cls.return_value = mock_cfg

            with patch("lib.core.source.subprocess.run", return_value=mock_result) as mock_run:
                result = _pull_rclone_source(ctx, "/data", "/local/dest")

        assert result == 0
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "rclone"
        assert cmd[1] == "copy"
        assert "--config" in cmd

    def test_failure(self):
        ctx = _make_ctx(source_type="s3", source_s3_bucket="mybucket",
                        source_s3_access_key_id="AK", source_s3_secret_access_key="SK")

        mock_result = MagicMock(returncode=1)

        with patch("lib.core.rclone.RcloneSourceConfig") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.__enter__ = MagicMock(return_value="/tmp/fake.conf")
            mock_cfg.__exit__ = MagicMock(return_value=False)
            mock_cfg_cls.return_value = mock_cfg

            with patch("lib.core.source.subprocess.run", return_value=mock_result):
                result = _pull_rclone_source(ctx, "/data", "/local/dest")

        assert result == 1

    def test_exception_returns_1(self):
        ctx = _make_ctx(source_type="s3", source_s3_bucket="mybucket",
                        source_s3_access_key_id="AK", source_s3_secret_access_key="SK")

        with patch("lib.core.rclone.RcloneSourceConfig") as mock_cfg_cls:
            mock_cfg_cls.side_effect = RuntimeError("config error")
            result = _pull_rclone_source(ctx, "/data", "/local/dest")

        assert result == 1
