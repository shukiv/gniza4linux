"""Tests for lib.core.backup — backup orchestration."""
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from lib.models import Target, Remote, AppSettings
from lib.core.context import BackupContext
from lib.core.locking import TargetLock
from lib.ssh import SSHOpts


def _make_ctx(remote_type="local", base="/backups", target_name="web",
              hostname="myhost", timestamp="2026-03-24T120000",
              folders="/etc,/home", source_type="local",
              mysql_enabled="no", postgresql_enabled="no",
              crontab_enabled="no", pre_hook="", post_hook="",
              enabled="yes"):
    """Helper to build a BackupContext for tests."""
    target = Target(
        name=target_name, folders=folders, source_type=source_type,
        mysql_enabled=mysql_enabled, postgresql_enabled=postgresql_enabled,
        crontab_enabled=crontab_enabled, pre_hook=pre_hook, post_hook=post_hook,
        enabled=enabled,
    )
    remote = Remote(name="r", type=remote_type, host="10.0.0.1",
                    user="gniza", base=base)
    return BackupContext(
        target=target, remote=remote, settings=AppSettings(),
        hostname=hostname, timestamp=timestamp,
        work_dir=Path("/tmp"), log_dir=Path("/tmp"),
    )


def _make_target_conf(conf_dir, name, folders="/etc", enabled="yes",
                      pre_hook="", post_hook="", mysql_enabled="no",
                      postgresql_enabled="no", crontab_enabled="no",
                      source_type="local"):
    """Write a target .conf file."""
    lines = [
        'TARGET_FOLDERS="%s"' % folders,
        'TARGET_ENABLED="%s"' % enabled,
        'TARGET_SOURCE_TYPE="%s"' % source_type,
    ]
    if pre_hook:
        lines.append('TARGET_PRE_HOOK="%s"' % pre_hook)
    if post_hook:
        lines.append('TARGET_POST_HOOK="%s"' % post_hook)
    if mysql_enabled == "yes":
        lines.append('TARGET_MYSQL_ENABLED="yes"')
    if postgresql_enabled == "yes":
        lines.append('TARGET_POSTGRESQL_ENABLED="yes"')
    if crontab_enabled == "yes":
        lines.append('TARGET_CRONTAB_ENABLED="yes"')
    (conf_dir / "targets.d" / ("%s.conf" % name)).write_text("\n".join(lines) + "\n")


def _make_remote_conf(conf_dir, name, remote_type="local", base="/backups"):
    """Write a remote .conf file."""
    lines = [
        'REMOTE_TYPE="%s"' % remote_type,
        'REMOTE_BASE="%s"' % base,
    ]
    if remote_type == "ssh":
        lines.append('REMOTE_HOST="10.0.0.1"')
        lines.append('REMOTE_USER="gniza"')
    (conf_dir / "remotes.d" / ("%s.conf" % name)).write_text("\n".join(lines) + "\n")


def _make_gniza_conf(conf_dir):
    """Write a minimal gniza.conf."""
    (conf_dir / "gniza.conf").write_text(
        'RETENTION_COUNT="30"\nDISK_USAGE_THRESHOLD="0"\n'
    )


@pytest.fixture
def backup_conf(tmp_path):
    """Create a temporary config with target and remote."""
    conf_dir = tmp_path / "gniza"
    conf_dir.mkdir()
    (conf_dir / "targets.d").mkdir()
    (conf_dir / "remotes.d").mkdir()
    (conf_dir / "schedules.d").mkdir()

    _make_gniza_conf(conf_dir)
    _make_target_conf(conf_dir, "web", folders="/etc,/home")
    _make_remote_conf(conf_dir, "nas", remote_type="local", base=str(tmp_path / "backups"))

    work_dir = tmp_path / "work"
    work_dir.mkdir()

    # Create backup base dir
    (tmp_path / "backups").mkdir()

    import lib.config
    orig_config = lib.config.CONFIG_DIR
    orig_work = lib.config.WORK_DIR
    lib.config.CONFIG_DIR = conf_dir
    lib.config.WORK_DIR = work_dir
    lib.config._conf_dir_cache.clear()
    yield conf_dir, tmp_path
    lib.config.CONFIG_DIR = orig_config
    lib.config.WORK_DIR = orig_work
    lib.config._conf_dir_cache.clear()


