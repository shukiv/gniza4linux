"""Tests for lib.core.rclone — rclone transport layer."""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call, ANY

import pytest

from lib.core.rclone import (
    is_rclone_mode,
    RcloneConfig,
    RcloneSourceConfig,
    _build_rclone_config,
    _build_source_rclone_config,
    _extract_rclone_section,
    _rclone_remote_path,
    rclone_cmd,
    rclone_sync_incremental,
    rclone_from_remote,
    rclone_list_dirs,
    rclone_list_files,
    rclone_cat,
    rclone_rcat,
    rclone_purge,
    _rclone_exists,
    rclone_size,
    rclone_disk_usage_pct,
    rclone_list_remote_snapshots,
    rclone_finalize_snapshot,
    rclone_clean_partial_snapshots,
)
from lib.models import Target, Remote, AppSettings
from lib.core.context import BackupContext


def _make_ctx(
    remote_type="s3",
    base="/backups",
    target_name="web",
    hostname="myhost",
    timestamp="2026-03-24T120000",
    s3_bucket="my-bucket",
    s3_provider="AWS",
    s3_access_key_id="AKID",
    s3_secret_access_key="SKEY",
    s3_region="us-east-1",
    s3_endpoint="",
    gdrive_sa_file="",
    gdrive_root_folder_id="",
    rclone_config_path="",
    rclone_remote_name="",
    bwlimit="0",
    ssh_retries="3",
):
    """Helper to build a BackupContext for rclone tests."""
    target = Target(name=target_name, folders="/etc")
    remote = Remote(
        name="r",
        type=remote_type,
        base=base,
        s3_bucket=s3_bucket,
        s3_provider=s3_provider,
        s3_access_key_id=s3_access_key_id,
        s3_secret_access_key=s3_secret_access_key,
        s3_region=s3_region,
        s3_endpoint=s3_endpoint,
        gdrive_sa_file=gdrive_sa_file,
        gdrive_root_folder_id=gdrive_root_folder_id,
        rclone_config_path=rclone_config_path,
        rclone_remote_name=rclone_remote_name,
        bwlimit=bwlimit,
    )
    settings = AppSettings(ssh_retries=ssh_retries)
    return BackupContext(
        target=target, remote=remote, settings=settings,
        hostname=hostname, timestamp=timestamp,
        work_dir=Path("/tmp"), log_dir=Path("/tmp"),
    )


class TestIsRcloneMode:
    def test_s3(self):
        assert is_rclone_mode("s3") is True

    def test_gdrive(self):
        assert is_rclone_mode("gdrive") is True

    def test_rclone(self):
        assert is_rclone_mode("rclone") is True

    def test_ssh(self):
        assert is_rclone_mode("ssh") is False

    def test_local(self):
        assert is_rclone_mode("local") is False


