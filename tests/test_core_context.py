"""Tests for BackupContext."""
import pytest
from unittest.mock import patch, MagicMock
from lib.core.context import BackupContext


class TestBackupContext:
    def test_create_from_models(self):
        """Test constructing BackupContext from model objects."""
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        target = Target(name="test", folders="/etc,/home", source_type="ssh",
                       source_host="192.168.1.1", source_user="gniza")
        remote = Remote(name="nas", type="ssh", host="10.0.0.1",
                       user="gniza", base="/backups")
        settings = AppSettings()

        ctx = BackupContext(
            target=target, remote=remote, settings=settings,
            hostname="myhost", timestamp="2026-03-24T120000",
            work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )

        assert ctx.target.name == "test"
        assert ctx.remote.name == "nas"
        assert ctx.hostname == "myhost"
        assert ctx.timestamp == "2026-03-24T120000"
        assert ctx.is_ssh_remote
        assert ctx.is_ssh_source

    def test_snap_dir(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        target = Target(name="webserver", folders="/etc")
        remote = Remote(name="nas", type="ssh", base="/backups")
        ctx = BackupContext(
            target=target, remote=remote, settings=AppSettings(),
            hostname="myhost", timestamp="2026-03-24T120000",
            work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.snap_dir == "/backups/myhost/targets/webserver/snapshots"

    def test_snap_dir_strips_trailing_slash(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        remote = Remote(name="nas", type="ssh", base="/backups/")
        ctx = BackupContext(
            target=Target(name="t"), remote=remote, settings=AppSettings(),
            hostname="h", timestamp="ts", work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.snap_dir == "/backups/h/targets/t/snapshots"

    def test_is_local_remote(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        remote = Remote(name="local", type="local", base="/backups")
        ctx = BackupContext(
            target=Target(name="t"), remote=remote, settings=AppSettings(),
            hostname="h", timestamp="ts", work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.is_local_remote
        assert not ctx.is_ssh_remote
        assert not ctx.is_rclone_remote

    def test_is_rclone_remote_s3(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        remote = Remote(name="s3", type="s3")
        ctx = BackupContext(
            target=Target(name="t"), remote=remote, settings=AppSettings(),
            hostname="h", timestamp="ts", work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.is_rclone_remote
        assert not ctx.is_ssh_remote
        assert not ctx.is_local_remote

    def test_is_rclone_remote_gdrive(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        remote = Remote(name="gd", type="gdrive")
        ctx = BackupContext(
            target=Target(name="t"), remote=remote, settings=AppSettings(),
            hostname="h", timestamp="ts", work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.is_rclone_remote

    def test_bwlimit_remote_override(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        remote = Remote(name="r", type="ssh", bwlimit="5000")
        settings = AppSettings(bwlimit="1000")
        ctx = BackupContext(
            target=Target(name="t"), remote=remote, settings=settings,
            hostname="h", timestamp="ts", work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.bwlimit == 5000  # remote override wins

    def test_bwlimit_global_fallback(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        remote = Remote(name="r", type="ssh", bwlimit="")
        settings = AppSettings(bwlimit="2000")
        ctx = BackupContext(
            target=Target(name="t"), remote=remote, settings=settings,
            hostname="h", timestamp="ts", work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.bwlimit == 2000

    def test_bwlimit_zero_default(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        remote = Remote(name="r", type="ssh", bwlimit="0")
        settings = AppSettings(bwlimit="0")
        ctx = BackupContext(
            target=Target(name="t"), remote=remote, settings=settings,
            hostname="h", timestamp="ts", work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.bwlimit == 0

    def test_bwlimit_invalid_values(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        remote = Remote(name="r", type="ssh", bwlimit="notanumber")
        settings = AppSettings(bwlimit="alsobad")
        ctx = BackupContext(
            target=Target(name="t"), remote=remote, settings=settings,
            hostname="h", timestamp="ts", work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.bwlimit == 0

    def test_retention_count_default(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        ctx = BackupContext(
            target=Target(name="t"), remote=Remote(name="r", type="local"),
            settings=AppSettings(), hostname="h", timestamp="ts",
            work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.retention_count == 30

    def test_retention_count_custom(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        settings = AppSettings(retention_count="7")
        ctx = BackupContext(
            target=Target(name="t"), remote=Remote(name="r", type="local"),
            settings=settings, hostname="h", timestamp="ts",
            work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.retention_count == 7

    def test_retention_count_invalid(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        settings = AppSettings(retention_count="bad")
        ctx = BackupContext(
            target=Target(name="t"), remote=Remote(name="r", type="local"),
            settings=settings, hostname="h", timestamp="ts",
            work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.retention_count == 30

    def test_frozen(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        ctx = BackupContext(
            target=Target(name="t"), remote=Remote(name="r", type="local"),
            settings=AppSettings(), hostname="h", timestamp="ts",
            work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        with pytest.raises(AttributeError):
            ctx.timestamp = "new"

    def test_prev_snapshot_default_none(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        ctx = BackupContext(
            target=Target(name="t"), remote=Remote(name="r", type="local"),
            settings=AppSettings(), hostname="h", timestamp="ts",
            work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert ctx.prev_snapshot is None

    def test_is_ssh_source_local(self):
        from lib.models import Target, Remote, AppSettings
        from pathlib import Path

        ctx = BackupContext(
            target=Target(name="t", source_type="local"),
            remote=Remote(name="r", type="ssh"),
            settings=AppSettings(), hostname="h", timestamp="ts",
            work_dir=Path("/tmp"), log_dir=Path("/tmp"),
        )
        assert not ctx.is_ssh_source