class TestBackupTarget:

    def test_missing_target_returns_1(self, backup_conf):
        """Missing target config returns 1."""
        from lib.core.backup import backup_target
        rc = backup_target("nonexistent", "nas")
        assert rc == 1

    def test_disabled_target_returns_0(self, backup_conf):
        """Disabled target returns 0 (matching Bash behavior)."""
        conf_dir, tmp_path = backup_conf
        _make_target_conf(conf_dir, "disabled_target", enabled="no")
        from lib.core.backup import backup_target
        rc = backup_target("disabled_target", "nas")
        assert rc == 0

    def test_missing_remote_returns_1(self, backup_conf):
        """Target pointing to nonexistent remote returns 1."""
        from lib.core.backup import backup_target
        rc = backup_target("web", "nonexistent_remote")
        assert rc == 1

    def test_no_remote_configured_returns_1(self, tmp_path):
        """No remotes at all configured returns 1."""
        conf_dir = tmp_path / "gniza_empty"
        conf_dir.mkdir()
        (conf_dir / "targets.d").mkdir()
        (conf_dir / "remotes.d").mkdir()
        (conf_dir / "schedules.d").mkdir()
        _make_gniza_conf(conf_dir)
        _make_target_conf(conf_dir, "web")

        work_dir = tmp_path / "work2"
        work_dir.mkdir()

        import lib.config
        orig_config = lib.config.CONFIG_DIR
        orig_work = lib.config.WORK_DIR
        lib.config.CONFIG_DIR = conf_dir
        lib.config.WORK_DIR = work_dir

        try:
            from lib.core.backup import backup_target
            rc = backup_target("web")
            assert rc == 1
        finally:
            lib.config.CONFIG_DIR = orig_config
            lib.config.WORK_DIR = orig_work

    def test_lock_conflict_returns_2(self, backup_conf):
        """Lock conflict returns 2."""
        conf_dir, tmp_path = backup_conf
        work_dir = tmp_path / "work"

        # Hold the lock so backup_target cannot acquire it
        held_lock = TargetLock("web", work_dir)
        assert held_lock.acquire()

        try:
            from lib.core.backup import backup_target
            rc = backup_target("web", "nas")
            assert rc == 2
        finally:
            held_lock.release()

    def test_pre_hook_failure_returns_1(self, backup_conf):
        """Pre-hook failure returns 1 without transferring."""
        conf_dir, tmp_path = backup_conf
        _make_target_conf(conf_dir, "hook_target", pre_hook="exit 1")

        with patch("lib.core.backup.get_latest_snapshot", return_value=None), \
             patch("lib.core.backup.clean_partial_snapshots"), \
             patch("lib.core.backup._check_remote_disk_space", return_value=True), \
             patch("lib.core.backup.transfer_local") as mock_transfer:
            from lib.core.backup import backup_target
            rc = backup_target("hook_target", "nas")
            assert rc == 1
            mock_transfer.assert_not_called()

    def test_transfer_failure_returns_1(self, backup_conf):
        """Transfer failure returns 1, finalize is not called."""
        conf_dir, tmp_path = backup_conf

        with patch("lib.core.backup.get_latest_snapshot", return_value=None), \
             patch("lib.core.backup.clean_partial_snapshots"), \
             patch("lib.core.backup._check_remote_disk_space", return_value=True), \
             patch("lib.core.backup.transfer_local", return_value=1), \
             patch("lib.core.backup.finalize_snapshot") as mock_finalize:
            from lib.core.backup import backup_target
            rc = backup_target("web", "nas")
            assert rc == 1
            mock_finalize.assert_not_called()

    def test_successful_backup_flow(self, backup_conf):
        """Full successful backup: transfer, meta.json, finalize, retention."""
        conf_dir, tmp_path = backup_conf

        with patch("lib.core.backup.get_latest_snapshot", return_value=None), \
             patch("lib.core.backup.clean_partial_snapshots"), \
             patch("lib.core.backup._check_remote_disk_space", return_value=True), \
             patch("lib.core.backup.transfer_local", return_value=0) as mock_transfer, \
             patch("lib.core.backup.finalize_snapshot", return_value=True) as mock_finalize, \
             patch("lib.core.backup.enforce_retention") as mock_retention, \
             patch("lib.core.backup._generate_meta_json") as mock_meta:
            from lib.core.backup import backup_target
            rc = backup_target("web", "nas")
            assert rc == 0
            # transfer_local called once per folder (/etc, /home)
            assert mock_transfer.call_count == 2
            mock_finalize.assert_called_once()
            mock_retention.assert_called_once()
            mock_meta.assert_called_once()

    def test_db_dump_failure_continues(self, backup_conf):
        """Database dump failure does not stop the file backup."""
        conf_dir, tmp_path = backup_conf
        _make_target_conf(conf_dir, "db_target", folders="/etc", mysql_enabled="yes")

        with patch("lib.core.backup.get_latest_snapshot", return_value=None), \
             patch("lib.core.backup.clean_partial_snapshots"), \
             patch("lib.core.backup._check_remote_disk_space", return_value=True), \
             patch("lib.core.backup.transfer_local", return_value=0), \
             patch("lib.core.backup.finalize_snapshot", return_value=True), \
             patch("lib.core.backup.enforce_retention"), \
             patch("lib.core.backup._generate_meta_json"), \
             patch("lib.core.db.mysql.dump_databases", side_effect=RuntimeError("MySQL not found")):
            from lib.core.backup import backup_target
            rc = backup_target("db_target", "nas")
            # File backup should succeed even though MySQL dump failed
            assert rc == 0

    def test_retention_failure_does_not_fail_backup(self, backup_conf):
        """Retention failure is logged but doesn't fail the backup."""
        conf_dir, tmp_path = backup_conf

        with patch("lib.core.backup.get_latest_snapshot", return_value=None), \
             patch("lib.core.backup.clean_partial_snapshots"), \
             patch("lib.core.backup._check_remote_disk_space", return_value=True), \
             patch("lib.core.backup.transfer_local", return_value=0), \
             patch("lib.core.backup.finalize_snapshot", return_value=True), \
             patch("lib.core.backup.enforce_retention", side_effect=RuntimeError("retention boom")), \
             patch("lib.core.backup._generate_meta_json"):
            from lib.core.backup import backup_target
            rc = backup_target("web", "nas")
            assert rc == 0

    def test_finalize_failure_returns_1(self, backup_conf):
        """Finalize failure returns 1."""
        conf_dir, tmp_path = backup_conf

        with patch("lib.core.backup.get_latest_snapshot", return_value=None), \
             patch("lib.core.backup.clean_partial_snapshots"), \
             patch("lib.core.backup._check_remote_disk_space", return_value=True), \
             patch("lib.core.backup.transfer_local", return_value=0), \
             patch("lib.core.backup.finalize_snapshot", return_value=False), \
             patch("lib.core.backup._generate_meta_json"):
            from lib.core.backup import backup_target
            rc = backup_target("web", "nas")
            assert rc == 1

    def test_post_hook_failure_does_not_fail_backup(self, backup_conf):
        """Post-hook failure is tolerated (doesn't change return code)."""
        conf_dir, tmp_path = backup_conf
        _make_target_conf(conf_dir, "post_hook_target", post_hook="exit 1")

        with patch("lib.core.backup.get_latest_snapshot", return_value=None), \
             patch("lib.core.backup.clean_partial_snapshots"), \
             patch("lib.core.backup._check_remote_disk_space", return_value=True), \
             patch("lib.core.backup.transfer_local", return_value=0), \
             patch("lib.core.backup.finalize_snapshot", return_value=True), \
             patch("lib.core.backup.enforce_retention"), \
             patch("lib.core.backup._generate_meta_json"):
            from lib.core.backup import backup_target
            rc = backup_target("post_hook_target", "nas")
            assert rc == 0

    def test_disk_space_check_failure_returns_1(self, backup_conf):
        """Disk space threshold exceeded returns 1 before any transfer."""
        conf_dir, tmp_path = backup_conf
        # Write gniza.conf with a threshold
        (conf_dir / "gniza.conf").write_text(
            'RETENTION_COUNT="30"\nDISK_USAGE_THRESHOLD="90"\n'
        )

        with patch("lib.core.backup.get_latest_snapshot", return_value=None), \
             patch("lib.core.backup.clean_partial_snapshots"), \
             patch("lib.core.backup._check_remote_disk_space", return_value=False), \
             patch("lib.core.backup.transfer_local") as mock_transfer:
            from lib.core.backup import backup_target
            rc = backup_target("web", "nas")
            assert rc == 1
            mock_transfer.assert_not_called()

    def test_previous_snapshot_sets_link_dest(self, backup_conf):
        """When a previous snapshot exists, it's passed for --link-dest."""
        conf_dir, tmp_path = backup_conf

        prev_ts = "2026-03-23T100000"

        with patch("lib.core.backup.get_latest_snapshot", return_value=prev_ts), \
             patch("lib.core.backup.clean_partial_snapshots"), \
             patch("lib.core.backup._check_remote_disk_space", return_value=True), \
             patch("lib.core.backup.transfer_local", return_value=0) as mock_transfer, \
             patch("lib.core.backup.finalize_snapshot", return_value=True), \
             patch("lib.core.backup.enforce_retention"), \
             patch("lib.core.backup._generate_meta_json"):
            from lib.core.backup import backup_target
            rc = backup_target("web", "nas")
            assert rc == 0
            # Check that link_dest was passed (non-empty)
            for c in mock_transfer.call_args_list:
                # link_dest is the 5th positional arg (index 4)
                link_dest = c[0][4] if len(c[0]) > 4 else ""
                assert prev_ts in link_dest