class TestBuildRcloneConfig:
    def test_s3_config(self, tmp_path):
        remote = Remote(
            name="r", type="s3",
            s3_provider="AWS",
            s3_access_key_id="AKID",
            s3_secret_access_key="SKEY",
            s3_region="us-east-1",
        )
        path = _build_rclone_config(remote, tmp_path)
        try:
            content = open(path).read()
            assert "[remote]" in content
            assert "type = s3" in content
            assert "provider = AWS" in content
            assert "access_key_id = AKID" in content
            assert "secret_access_key = SKEY" in content
            assert "region = us-east-1" in content
            assert "endpoint" not in content
        finally:
            os.unlink(path)

    def test_s3_config_with_endpoint(self, tmp_path):
        remote = Remote(
            name="r", type="s3",
            s3_provider="Minio",
            s3_access_key_id="AK",
            s3_secret_access_key="SK",
            s3_region="eu-west-1",
            s3_endpoint="https://minio.example.com",
        )
        path = _build_rclone_config(remote, tmp_path)
        try:
            content = open(path).read()
            assert "endpoint = https://minio.example.com" in content
        finally:
            os.unlink(path)

    def test_gdrive_config(self, tmp_path):
        remote = Remote(
            name="r", type="gdrive",
            gdrive_sa_file="/path/to/sa.json",
        )
        path = _build_rclone_config(remote, tmp_path)
        try:
            content = open(path).read()
            assert "[remote]" in content
            assert "type = drive" in content
            assert "scope = drive" in content
            assert "service_account_file = /path/to/sa.json" in content
            assert "root_folder_id" not in content
        finally:
            os.unlink(path)

    def test_gdrive_config_with_root_folder(self, tmp_path):
        remote = Remote(
            name="r", type="gdrive",
            gdrive_sa_file="/path/to/sa.json",
            gdrive_root_folder_id="abc123",
        )
        path = _build_rclone_config(remote, tmp_path)
        try:
            content = open(path).read()
            assert "root_folder_id = abc123" in content
        finally:
            os.unlink(path)

    def test_generic_rclone_config(self, tmp_path):
        # Create a fake rclone.conf
        rclone_conf = tmp_path / "rclone.conf"
        rclone_conf.write_text("[myremote]\ntype = sftp\nhost = example.com\n")

        remote = Remote(
            name="r", type="rclone",
            rclone_config_path=str(rclone_conf),
            rclone_remote_name="myremote",
        )
        path = _build_rclone_config(remote, tmp_path)
        try:
            content = open(path).read()
            assert "[remote]" in content
            assert "type = sftp" in content
            assert "host = example.com" in content
            assert "[myremote]" not in content
        finally:
            os.unlink(path)

    def test_unknown_type_raises(self, tmp_path):
        remote = Remote(name="r", type="ftp")
        with pytest.raises(ValueError, match="Unknown REMOTE_TYPE"):
            _build_rclone_config(remote, tmp_path)

    def test_rclone_section_not_found(self, tmp_path):
        rclone_conf = tmp_path / "rclone.conf"
        rclone_conf.write_text("[other]\ntype = sftp\n")

        remote = Remote(
            name="r", type="rclone",
            rclone_config_path=str(rclone_conf),
            rclone_remote_name="missing",
        )
        with pytest.raises(ValueError, match="not found"):
            _build_rclone_config(remote, tmp_path)


class TestBuildSourceRcloneConfig:
    def test_s3_source(self, tmp_path):
        target = Target(
            name="web",
            source_type="s3",
            source_s3_provider="AWS",
            source_s3_access_key_id="AK",
            source_s3_secret_access_key="SK",
            source_s3_region="us-east-1",
        )
        path = _build_source_rclone_config(target, tmp_path)
        try:
            content = open(path).read()
            assert "[gniza-source]" in content
            assert "type = s3" in content
            assert "access_key_id = AK" in content
        finally:
            os.unlink(path)

    def test_gdrive_source(self, tmp_path):
        target = Target(
            name="web",
            source_type="gdrive",
            source_gdrive_sa_file="/sa.json",
        )
        path = _build_source_rclone_config(target, tmp_path)
        try:
            content = open(path).read()
            assert "[gniza-source]" in content
            assert "type = drive" in content
        finally:
            os.unlink(path)

    def test_generic_rclone_source(self, tmp_path):
        rclone_conf = tmp_path / "rclone.conf"
        rclone_conf.write_text("[myremote]\ntype = sftp\nhost = example.com\n")

        target = Target(
            name="web",
            source_type="rclone",
            source_rclone_config_path=str(rclone_conf),
            source_rclone_remote_name="myremote",
        )
        path = _build_source_rclone_config(target, tmp_path)
        try:
            content = open(path).read()
            assert "[gniza-source]" in content
            assert "type = sftp" in content
        finally:
            os.unlink(path)


class TestExtractRcloneSection:
    def test_extracts_and_renames(self, tmp_path):
        src = tmp_path / "src.conf"
        src.write_text(
            "[other]\ntype = ftp\n\n[target]\ntype = sftp\nhost = example.com\n\n[another]\ntype = s3\n"
        )
        out = tmp_path / "out.conf"
        _extract_rclone_section(str(src), "target", str(out), section_name="remote")
        content = out.read_text()
        assert "[remote]" in content
        assert "type = sftp" in content
        assert "host = example.com" in content
        assert "[target]" not in content
        assert "[other]" not in content
        assert "[another]" not in content

    def test_section_not_found_raises(self, tmp_path):
        src = tmp_path / "src.conf"
        src.write_text("[other]\ntype = ftp\n")
        out = tmp_path / "out.conf"
        with pytest.raises(ValueError, match="not found"):
            _extract_rclone_section(str(src), "missing", str(out))

    def test_config_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            _extract_rclone_section("/nonexistent/path.conf", "remote", "/tmp/out.conf")


