"""Tests for lib.core.restore — restore orchestration."""
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from lib.models import Target, Remote, AppSettings
from lib.core.context import BackupContext
from lib.ssh import SSHOpts


def _make_ctx(remote_type="local", base="/backups", target_name="web",
              hostname="myhost", timestamp="2026-03-24T120000",
              folders="/etc,/home", mysql_enabled="no",
              postgresql_enabled="no", crontab_enabled="no"):
    """Helper to build a BackupContext for tests."""
    target = Target(
        name=target_name, folders=folders,
        mysql_enabled=mysql_enabled, postgresql_enabled=postgresql_enabled,
        crontab_enabled=crontab_enabled,
    )
    remote = Remote(name="r", type=remote_type, host="10.0.0.1",
                    user="gniza", base=base)
    return BackupContext(
        target=target, remote=remote, settings=AppSettings(),
        hostname=hostname, timestamp=timestamp,
        work_dir=Path("/tmp"), log_dir=Path("/tmp"),
    )


def _make_target_conf(conf_dir, name, folders="/etc,/home",
                      mysql_enabled="no", postgresql_enabled="no",
                      crontab_enabled="no"):
    """Write a target .conf file."""
    lines = [
        'TARGET_FOLDERS="%s"' % folders,
        'TARGET_ENABLED="yes"',
        'TARGET_SOURCE_TYPE="local"',
    ]
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


@pytest.fixture
def restore_conf(tmp_path):
    """Create a temporary config with target and remote."""
    conf_dir = tmp_path / "gniza"
    conf_dir.mkdir()
    (conf_dir / "targets.d").mkdir()
    (conf_dir / "remotes.d").mkdir()
    (conf_dir / "schedules.d").mkdir()
    (conf_dir / "gniza.conf").write_text('RETENTION_COUNT="30"\n')

    _make_target_conf(conf_dir, "web", folders="/etc,/home")
    _make_remote_conf(conf_dir, "nas", remote_type="local",
                      base=str(tmp_path / "backups"))

    (tmp_path / "backups").mkdir()

    import lib.config
    orig_config = lib.config.CONFIG_DIR
    lib.config.CONFIG_DIR = conf_dir
    yield conf_dir, tmp_path
    lib.config.CONFIG_DIR = orig_config


