"""Tests for lib.core.retention — retention policy pruning."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from lib.core.retention import enforce_retention, _delete_snapshot
from lib.models import Target, Remote, AppSettings
from lib.core.context import BackupContext
from lib.ssh import SSHOpts


def _make_ctx(remote_type="local", base="/backups", target_name="web",
              hostname="myhost", timestamp="2026-03-24T120000",
              retention_count="30"):
    """Helper to build a BackupContext for tests."""
    target = Target(name=target_name, folders="/etc")
    remote = Remote(name="r", type=remote_type, host="10.0.0.1",
                    user="gniza", base=base)
    settings = AppSettings(retention_count=retention_count)
    return BackupContext(
        target=target, remote=remote, settings=settings,
        hostname=hostname, timestamp=timestamp,
        work_dir=Path("/tmp"), log_dir=Path("/tmp"),
    )


class TestEnforceRetention:
    def test_basic_pruning_keep_3_have_5(self):
        """Keep 3, have 5 unpinned => prune 2 oldest."""
        ctx = _make_ctx(remote_type="local", retention_count="3")
        snapshots = [
            "2026-03-24T100000",
            "2026-03-23T100000",
            "2026-03-22T100000",
            "2026-03-21T100000",
            "2026-03-20T100000",
        ]
        with patch("lib.core.retention.list_snapshots", return_value=snapshots):
            with patch("lib.core.retention._prefetch_pinned", return_value=set()):
                with patch("lib.core.retention._delete_snapshot", return_value=True) as mock_del:
                    result = enforce_retention(ctx)
        assert result == 2
        assert mock_del.call_count == 2
        # Should delete the 2 oldest
        mock_del.assert_any_call(ctx, "2026-03-21T100000")
        mock_del.assert_any_call(ctx, "2026-03-20T100000")

    def test_pinned_skipped_and_dont_count(self):
        """Pinned snapshots are skipped and don't count toward the limit."""
        ctx = _make_ctx(remote_type="local", retention_count="2")
        snapshots = [
            "2026-03-24T100000",
            "2026-03-23T100000",  # pinned
            "2026-03-22T100000",
            "2026-03-21T100000",
        ]
        pinned = {"2026-03-23T100000"}
        with patch("lib.core.retention.list_snapshots", return_value=snapshots):
            with patch("lib.core.retention._prefetch_pinned", return_value=pinned):
                with patch("lib.core.retention._delete_snapshot", return_value=True) as mock_del:
                    result = enforce_retention(ctx)
        assert result == 1
        # Only the oldest unpinned (2026-03-21) should be deleted.
        # 2026-03-24 is #1, 2026-03-23 is pinned (skipped), 2026-03-22 is #2,
        # 2026-03-21 is #3 (exceeds keep=2).
        mock_del.assert_called_once_with(ctx, "2026-03-21T100000")

    def test_empty_snapshot_list(self):
        ctx = _make_ctx(remote_type="local", retention_count="3")
        with patch("lib.core.retention.list_snapshots", return_value=[]):
            result = enforce_retention(ctx)
        assert result == 0

    def test_override_count(self):
        """Override count takes precedence over settings."""
        ctx = _make_ctx(remote_type="local", retention_count="30")
        snapshots = [
            "2026-03-24T100000",
            "2026-03-23T100000",
            "2026-03-22T100000",
        ]
        with patch("lib.core.retention.list_snapshots", return_value=snapshots):
            with patch("lib.core.retention._prefetch_pinned", return_value=set()):
                with patch("lib.core.retention._delete_snapshot", return_value=True) as mock_del:
                    result = enforce_retention(ctx, override_count=1)
        assert result == 2
        mock_del.assert_any_call(ctx, "2026-03-23T100000")
        mock_del.assert_any_call(ctx, "2026-03-22T100000")

    def test_delete_failure_continues(self):
        """If a delete fails, log warning and continue with remaining."""
        ctx = _make_ctx(remote_type="local", retention_count="1")
        snapshots = [
            "2026-03-24T100000",
            "2026-03-23T100000",
            "2026-03-22T100000",
        ]
        with patch("lib.core.retention.list_snapshots", return_value=snapshots):
            with patch("lib.core.retention._prefetch_pinned", return_value=set()):
                with patch("lib.core.retention._delete_snapshot", side_effect=[False, True]) as mock_del:
                    result = enforce_retention(ctx)
        # One failed, one succeeded
        assert result == 1
        assert mock_del.call_count == 2

    def test_nothing_to_prune(self):
        """Have exactly keep count => prune 0."""
        ctx = _make_ctx(remote_type="local", retention_count="3")
        snapshots = [
            "2026-03-24T100000",
            "2026-03-23T100000",
            "2026-03-22T100000",
        ]
        with patch("lib.core.retention.list_snapshots", return_value=snapshots):
            with patch("lib.core.retention._prefetch_pinned", return_value=set()):
                with patch("lib.core.retention._delete_snapshot") as mock_del:
                    result = enforce_retention(ctx)
        assert result == 0
        mock_del.assert_not_called()

    def test_fewer_than_keep(self):
        """Have fewer than keep count => prune 0."""
        ctx = _make_ctx(remote_type="local", retention_count="10")
        snapshots = [
            "2026-03-24T100000",
            "2026-03-23T100000",
        ]
        with patch("lib.core.retention.list_snapshots", return_value=snapshots):
            with patch("lib.core.retention._prefetch_pinned", return_value=set()):
                with patch("lib.core.retention._delete_snapshot") as mock_del:
                    result = enforce_retention(ctx)
        assert result == 0
        mock_del.assert_not_called()


class TestDeleteSnapshot:
    def test_local_success(self):
        ctx = _make_ctx(remote_type="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = _delete_snapshot(ctx, "2026-03-20T100000")
        assert result is True
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["rm", "-rf", "/backups/myhost/targets/web/snapshots/2026-03-20T100000"]

    def test_local_sudo_fallback(self):
        ctx = _make_ctx(remote_type="local")
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=1),   # rm fails
                MagicMock(returncode=0),   # sudo rm succeeds
            ]
            result = _delete_snapshot(ctx, "2026-03-20T100000")
        assert result is True
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[1][0][0][0] == "sudo"

    def test_local_both_fail(self):
        ctx = _make_ctx(remote_type="local")
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=1),
                MagicMock(returncode=1),
            ]
            result = _delete_snapshot(ctx, "2026-03-20T100000")
        assert result is False

    def test_local_exception(self):
        ctx = _make_ctx(remote_type="local")
        with patch("subprocess.run", side_effect=Exception("boom")):
            result = _delete_snapshot(ctx, "2026-03-20T100000")
        assert result is False

    def test_ssh_success(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock(returncode=0)
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = _delete_snapshot(ctx, "2026-03-20T100000")
        assert result is True

    def test_ssh_failure(self):
        ctx = _make_ctx(remote_type="ssh")
        mock_result = MagicMock(returncode=1)
        with patch.object(SSHOpts, "run", return_value=mock_result):
            result = _delete_snapshot(ctx, "2026-03-20T100000")
        assert result is False

    def test_rclone_returns_false(self):
        ctx = _make_ctx(remote_type="s3")
        result = _delete_snapshot(ctx, "2026-03-20T100000")
        assert result is False