class TestRcloneRemotePath:
    def test_s3_path(self):
        ctx = _make_ctx(remote_type="s3", s3_bucket="my-bucket", base="/backups")
        result = _rclone_remote_path(ctx, "targets/web/snapshots")
        assert result == "remote:my-bucket/backups/myhost/targets/web/snapshots"

    def test_s3_no_subpath(self):
        ctx = _make_ctx(remote_type="s3", s3_bucket="my-bucket", base="/backups")
        result = _rclone_remote_path(ctx)
        assert result == "remote:my-bucket/backups/myhost"

    def test_gdrive_path(self):
        ctx = _make_ctx(remote_type="gdrive", base="/backups")
        result = _rclone_remote_path(ctx, "targets/web/snapshots")
        assert result == "remote:/backups/myhost/targets/web/snapshots"

    def test_rclone_path(self):
        ctx = _make_ctx(remote_type="rclone", base="/data")
        result = _rclone_remote_path(ctx, "some/path")
        assert result == "remote:/data/myhost/some/path"

    def test_trailing_slash_stripped(self):
        ctx = _make_ctx(remote_type="gdrive", base="/backups/")
        result = _rclone_remote_path(ctx, "sub")
        assert result == "remote:/backups/myhost/sub"


class TestRcloneCmd:
    def test_basic_command(self):
        ctx = _make_ctx(remote_type="s3")
        mock_result = MagicMock(returncode=0, stdout="ok\n", stderr="")

        with patch("lib.core.rclone.RcloneConfig") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.__enter__ = MagicMock(return_value="/tmp/fake.conf")
            mock_cfg.__exit__ = MagicMock(return_value=False)
            mock_cfg_cls.return_value = mock_cfg

            with patch("subprocess.run", return_value=mock_result) as mock_run:
                result = rclone_cmd(ctx, "lsf", "remote:bucket/path")

        assert result.returncode == 0
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "rclone"
        assert cmd[1] == "lsf"
        assert "--config" in cmd

    def test_bwlimit_applied(self):
        ctx = _make_ctx(remote_type="s3", bwlimit="500")
        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        with patch("lib.core.rclone.RcloneConfig") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.__enter__ = MagicMock(return_value="/tmp/fake.conf")
            mock_cfg.__exit__ = MagicMock(return_value=False)
            mock_cfg_cls.return_value = mock_cfg

            with patch("subprocess.run", return_value=mock_result) as mock_run:
                rclone_cmd(ctx, "sync", "src", "dst")

        cmd = mock_run.call_args[0][0]
        bw_args = [a for a in cmd if a.startswith("--bwlimit=")]
        assert len(bw_args) == 1
        assert bw_args[0] == "--bwlimit=500k"