class TestBackupAllTargets:

    def test_no_targets_returns_1(self, tmp_path):
        """No targets configured returns 1."""
        conf_dir = tmp_path / "gniza_empty2"
        conf_dir.mkdir()
        (conf_dir / "targets.d").mkdir()
        (conf_dir / "remotes.d").mkdir()
        (conf_dir / "schedules.d").mkdir()
        _make_gniza_conf(conf_dir)
        _make_remote_conf(conf_dir, "nas")

        import lib.config
        orig_config = lib.config.CONFIG_DIR
        lib.config.CONFIG_DIR = conf_dir

        try:
            from lib.core.backup import backup_all_targets
            rc = backup_all_targets("nas")
            assert rc == 1
        finally:
            lib.config.CONFIG_DIR = orig_config

    def test_all_succeed_returns_0(self, backup_conf):
        """All targets succeed returns 0."""
        conf_dir, tmp_path = backup_conf

        with patch("lib.core.backup.backup_target", return_value=0):
            from lib.core.backup import backup_all_targets
            rc = backup_all_targets("nas")
            assert rc == 0

    def test_mixed_returns_3(self, backup_conf):
        """Some succeed, some fail returns 3 (EXIT_PARTIAL)."""
        conf_dir, tmp_path = backup_conf
        _make_target_conf(conf_dir, "web2", folders="/var")

        # Clear list_conf_dir cache so new file is picked up
        import lib.config
        lib.config._conf_dir_cache.clear()

        call_count = [0]

        def _mock_backup(name, remote, **kw):
            call_count[0] += 1
            return 1 if name == "web" else 0

        with patch("lib.core.backup.backup_target", side_effect=_mock_backup):
            from lib.core.backup import backup_all_targets
            rc = backup_all_targets("nas")
            assert rc == 3