class TestRestoreTarget:

    def test_missing_target_returns_1(self, restore_conf):
        """Missing target config returns 1."""
        from lib.core.restore import restore_target
        rc = restore_target("nonexistent", remote_name="nas")
        assert rc == 1

    def test_missing_remote_returns_1(self, restore_conf):
        """Missing remote config returns 1."""
        from lib.core.restore import restore_target
        rc = restore_target("web", remote_name="nonexistent")
        assert rc == 1

    def test_no_remote_specified_returns_1(self, restore_conf):
        """No remote specified returns 1."""
        from lib.core.restore import restore_target
        rc = restore_target("web")
        assert rc == 1

    def test_snapshot_not_found_returns_1(self, restore_conf):
        """Unresolvable snapshot timestamp returns 1."""
        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value=None):
            from lib.core.restore import restore_target
            rc = restore_target("web", snapshot_ts="bad-timestamp", remote_name="nas")
            assert rc == 1

    def test_successful_restore_local(self, restore_conf, tmp_path):
        """Successful restore from local remote."""
        conf_dir, _ = restore_conf
        dest = tmp_path / "restore_dest"
        dest.mkdir()

        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value="2026-03-24T120000"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            from lib.core.restore import restore_target
            rc = restore_target("web", snapshot_ts="latest", remote_name="nas",
                               dest_dir=str(dest))
            assert rc == 0

    def test_restore_with_mysql(self, restore_conf, tmp_path):
        """Restore with MySQL enabled attempts MySQL restore."""
        conf_dir, _ = restore_conf
        _make_target_conf(conf_dir, "dbweb", folders="/etc", mysql_enabled="yes")
        dest = tmp_path / "restore_dest2"
        dest.mkdir()

        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value="2026-03-24T120000"), \
             patch("subprocess.run") as mock_run, \
             patch("lib.core.restore._fetch_dump_subdir", return_value=True), \
             patch("lib.core.restore._has_dump_files", return_value=True), \
             patch("lib.core.db.mysql.restore_databases", return_value=True) as mock_mysql:
            mock_run.return_value = MagicMock(returncode=0)
            from lib.core.restore import restore_target
            rc = restore_target("dbweb", snapshot_ts="latest", remote_name="nas",
                               dest_dir=str(dest))
            assert rc == 0
            mock_mysql.assert_called_once()

    def test_skip_mysql_flag(self, restore_conf, tmp_path):
        """skip_mysql=True skips MySQL restore."""
        conf_dir, _ = restore_conf
        _make_target_conf(conf_dir, "dbweb2", folders="/etc", mysql_enabled="yes")
        dest = tmp_path / "restore_dest3"
        dest.mkdir()

        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value="2026-03-24T120000"), \
             patch("subprocess.run") as mock_run, \
             patch("lib.core.db.mysql.restore_databases") as mock_mysql:
            mock_run.return_value = MagicMock(returncode=0)
            from lib.core.restore import restore_target
            rc = restore_target("dbweb2", snapshot_ts="latest", remote_name="nas",
                               dest_dir=str(dest), skip_mysql=True)
            assert rc == 0
            mock_mysql.assert_not_called()

    def test_skip_postgresql_flag(self, restore_conf, tmp_path):
        """skip_postgresql=True skips PostgreSQL restore."""
        conf_dir, _ = restore_conf
        _make_target_conf(conf_dir, "pgweb", folders="/etc", postgresql_enabled="yes")
        dest = tmp_path / "restore_dest4"
        dest.mkdir()

        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value="2026-03-24T120000"), \
             patch("subprocess.run") as mock_run, \
             patch("lib.core.db.postgresql.restore_databases") as mock_pg:
            mock_run.return_value = MagicMock(returncode=0)
            from lib.core.restore import restore_target
            rc = restore_target("pgweb", snapshot_ts="latest", remote_name="nas",
                               dest_dir=str(dest), skip_postgresql=True)
            assert rc == 0
            mock_pg.assert_not_called()

    def test_restore_failure_returns_1(self, restore_conf, tmp_path):
        """rsync failure during restore returns 1."""
        conf_dir, _ = restore_conf
        dest = tmp_path / "restore_dest5"
        dest.mkdir()

        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value="2026-03-24T120000"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            from lib.core.restore import restore_target
            rc = restore_target("web", snapshot_ts="latest", remote_name="nas",
                               dest_dir=str(dest))
            assert rc == 1

    def test_custom_dest_dir(self, restore_conf, tmp_path):
        """Restore to custom destination creates correct paths."""
        conf_dir, _ = restore_conf
        dest = tmp_path / "custom_restore"
        dest.mkdir()

        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value="2026-03-24T120000"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            from lib.core.restore import restore_target
            rc = restore_target("web", snapshot_ts="latest", remote_name="nas",
                               dest_dir=str(dest))
            assert rc == 0
            # Check that destination directories were created
            assert (dest / "etc").exists()
            assert (dest / "home").exists()


class TestRestoreFolder:

    def test_missing_target_returns_1(self, restore_conf):
        """Missing target returns 1."""
        from lib.core.restore import restore_folder
        rc = restore_folder("nonexistent", "/etc", remote_name="nas")
        assert rc == 1

    def test_missing_remote_returns_1(self, restore_conf):
        """Missing remote returns 1."""
        from lib.core.restore import restore_folder
        rc = restore_folder("web", "/etc", remote_name="nonexistent")
        assert rc == 1

    def test_snapshot_not_found_returns_1(self, restore_conf):
        """Unresolvable snapshot returns 1."""
        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value=None):
            from lib.core.restore import restore_folder
            rc = restore_folder("web", "/etc", snapshot_ts="bad", remote_name="nas")
            assert rc == 1

    def test_successful_folder_restore(self, restore_conf, tmp_path):
        """Successful single-folder restore."""
        dest = tmp_path / "folder_restore"
        dest.mkdir()

        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value="2026-03-24T120000"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            from lib.core.restore import restore_folder
            rc = restore_folder("web", "/etc", snapshot_ts="latest",
                               remote_name="nas", dest_dir=str(dest))
            assert rc == 0

    def test_folder_restore_in_place(self, restore_conf, tmp_path):
        """In-place restore (no dest_dir) uses original path."""
        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value="2026-03-24T120000"), \
             patch("subprocess.run") as mock_run, \
             patch("os.makedirs"):
            mock_run.return_value = MagicMock(returncode=0)
            from lib.core.restore import restore_folder
            rc = restore_folder("web", "/etc", snapshot_ts="latest",
                               remote_name="nas")
            assert rc == 0

    def test_folder_restore_rsync_failure(self, restore_conf, tmp_path):
        """rsync failure returns 1."""
        dest = tmp_path / "folder_restore2"
        dest.mkdir()

        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value="2026-03-24T120000"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            from lib.core.restore import restore_folder
            rc = restore_folder("web", "/etc", snapshot_ts="latest",
                               remote_name="nas", dest_dir=str(dest))
            assert rc == 1


