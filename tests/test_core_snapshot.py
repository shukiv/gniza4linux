"""Tests for lib.core.snapshot — snapshot management functions."""
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from lib.core.snapshot import (
    get_snapshot_dir,
    list_snapshots,
    get_latest_snapshot,
    resolve_snapshot_timestamp,
    clean_partial_snapshots,
    finalize_snapshot,
    update_latest_symlink,
    count_partial_snapshots,
    is_snapshot_pinned,
)
from lib.models import Target, Remote, AppSettings
from lib.core.context import BackupContext
from lib.ssh import SSHOpts


def _make_ctx(remote_type="local", base="/backups", target_name="web",
              hostname="myhost", timestamp="2026-03-24T120000"):
    """Helper to build a BackupContext for tests."""
    target = Target(name=target_name, folders="/etc")
    remote = Remote(name="r", type=remote_type, host="10.0.0.1",
                    user="gniza", base=base)
    return BackupContext(
        target=target, remote=remote, settings=AppSettings(),
        hostname=hostname, timestamp=timestamp,
        work_dir=Path("/tmp"), log_dir=Path("/tmp"),
    )


class TestGetSnapshotDir:
    def test_basic(self):
        remote = Remote(name="r", type="ssh", base="/backups")
        result = get_snapshot_dir("web", remote, "myhost")
        assert result == "/backups/myhost/targets/web/snapshots"

    def test_trailing_slash_stripped(self):
        remote = Remote(name="r", type="ssh", base="/backups/")
        result = get_snapshot_dir("web", remote, "myhost")
        assert result == "/backups/myhost/targets/web/snapshots"