class TestTransferFolder:

    def test_local_remote_calls_transfer_local(self):
        """Local remote uses transfer_local."""
        ctx = _make_ctx(remote_type="local")
        with patch("lib.core.backup.transfer_local", return_value=0) as mock:
            from lib.core.backup import _transfer_folder
            rc = _transfer_folder(ctx, "/etc", "etc", "2026-03-24T120000", "")
            assert rc == 0
            mock.assert_called_once()

    def test_ssh_remote_calls_transfer_to_remote(self):
        """SSH remote uses transfer_to_remote."""
        ctx = _make_ctx(remote_type="ssh")
        with patch("lib.core.backup.transfer_to_remote", return_value=0) as mock:
            from lib.core.backup import _transfer_folder
            rc = _transfer_folder(ctx, "/etc", "etc", "2026-03-24T120000", "")
            assert rc == 0
            mock.assert_called_once()

    def test_rclone_remote_calls_rclone_sync(self):
        """Rclone remote uses rclone_sync_incremental."""
        ctx = _make_ctx(remote_type="s3")
        with patch("lib.core.rclone.rclone_sync_incremental", return_value=0) as mock:
            from lib.core.backup import _transfer_folder
            rc = _transfer_folder(ctx, "/etc", "etc", "2026-03-24T120000", "")
            assert rc == 0
            mock.assert_called_once()