class TestListSnapshotContents:

    def test_missing_remote_returns_empty(self, restore_conf):
        """Missing remote returns empty list."""
        from lib.core.restore import list_snapshot_contents
        result = list_snapshot_contents("web", remote_name="nonexistent")
        assert result == []

    def test_no_remote_returns_empty(self, restore_conf):
        """No remote specified returns empty list."""
        from lib.core.restore import list_snapshot_contents
        result = list_snapshot_contents("web")
        assert result == []

    def test_local_lists_files(self, restore_conf, tmp_path):
        """Local remote uses os.walk to list files."""
        conf_dir, _ = restore_conf
        base = tmp_path / "backups"
        import socket
        hostname = socket.gethostname()
        snap_dir = base / hostname / "targets" / "web" / "snapshots" / "2026-03-24T120000"
        snap_dir.mkdir(parents=True)
        (snap_dir / "etc").mkdir()
        (snap_dir / "etc" / "hosts").write_text("test")

        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value="2026-03-24T120000"):
            from lib.core.restore import list_snapshot_contents
            result = list_snapshot_contents("web", snapshot_ts="latest",
                                           remote_name="nas")
            assert len(result) >= 1
            assert any("hosts" in f for f in result)

    def test_snapshot_not_found_returns_empty(self, restore_conf):
        """Unresolvable snapshot returns empty list."""
        with patch("lib.core.restore.resolve_snapshot_timestamp", return_value=None):
            from lib.core.restore import list_snapshot_contents
            result = list_snapshot_contents("web", snapshot_ts="bad",
                                           remote_name="nas")
            assert result == []


class TestFetchDumpSubdir:

    def test_local_found(self, tmp_path):
        """Local dump subdir is found and rsynced."""
        ctx = _make_ctx(remote_type="local", base=str(tmp_path / "backups"))
        snap_dir = ctx.snap_dir
        # Create the source dump directory
        mysql_src = Path(snap_dir) / "2026-03-24T120000" / "_mysql"
        mysql_src.mkdir(parents=True)
        (mysql_src / "test.sql.gz").write_text("data")

        local_dest = tmp_path / "dest_mysql"
        local_dest.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            from lib.core.restore import _fetch_dump_subdir
            result = _fetch_dump_subdir(ctx, snap_dir, "2026-03-24T120000",
                                       "_mysql", str(local_dest))
            assert result is True

    def test_local_not_found(self, tmp_path):
        """Local dump subdir missing returns False."""
        ctx = _make_ctx(remote_type="local", base=str(tmp_path / "backups"))
        snap_dir = ctx.snap_dir

        local_dest = tmp_path / "dest_mysql2"
        local_dest.mkdir()

        from lib.core.restore import _fetch_dump_subdir
        result = _fetch_dump_subdir(ctx, snap_dir, "2026-03-24T120000",
                                   "_mysql", str(local_dest))
        assert result is False

    def test_ssh_success(self):
        """SSH dump subdir fetch succeeds."""
        ctx = _make_ctx(remote_type="ssh")
        snap_dir = ctx.snap_dir

        with patch("lib.core.restore._rsync_download", return_value=0):
            from lib.core.restore import _fetch_dump_subdir
            result = _fetch_dump_subdir(ctx, snap_dir, "2026-03-24T120000",
                                       "_mysql", "/tmp/test_dest")
            assert result is True


class TestHasDumpFiles:

    def test_has_sql_gz(self, tmp_path):
        """Directory with .sql.gz files returns True."""
        (tmp_path / "test.sql.gz").write_text("data")
        from lib.core.restore import _has_dump_files
        assert _has_dump_files(str(tmp_path), "*.sql.gz", "grants.sql") is True

    def test_has_alt_file(self, tmp_path):
        """Directory with alt file returns True."""
        (tmp_path / "grants.sql").write_text("data")
        from lib.core.restore import _has_dump_files
        assert _has_dump_files(str(tmp_path), "*.sql.gz", "grants.sql") is True

    def test_empty_dir(self, tmp_path):
        """Empty directory returns False."""
        from lib.core.restore import _has_dump_files
        assert _has_dump_files(str(tmp_path), "*.sql.gz", "grants.sql") is False


class TestRsyncDownload:

    def test_builds_correct_command(self):
        """_rsync_download builds correct rsync command."""
        ctx = _make_ctx(remote_type="ssh")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            from lib.core.restore import _rsync_download
            rc = _rsync_download(ctx, "/remote/path/", "/local/path/")
            assert rc == 0
            # Verify rsync was called
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "rsync"
            assert "-aHAX" in cmd
            assert "--numeric-ids" in cmd

    def test_failure_returns_nonzero(self):
        """_rsync_download returns non-zero on failure."""
        ctx = _make_ctx(remote_type="ssh")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            from lib.core.restore import _rsync_download
            rc = _rsync_download(ctx, "/remote/path/", "/local/path/")
            assert rc == 1