class TestListSnapshots:
    def test_local_lists_and_sorts(self):
        ctx = _make_ctx(remote_type="local")
        entries = [
            "2026-03-20T100000",
            "2026-03-22T100000",
            "2026-03-24T100000",
            "2026-03-21T100000.partial",
            "some-junk",
            ".hidden",
        ]
        with patch("os.listdir", return_value=entries):
            result = list_snapshots(ctx)
        assert result == [
            "2026-03-24T100000",
            "2026-03-22T100000",
            "2026-03-20T100000",
        ]

    def test_local_empty_dir(self):
        ctx = _make_ctx(remote_type="local")
        with patch("os.listdir", return_value=[]):
            result = list_snapshots(ctx)
        assert result == []

    def test_local_dir_not_found(self):
        ctx = _make_ctx(remote_type="local")
        with patch("os.listdir", side_effect=FileNotFoundError):
            result = list_snapshots(ctx)
        assert result == []

    def test_local_filters_partial(self):
        ctx = _make_ctx(remote_type="local")
        entries = [
            "2026-03-24T100000",
            "2026-03-23T100000.partial",
        ]
        with patch("os.listdir", return_value=entries):
            result = list_snapshots(ctx)
        assert result == ["2026-03-24T100000"]

    def test_ssh_parses_output(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "/backups/myhost/targets/web/snapshots/2026-03-24T100000\n"
            "/backups/myhost/targets/web/snapshots/2026-03-22T100000\n"
        )
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = list_snapshots(ctx)
        assert result == ["2026-03-24T100000", "2026-03-22T100000"]

    def test_ssh_empty(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = list_snapshots(ctx)
        assert result == []

    def test_ssh_no_stdout(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "   \n  \n"
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = list_snapshots(ctx)
        assert result == []

    def test_rclone_returns_empty(self):
        ctx = _make_ctx(remote_type="s3")
        with patch("lib.core.rclone.rclone_list_dirs", return_value=[]):
            result = list_snapshots(ctx)
        assert result == []

    def test_rclone_returns_completed_snapshots(self):
        ctx = _make_ctx(remote_type="s3")
        with patch("lib.core.rclone.rclone_list_dirs",
                    return_value=["2026-03-24T100000", "2026-03-22T100000"]):
            with patch("lib.core.rclone._rclone_exists", return_value=True):
                result = list_snapshots(ctx)
        assert result == ["2026-03-24T100000", "2026-03-22T100000"]


class TestGetLatestSnapshot:
    def test_returns_first(self):
        ctx = _make_ctx(remote_type="local")
        entries = ["2026-03-24T100000", "2026-03-22T100000"]
        with patch("os.listdir", return_value=entries):
            result = get_latest_snapshot(ctx)
        assert result == "2026-03-24T100000"

    def test_returns_none_when_empty(self):
        ctx = _make_ctx(remote_type="local")
        with patch("os.listdir", return_value=[]):
            result = get_latest_snapshot(ctx)
        assert result is None


class TestResolveSnapshotTimestamp:
    def test_latest_keyword(self):
        ctx = _make_ctx(remote_type="local")
        with patch("os.listdir", return_value=["2026-03-24T100000"]):
            result = resolve_snapshot_timestamp(ctx, "latest")
        assert result == "2026-03-24T100000"

    def test_latest_empty_string(self):
        ctx = _make_ctx(remote_type="local")
        with patch("os.listdir", return_value=["2026-03-24T100000"]):
            result = resolve_snapshot_timestamp(ctx, "")
        assert result == "2026-03-24T100000"

    def test_local_specific_exists(self):
        ctx = _make_ctx(remote_type="local")
        with patch("os.path.isdir", return_value=True):
            result = resolve_snapshot_timestamp(ctx, "2026-03-22T100000")
        assert result == "2026-03-22T100000"

    def test_local_specific_not_found(self):
        ctx = _make_ctx(remote_type="local")
        with patch("os.path.isdir", return_value=False):
            result = resolve_snapshot_timestamp(ctx, "2026-03-22T100000")
        assert result is None

    def test_ssh_specific_exists(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = resolve_snapshot_timestamp(ctx, "2026-03-22T100000")
        assert result == "2026-03-22T100000"

    def test_ssh_specific_not_found(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = resolve_snapshot_timestamp(ctx, "2026-03-22T100000")
        assert result is None


class TestCleanPartialSnapshots:
    def test_local_cleanup(self, tmp_path):
        ctx = _make_ctx(remote_type="local")
        with patch("glob.glob", return_value=["/backups/myhost/targets/web/snapshots/2026-03-24T100000.partial"]):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                clean_partial_snapshots(ctx)
                mock_run.assert_called_once_with(
                    ["rm", "-rf", "/backups/myhost/targets/web/snapshots/2026-03-24T100000.partial"],
                    capture_output=True, timeout=60,
                )

    def test_local_no_partials(self):
        ctx = _make_ctx(remote_type="local")
        with patch("glob.glob", return_value=[]):
            with patch("subprocess.run") as mock_run:
                clean_partial_snapshots(ctx)
                mock_run.assert_not_called()

    def test_local_sudo_fallback(self):
        ctx = _make_ctx(remote_type="local")
        with patch("glob.glob", return_value=["/snap/x.partial"]):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [Exception("permission denied"), MagicMock(returncode=0)]
                clean_partial_snapshots(ctx)
                assert mock_run.call_count == 2
                assert mock_run.call_args_list[1][0][0][0] == "sudo"

    def test_ssh_cleanup(self):
        ctx = _make_ctx(remote_type="ssh")
        list_result = MagicMock(returncode=0, stdout="/snap/x.partial\n")
        rm_result = MagicMock(returncode=0)
        with patch.object(SSHOpts, "run", side_effect=[list_result, rm_result]) as mock_run:
            clean_partial_snapshots(ctx)
            assert mock_run.call_count == 2

    def test_ssh_no_partials(self):
        ctx = _make_ctx(remote_type="ssh")
        list_result = MagicMock(returncode=1, stdout="")
        with patch.object(SSHOpts, "run", return_value=list_result) as mock_run:
            clean_partial_snapshots(ctx)
            assert mock_run.call_count == 1


class TestFinalizeSnapshot:
    def test_local_rename_and_symlink(self, tmp_path):
        snap_dir = tmp_path / "backups" / "myhost" / "targets" / "web" / "snapshots"
        snap_dir.mkdir(parents=True)
        partial = snap_dir / "2026-03-24T120000.partial"
        partial.mkdir()

        ctx = _make_ctx(
            remote_type="local",
            base=str(tmp_path / "backups"),
            hostname="myhost",
            timestamp="2026-03-24T120000",
        )

        result = finalize_snapshot(ctx)
        assert result is True
        assert (snap_dir / "2026-03-24T120000").is_dir()
        assert not partial.exists()
        latest = snap_dir.parent / "latest"
        assert latest.is_symlink()
        assert os.readlink(str(latest)) == "snapshots/2026-03-24T120000"

    def test_local_rename_failure(self):
        ctx = _make_ctx(remote_type="local", timestamp="2026-03-24T120000")
        with patch("os.rename", side_effect=OSError("no such file")):
            result = finalize_snapshot(ctx)
        assert result is False

    def test_ssh_success(self):
        ctx = _make_ctx(remote_type="ssh", timestamp="2026-03-24T120000")
        mv_result = MagicMock(returncode=0)
        ln_result = MagicMock(returncode=0)
        with patch.object(SSHOpts, "run", side_effect=[mv_result, ln_result]) as mock_run:
            result = finalize_snapshot(ctx)
        assert result is True
        assert mock_run.call_count == 2

    def test_ssh_mv_failure(self):
        ctx = _make_ctx(remote_type="ssh", timestamp="2026-03-24T120000")
        mv_result = MagicMock(returncode=1, stderr="mv: error")
        with patch.object(SSHOpts, "run", return_value=mv_result):
            result = finalize_snapshot(ctx)
        assert result is False

    def test_rclone_calls_finalize(self):
        ctx = _make_ctx(remote_type="s3", timestamp="2026-03-24T120000")
        with patch("lib.core.rclone.rclone_rcat", return_value=0):
            result = finalize_snapshot(ctx)
        assert result is True

    def test_rclone_finalize_failure(self):
        ctx = _make_ctx(remote_type="s3", timestamp="2026-03-24T120000")
        with patch("lib.core.rclone.rclone_rcat", return_value=1):
            result = finalize_snapshot(ctx)
        assert result is False


class TestCountPartialSnapshots:
    def test_local_counts(self):
        ctx = _make_ctx(remote_type="local")
        with patch("glob.glob", return_value=["/a/x.partial", "/a/y.partial"]):
            assert count_partial_snapshots(ctx) == 2

    def test_local_zero(self):
        ctx = _make_ctx(remote_type="local")
        with patch("glob.glob", return_value=[]):
            assert count_partial_snapshots(ctx) == 0

    def test_ssh_counts(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock(returncode=0, stdout="3\n")
        with patch.object(SSHOpts, "run", return_value=mock_result):
            assert count_partial_snapshots(ctx) == 3

    def test_ssh_parse_failure(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock(returncode=0, stdout="not-a-number\n")
        with patch.object(SSHOpts, "run", return_value=mock_result):
            assert count_partial_snapshots(ctx) == 0

    def test_rclone_returns_zero(self):
        ctx = _make_ctx(remote_type="s3")
        assert count_partial_snapshots(ctx) == 0


class TestIsSnapshotPinned:
    def test_local_pinned_true(self, tmp_path):
        snap_dir = tmp_path / "backups" / "myhost" / "targets" / "web" / "snapshots"
        meta_dir = snap_dir / "2026-03-24T100000"
        meta_dir.mkdir(parents=True)
        (meta_dir / "meta.json").write_text(json.dumps({"pinned": True}))

        ctx = _make_ctx(remote_type="local", base=str(tmp_path / "backups"))
        result = is_snapshot_pinned(ctx, "2026-03-24T100000")
        assert result is True

    def test_local_pinned_false(self, tmp_path):
        snap_dir = tmp_path / "backups" / "myhost" / "targets" / "web" / "snapshots"
        meta_dir = snap_dir / "2026-03-24T100000"
        meta_dir.mkdir(parents=True)
        (meta_dir / "meta.json").write_text(json.dumps({"pinned": False}))

        ctx = _make_ctx(remote_type="local", base=str(tmp_path / "backups"))
        result = is_snapshot_pinned(ctx, "2026-03-24T100000")
        assert result is False

    def test_local_no_meta_json(self, tmp_path):
        snap_dir = tmp_path / "backups" / "myhost" / "targets" / "web" / "snapshots"
        meta_dir = snap_dir / "2026-03-24T100000"
        meta_dir.mkdir(parents=True)

        ctx = _make_ctx(remote_type="local", base=str(tmp_path / "backups"))
        result = is_snapshot_pinned(ctx, "2026-03-24T100000")
        assert result is False

    def test_local_invalid_json(self, tmp_path):
        snap_dir = tmp_path / "backups" / "myhost" / "targets" / "web" / "snapshots"
        meta_dir = snap_dir / "2026-03-24T100000"
        meta_dir.mkdir(parents=True)
        (meta_dir / "meta.json").write_text("not valid json{{{")

        ctx = _make_ctx(remote_type="local", base=str(tmp_path / "backups"))
        result = is_snapshot_pinned(ctx, "2026-03-24T100000")
        assert result is False

    def test_local_pinned_key_missing(self, tmp_path):
        snap_dir = tmp_path / "backups" / "myhost" / "targets" / "web" / "snapshots"
        meta_dir = snap_dir / "2026-03-24T100000"
        meta_dir.mkdir(parents=True)
        (meta_dir / "meta.json").write_text(json.dumps({"status": "ok"}))

        ctx = _make_ctx(remote_type="local", base=str(tmp_path / "backups"))
        result = is_snapshot_pinned(ctx, "2026-03-24T100000")
        assert result is False

    def test_ssh_pinned_true(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock(returncode=0, stdout='{"pinned": true}')
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = is_snapshot_pinned(ctx, "2026-03-24T100000")
        assert result is True

    def test_ssh_pinned_false(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock(returncode=0, stdout='{"pinned": false}')
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = is_snapshot_pinned(ctx, "2026-03-24T100000")
        assert result is False

    def test_ssh_cat_fails(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock(returncode=1, stdout="")
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = is_snapshot_pinned(ctx, "2026-03-24T100000")
        assert result is False

    def test_ssh_invalid_json(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock(returncode=0, stdout="not json")
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = is_snapshot_pinned(ctx, "2026-03-24T100000")
        assert result is False


class TestUpdateLatestSymlink:
    def test_local_creates_symlink(self, tmp_path):
        snap_dir = tmp_path / "backups" / "myhost" / "targets" / "web" / "snapshots"
        snap_dir.mkdir(parents=True)
        (snap_dir / "2026-03-24T100000").mkdir()

        ctx = _make_ctx(remote_type="local", base=str(tmp_path / "backups"))
        result = update_latest_symlink(ctx, "2026-03-24T100000")
        assert result is True
        latest = snap_dir.parent / "latest"
        assert latest.is_symlink()

    def test_ssh_success(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock(returncode=0)
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = update_latest_symlink(ctx, "2026-03-24T100000")
        assert result is True

    def test_ssh_failure(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock(returncode=1)
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = update_latest_symlink(ctx, "2026-03-24T100000")
        assert result is False