class TestRcloneListDirs:
    def test_returns_dirs(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=0, stdout="dir1/\ndir2/\ndir3/\n", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_list_dirs(ctx, "targets/web/snapshots")

        assert result == ["dir1", "dir2", "dir3"]

    def test_empty_result(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=1, stdout="", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_list_dirs(ctx, "targets/web/snapshots")

        assert result == []


class TestRcloneListFiles:
    def test_returns_files(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=0, stdout="file1.txt\nfile2.txt\n", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_list_files(ctx, "some/path")

        assert result == ["file1.txt", "file2.txt"]

    def test_empty_result(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=0, stdout="   \n", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_list_files(ctx, "some/path")

        assert result == []


class TestRcloneCat:
    def test_reads_content(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=0, stdout="2026-03-24T120000", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_cat(ctx, "targets/web/snapshots/latest.txt")

        assert result == "2026-03-24T120000"

    def test_failure_returns_empty(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=1, stdout="", stderr="not found")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_cat(ctx, "targets/web/snapshots/latest.txt")

        assert result == ""


class TestRcloneRcat:
    def test_writes_content(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result) as mock_cmd:
            result = rclone_rcat(ctx, "targets/web/snapshots/latest.txt", "2026-03-24T120000")

        assert result == 0
        mock_cmd.assert_called_once()
        assert mock_cmd.call_args[1]["input_data"] == b"2026-03-24T120000"

    def test_failure(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_rcat(ctx, "some/path", "content")

        assert result == 1


class TestRclonePurge:
    def test_success(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_purge(ctx, "targets/web/snapshots/old")

        assert result == 0

    def test_failure(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_purge(ctx, "targets/web/snapshots/old")

        assert result == 1


class TestRcloneExists:
    def test_exists(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=0)

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            assert _rclone_exists(ctx, "some/path/.complete") is True

    def test_not_exists(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=1)

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            assert _rclone_exists(ctx, "some/path/.complete") is False


class TestRcloneSize:
    def test_returns_bytes(self):
        ctx = _make_ctx()
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps({"bytes": 12345678, "count": 42}),
            stderr="",
        )

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_size(ctx, "targets/web")

        assert result == 12345678

    def test_failure_returns_zero(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_size(ctx, "targets/web")

        assert result == 0

    def test_invalid_json_returns_zero(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=0, stdout="not json", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_size(ctx, "targets/web")

        assert result == 0


class TestRcloneDiskUsagePct:
    def test_s3_returns_zero(self):
        ctx = _make_ctx(remote_type="s3")
        assert rclone_disk_usage_pct(ctx) == 0

    def test_gdrive_computes_percentage(self):
        ctx = _make_ctx(remote_type="gdrive")
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps({"total": 1000, "used": 750}),
            stderr="",
        )

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_disk_usage_pct(ctx)

        assert result == 75

    def test_gdrive_failure_returns_zero(self):
        ctx = _make_ctx(remote_type="gdrive")
        mock_result = MagicMock(returncode=1, stdout="", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_disk_usage_pct(ctx)

        assert result == 0

    def test_gdrive_zero_total(self):
        ctx = _make_ctx(remote_type="gdrive")
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps({"total": 0, "used": 0}),
            stderr="",
        )

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            result = rclone_disk_usage_pct(ctx)

        assert result == 0


class TestRcloneSyncIncremental:
    def test_success_first_attempt(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result) as mock_cmd:
            result = rclone_sync_incremental(
                ctx, "/local/data", "web", "etc", "2026-03-24T120000")

        assert result == 0
        mock_cmd.assert_called_once()
        call_args = mock_cmd.call_args
        assert call_args[0][1] == "sync"
        assert "--backup-dir" in call_args[0]

    def test_retry_then_success(self):
        ctx = _make_ctx(ssh_retries="3")
        fail_result = MagicMock(returncode=1, stdout="", stderr="error")
        ok_result = MagicMock(returncode=0, stdout="", stderr="")

        with patch("lib.core.rclone.rclone_cmd", side_effect=[fail_result, ok_result]):
            with patch("time.sleep"):
                result = rclone_sync_incremental(
                    ctx, "/local/data", "web", "etc", "2026-03-24T120000")

        assert result == 0

    def test_all_retries_fail(self):
        ctx = _make_ctx(ssh_retries="2")
        fail_result = MagicMock(returncode=1, stdout="", stderr="error")

        with patch("lib.core.rclone.rclone_cmd", return_value=fail_result):
            with patch("time.sleep"):
                result = rclone_sync_incremental(
                    ctx, "/local/data", "web", "etc", "2026-03-24T120000")

        assert result == 1

    def test_trailing_slash_appended(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result) as mock_cmd:
            rclone_sync_incremental(ctx, "/local/data", "web", "etc", "2026-03-24T120000")

        call_args = mock_cmd.call_args[0]
        assert call_args[2] == "/local/data/"


class TestRcloneFromRemote:
    def test_success(self):
        ctx = _make_ctx()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        with patch("lib.core.rclone.rclone_cmd", return_value=mock_result):
            with patch("os.makedirs"):
                result = rclone_from_remote(ctx, "targets/web/snapshots/2026-03-24T120000",
                                            "/local/restore")

        assert result == 0

    def test_failure_after_retries(self):
        ctx = _make_ctx(ssh_retries="2")
        fail_result = MagicMock(returncode=1, stdout="", stderr="error")

        with patch("lib.core.rclone.rclone_cmd", return_value=fail_result):
            with patch("os.makedirs"):
                with patch("time.sleep"):
                    result = rclone_from_remote(ctx, "some/path", "/local/restore")

        assert result == 1


class TestRcloneListRemoteSnapshots:
    def test_lists_completed_snapshots(self):
        ctx = _make_ctx()

        with patch("lib.core.rclone.rclone_list_dirs",
                    return_value=["2026-03-24T120000", "2026-03-23T120000", "2026-03-22T120000"]):
            with patch("lib.core.rclone._rclone_exists",
                       side_effect=[True, False, True]):
                result = rclone_list_remote_snapshots(ctx, "web")

        assert result == ["2026-03-24T120000", "2026-03-22T120000"]

    def test_empty_dirs(self):
        ctx = _make_ctx()

        with patch("lib.core.rclone.rclone_list_dirs", return_value=[]):
            result = rclone_list_remote_snapshots(ctx, "web")

        assert result == []

    def test_none_complete(self):
        ctx = _make_ctx()

        with patch("lib.core.rclone.rclone_list_dirs", return_value=["snap1"]):
            with patch("lib.core.rclone._rclone_exists", return_value=False):
                result = rclone_list_remote_snapshots(ctx, "web")

        assert result == []

    def test_sorted_newest_first(self):
        ctx = _make_ctx()

        with patch("lib.core.rclone.rclone_list_dirs",
                    return_value=["2026-03-20T120000", "2026-03-24T120000", "2026-03-22T120000"]):
            with patch("lib.core.rclone._rclone_exists", return_value=True):
                result = rclone_list_remote_snapshots(ctx, "web")

        assert result == ["2026-03-24T120000", "2026-03-22T120000", "2026-03-20T120000"]


class TestRcloneFinalizeSnapshot:
    def test_success(self):
        ctx = _make_ctx()

        with patch("lib.core.rclone.rclone_rcat", return_value=0) as mock_rcat:
            result = rclone_finalize_snapshot(ctx, "web", "2026-03-24T120000")

        assert result is True
        assert mock_rcat.call_count == 2
        # First call: .complete marker
        first_call = mock_rcat.call_args_list[0]
        assert ".complete" in first_call[0][1]
        # Second call: latest.txt
        second_call = mock_rcat.call_args_list[1]
        assert "latest.txt" in second_call[0][1]
        assert second_call[0][2] == "2026-03-24T120000"

    def test_complete_marker_failure(self):
        ctx = _make_ctx()

        with patch("lib.core.rclone.rclone_rcat", return_value=1):
            result = rclone_finalize_snapshot(ctx, "web", "2026-03-24T120000")

        assert result is False

    def test_latest_txt_failure_still_succeeds(self):
        ctx = _make_ctx()

        with patch("lib.core.rclone.rclone_rcat", side_effect=[0, 1]):
            result = rclone_finalize_snapshot(ctx, "web", "2026-03-24T120000")

        assert result is True


class TestRcloneCleanPartialSnapshots:
    def test_purges_incomplete(self):
        ctx = _make_ctx()

        with patch("lib.core.rclone.rclone_list_dirs",
                    return_value=["2026-03-24T120000", "2026-03-23T120000"]):
            with patch("lib.core.rclone._rclone_exists",
                       side_effect=[True, False]):
                with patch("lib.core.rclone.rclone_purge", return_value=0) as mock_purge:
                    rclone_clean_partial_snapshots(ctx, "web")

        mock_purge.assert_called_once()
        assert "2026-03-23T120000" in mock_purge.call_args[0][1]

    def test_nothing_to_clean(self):
        ctx = _make_ctx()

        with patch("lib.core.rclone.rclone_list_dirs", return_value=[]):
            with patch("lib.core.rclone.rclone_purge") as mock_purge:
                rclone_clean_partial_snapshots(ctx, "web")

        mock_purge.assert_not_called()

    def test_all_complete(self):
        ctx = _make_ctx()

        with patch("lib.core.rclone.rclone_list_dirs",
                    return_value=["2026-03-24T120000"]):
            with patch("lib.core.rclone._rclone_exists", return_value=True):
                with patch("lib.core.rclone.rclone_purge") as mock_purge:
                    rclone_clean_partial_snapshots(ctx, "web")

        mock_purge.assert_not_called()


class TestRcloneConfigContextManager:
    def test_creates_and_cleans(self, tmp_path):
        ctx = _make_ctx(remote_type="s3")
        # Override work_dir to use tmp_path
        ctx = BackupContext(
            target=ctx.target, remote=ctx.remote, settings=ctx.settings,
            hostname=ctx.hostname, timestamp=ctx.timestamp,
            work_dir=tmp_path, log_dir=Path("/tmp"),
        )
        with RcloneConfig(ctx) as conf_path:
            assert os.path.isfile(conf_path)
            content = open(conf_path).read()
            assert "[remote]" in content

        # File should be cleaned up
        assert not os.path.isfile(conf_path)