class TestGenerateMetaJson:

    def test_writes_meta_json_local(self, tmp_path):
        """meta.json is written to the .partial directory for local remotes."""
        snap_dir = tmp_path / "backups" / "myhost" / "targets" / "web" / "snapshots"
        partial_dir = snap_dir / "2026-03-24T120000.partial"
        partial_dir.mkdir(parents=True)

        ctx = _make_ctx(remote_type="local", base=str(tmp_path / "backups"))

        from lib.core.backup import _generate_meta_json
        import time
        _generate_meta_json(ctx, "web", "2026-03-24T120000", time.time() - 10)

        meta_path = partial_dir / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["target"] == "web"
        assert meta["hostname"] == "myhost"
        assert meta["timestamp"] == "2026-03-24T120000"
        assert meta["pinned"] is False
        assert isinstance(meta["duration"], int)

    def test_meta_json_contains_db_flags(self, tmp_path):
        """meta.json includes mysql/postgresql/crontab flags."""
        snap_dir = tmp_path / "backups" / "myhost" / "targets" / "web" / "snapshots"
        partial_dir = snap_dir / "2026-03-24T120000.partial"
        partial_dir.mkdir(parents=True)

        ctx = _make_ctx(
            remote_type="local", base=str(tmp_path / "backups"),
            mysql_enabled="yes", crontab_enabled="yes",
        )

        from lib.core.backup import _generate_meta_json
        import time
        _generate_meta_json(ctx, "web", "2026-03-24T120000", time.time())

        meta = json.loads((partial_dir / "meta.json").read_text())
        assert meta["mysql_dumps"] is True
        assert meta["postgresql_dumps"] is False
        assert meta["crontab_dumps"] is True


class TestCheckRemoteDiskSpace:

    def test_threshold_zero_always_ok(self):
        """Threshold 0 means no check."""
        ctx = _make_ctx()
        from lib.core.backup import _check_remote_disk_space
        assert _check_remote_disk_space(ctx, 0) is True

    def test_local_under_threshold(self):
        """Local disk under threshold returns True."""
        ctx = _make_ctx(remote_type="local")
        mock_result = MagicMock(returncode=0, stdout="Use%\n 50%\n")
        with patch("subprocess.run", return_value=mock_result):
            from lib.core.backup import _check_remote_disk_space
            assert _check_remote_disk_space(ctx, 95) is True

    def test_local_over_threshold(self):
        """Local disk over threshold returns False."""
        ctx = _make_ctx(remote_type="local")
        mock_result = MagicMock(returncode=0, stdout="Use%\n 96%\n")
        with patch("subprocess.run", return_value=mock_result):
            from lib.core.backup import _check_remote_disk_space
            assert _check_remote_disk_space(ctx, 95) is False

    def test_ssh_under_threshold(self):
        """SSH remote under threshold returns True."""
        ctx = _make_ctx(remote_type="ssh")
        mock_ssh_result = MagicMock(returncode=0, stdout="50%")
        with patch.object(SSHOpts, "run", return_value=mock_ssh_result):
            from lib.core.backup import _check_remote_disk_space
            assert _check_remote_disk_space(ctx, 95) is True

    def test_ssh_over_threshold(self):
        """SSH remote over threshold returns False."""
        ctx = _make_ctx(remote_type="ssh")
        mock_ssh_result = MagicMock(returncode=0, stdout="96%")
        with patch.object(SSHOpts, "run", return_value=mock_ssh_result):
            from lib.core.backup import _check_remote_disk_space
            assert _check_remote_disk_space(ctx, 95) is False

    def test_df_failure_is_safe(self):
        """df command failure does not block backup (returns True)."""
        ctx = _make_ctx(remote_type="local")
        mock_result = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            from lib.core.backup import _check_remote_disk_space
            assert _check_remote_disk_space(ctx, 95) is True


class TestCleanupDumpDirs:

    def test_cleanup_removes_dirs(self, tmp_path):
        """Cleanup removes temp dump directories."""
        d1 = tmp_path / "dump1"
        d1.mkdir()
        (d1 / "file.sql").write_text("data")
        d2 = tmp_path / "dump2"
        d2.mkdir()

        from lib.core.backup import _cleanup_dump_dirs
        _cleanup_dump_dirs(str(d1), str(d2), "")

        assert not d1.exists()
        assert not d2.exists()

    def test_cleanup_handles_empty_strings(self):
        """Cleanup handles empty strings gracefully."""
        from lib.core.backup import _cleanup_dump_dirs
        # Should not raise
        _cleanup_dump_dirs("", "", "")
