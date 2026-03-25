"""Integration tests -- real rsync, real filesystem, no mocks.

These tests verify the Python backup core works end-to-end against
real rsync transfers on a local filesystem. Every test creates its
own isolated temp environment.

Run: pytest tests/test_integration.py -v
Run only these: pytest -m integration
"""
import json
import os
import shutil
import time

import pytest
from pathlib import Path
from unittest.mock import patch


# Skip entire module if rsync is not available
rsync_path = shutil.which("rsync")
if not rsync_path:
    pytest.skip("rsync not found", allow_module_level=True)

pytestmark = pytest.mark.integration


@pytest.fixture
def real_backup_env(tmp_path):
    """Create a complete, isolated backup environment with real files.

    Creates:
    - Source directory with test files
    - Config directory with target + remote configs
    - Backup destination directory
    - Work directory for locks
    - Log directory

    Patches CONFIG_DIR, WORK_DIR, LOG_DIR, and ssh global defaults cache.
    """
    # Source files
    src = tmp_path / "source"
    src.mkdir()
    (src / "etc").mkdir()
    (src / "etc" / "hosts").write_text("127.0.0.1 localhost\n")
    (src / "etc" / "resolv.conf").write_text("nameserver 8.8.8.8\n")
    (src / "etc" / "subdir").mkdir()
    (src / "etc" / "subdir" / "nested.conf").write_text("key=value\n")
    (src / "home").mkdir()
    (src / "home" / "user1").mkdir()
    (src / "home" / "user1" / "file.txt").write_text("hello world\n")
    (src / "home" / "user1" / "data.bin").write_bytes(b"\x00\x01\x02" * 100)

    # Config
    conf = tmp_path / "config"
    conf.mkdir()
    (conf / "targets.d").mkdir()
    (conf / "remotes.d").mkdir()
    (conf / "schedules.d").mkdir()

    # gniza.conf
    (conf / "gniza.conf").write_text(
        'RETENTION_COUNT="30"\n'
        'DISK_USAGE_THRESHOLD="0"\n'
        'LOG_LEVEL="info"\n'
    )

    # Target config -- folders point to our source dirs
    (conf / "targets.d" / "testsite.conf").write_text(
        'TARGET_FOLDERS="%s/etc,%s/home"\n' % (src, src)
        + 'TARGET_ENABLED="yes"\n'
        + 'TARGET_SOURCE_TYPE="local"\n'
    )

    # Remote config -- local type, destination in tmp
    backups = tmp_path / "backups"
    backups.mkdir()
    (conf / "remotes.d" / "local.conf").write_text(
        'REMOTE_TYPE="local"\n'
        'REMOTE_BASE="%s"\n' % backups
    )

    # Work and log dirs
    work = tmp_path / "work"
    work.mkdir()
    log = tmp_path / "log"
    log.mkdir()

    # Patch config module globals
    import lib.config
    orig_conf = lib.config.CONFIG_DIR
    orig_work = lib.config.WORK_DIR
    orig_log = lib.config.LOG_DIR

    lib.config.CONFIG_DIR = conf
    lib.config.WORK_DIR = work
    lib.config.LOG_DIR = log

    # Clear config caches
    lib.config._conf_dir_cache.clear()

    # Clear SSH global defaults cache so it re-reads from our temp config
    import lib.ssh
    orig_ssh_defaults = lib.ssh._global_defaults
    lib.ssh._global_defaults = None

    # Clear logger handlers to avoid duplicate output
    import logging
    logger = logging.getLogger("gniza")
    logger.handlers.clear()

    yield {
        "src": src,
        "conf": conf,
        "backups": backups,
        "work": work,
        "log": log,
        "tmp_path": tmp_path,
    }

    lib.config.CONFIG_DIR = orig_conf
    lib.config.WORK_DIR = orig_work
    lib.config.LOG_DIR = orig_log
    lib.config._conf_dir_cache.clear()
    lib.ssh._global_defaults = orig_ssh_defaults


def _find_snapshots(backups_dir, target_name="testsite", hostname="testhost"):
    """Return sorted list of completed snapshot directories (no .partial)."""
    snap_base = backups_dir / hostname / "targets" / target_name / "snapshots"
    if not snap_base.exists():
        return []
    return sorted(
        [d for d in snap_base.iterdir() if d.is_dir() and not d.name.endswith(".partial")],
        key=lambda d: d.name,
    )


def _find_file_in_snapshot(snap_dir, src_dir, rel_file):
    """Locate a source file inside a snapshot.

    Snapshot layout mirrors the absolute source path minus the leading '/'.
    For example, source /tmp/xxx/source/etc/hosts becomes:
        {snap_dir}/{tmp_xxx_source}/etc/hosts
    """
    # The rel_path used by backup is folder.lstrip("/"), so for
    # /tmp/xxx/source/etc the snapshot subdirectory is tmp/xxx/source/etc
    full_path = str(src_dir / rel_file).lstrip("/")
    return snap_dir / full_path


# =====================================================================
# Phase 1: Single backup, verify files on disk
# =====================================================================

class TestSingleBackup:
    """Phase 1: Complete backup creates correct snapshot structure."""

    @patch("socket.gethostname", return_value="testhost")
    def test_backup_creates_snapshot_with_files(self, mock_host, real_backup_env):
        from lib.core.backup import backup_target

        rc = backup_target("testsite", "local")
        assert rc == 0

        snapshots = _find_snapshots(real_backup_env["backups"])
        assert len(snapshots) == 1

        snap = snapshots[0]
        hosts_file = _find_file_in_snapshot(snap, real_backup_env["src"], "etc/hosts")
        assert hosts_file.exists()
        assert hosts_file.read_text() == "127.0.0.1 localhost\n"

        nested = _find_file_in_snapshot(snap, real_backup_env["src"], "etc/subdir/nested.conf")
        assert nested.exists()
        assert nested.read_text() == "key=value\n"

        user_file = _find_file_in_snapshot(snap, real_backup_env["src"], "home/user1/file.txt")
        assert user_file.exists()
        assert user_file.read_text() == "hello world\n"

        data_file = _find_file_in_snapshot(snap, real_backup_env["src"], "home/user1/data.bin")
        assert data_file.exists()
        assert data_file.read_bytes() == b"\x00\x01\x02" * 100

    @patch("socket.gethostname", return_value="testhost")
    def test_meta_json_written(self, mock_host, real_backup_env):
        from lib.core.backup import backup_target

        backup_target("testsite", "local")

        snapshots = _find_snapshots(real_backup_env["backups"])
        assert len(snapshots) == 1

        meta_path = snapshots[0] / "meta.json"
        assert meta_path.exists()

        meta = json.loads(meta_path.read_text())
        assert meta["target"] == "testsite"
        assert meta["hostname"] == "testhost"
        assert meta["pinned"] is False
        assert isinstance(meta["duration"], int)
        assert meta["duration"] >= 0

    @patch("socket.gethostname", return_value="testhost")
    def test_latest_symlink(self, mock_host, real_backup_env):
        from lib.core.backup import backup_target

        backup_target("testsite", "local")

        latest = (
            real_backup_env["backups"] / "testhost" / "targets" / "testsite" / "latest"
        )
        assert latest.is_symlink()
        # The symlink target should resolve to the snapshot directory
        assert latest.resolve().is_dir()

    @patch("socket.gethostname", return_value="testhost")
    def test_no_partial_remains(self, mock_host, real_backup_env):
        from lib.core.backup import backup_target

        backup_target("testsite", "local")

        snap_base = (
            real_backup_env["backups"] / "testhost" / "targets" / "testsite" / "snapshots"
        )
        partials = [d for d in snap_base.iterdir() if d.name.endswith(".partial")]
        assert len(partials) == 0


# =====================================================================
# Phase 2: Incremental backup with hardlinks
# =====================================================================

class TestIncrementalBackup:
    """Phase 2: Second backup uses hardlinks for unchanged files."""

    @patch("socket.gethostname", return_value="testhost")
    def test_unchanged_files_are_hardlinked(self, mock_host, real_backup_env):
        from lib.core.backup import backup_target

        backup_target("testsite", "local")
        time.sleep(1)  # Ensure different timestamp
        backup_target("testsite", "local")

        snapshots = _find_snapshots(real_backup_env["backups"])
        assert len(snapshots) == 2

        snap1, snap2 = snapshots[0], snapshots[1]

        # Same file in both snapshots should have same inode (hardlinked)
        hosts1 = _find_file_in_snapshot(snap1, real_backup_env["src"], "etc/hosts")
        hosts2 = _find_file_in_snapshot(snap2, real_backup_env["src"], "etc/hosts")
        assert hosts1.exists() and hosts2.exists()
        assert os.stat(hosts1).st_ino == os.stat(hosts2).st_ino

        data1 = _find_file_in_snapshot(snap1, real_backup_env["src"], "home/user1/data.bin")
        data2 = _find_file_in_snapshot(snap2, real_backup_env["src"], "home/user1/data.bin")
        assert os.stat(data1).st_ino == os.stat(data2).st_ino

    @patch("socket.gethostname", return_value="testhost")
    def test_changed_file_is_new_copy(self, mock_host, real_backup_env):
        from lib.core.backup import backup_target

        backup_target("testsite", "local")

        # Modify a file
        (real_backup_env["src"] / "etc" / "hosts").write_text("modified content\n")
        time.sleep(1)
        backup_target("testsite", "local")

        snapshots = _find_snapshots(real_backup_env["backups"])
        assert len(snapshots) == 2

        snap1, snap2 = snapshots[0], snapshots[1]

        # Modified file should have different inode
        hosts1 = _find_file_in_snapshot(snap1, real_backup_env["src"], "etc/hosts")
        hosts2 = _find_file_in_snapshot(snap2, real_backup_env["src"], "etc/hosts")
        assert os.stat(hosts1).st_ino != os.stat(hosts2).st_ino
        assert hosts2.read_text() == "modified content\n"

        # Unchanged file should still be hardlinked
        nested1 = _find_file_in_snapshot(snap1, real_backup_env["src"], "etc/subdir/nested.conf")
        nested2 = _find_file_in_snapshot(snap2, real_backup_env["src"], "etc/subdir/nested.conf")
        assert os.stat(nested1).st_ino == os.stat(nested2).st_ino


# =====================================================================
# Phase 3: Retention
# =====================================================================

class TestRetention:
    """Phase 3: Old snapshots deleted from disk."""

    @patch("socket.gethostname", return_value="testhost")
    def test_retention_deletes_old_snapshots(self, mock_host, real_backup_env):
        from lib.core.backup import backup_target
        from lib.core.retention import enforce_retention
        from lib.core.context import BackupContext

        # Create 4 snapshots
        for _ in range(4):
            backup_target("testsite", "local")
            time.sleep(1)

        snapshots_before = _find_snapshots(real_backup_env["backups"])
        assert len(snapshots_before) == 4

        # Build a context to pass to enforce_retention
        ctx = BackupContext.create("testsite", "local")

        # Keep only 2
        pruned = enforce_retention(ctx, override_count=2)
        assert pruned == 2

        snapshots_after = _find_snapshots(real_backup_env["backups"])
        assert len(snapshots_after) == 2

        # The 2 newest should remain
        remaining_names = sorted([s.name for s in snapshots_after])
        all_names = sorted([s.name for s in snapshots_before])
        assert remaining_names == all_names[-2:]

    @patch("socket.gethostname", return_value="testhost")
    def test_retention_preserves_pinned(self, mock_host, real_backup_env):
        from lib.core.backup import backup_target
        from lib.core.retention import enforce_retention
        from lib.core.context import BackupContext

        # Create 3 snapshots
        for _ in range(3):
            backup_target("testsite", "local")
            time.sleep(1)

        snapshots = _find_snapshots(real_backup_env["backups"])
        assert len(snapshots) == 3

        # Pin the oldest snapshot
        oldest = snapshots[0]
        meta_path = oldest / "meta.json"
        meta = json.loads(meta_path.read_text())
        meta["pinned"] = True
        meta_path.write_text(json.dumps(meta, indent=2))

        ctx = BackupContext.create("testsite", "local")

        # Keep only 1 -- but the pinned one should survive
        pruned = enforce_retention(ctx, override_count=1)
        assert pruned == 1  # only 1 unpinned gets pruned (the 2nd oldest)

        remaining = _find_snapshots(real_backup_env["backups"])
        remaining_names = [s.name for s in remaining]
        # Pinned (oldest) + newest should remain
        assert oldest.name in remaining_names
        assert snapshots[-1].name in remaining_names


# =====================================================================
# Phase 4: Restore round-trip
# =====================================================================

class TestRestore:
    """Phase 4: Backup then restore produces identical files."""

    @patch("socket.gethostname", return_value="testhost")
    def test_full_restore_matches_original(self, mock_host, real_backup_env):
        from lib.core.backup import backup_target
        from lib.core.restore import restore_target

        backup_target("testsite", "local")

        # Restore to a custom directory
        restore_dest = real_backup_env["tmp_path"] / "restored"
        restore_dest.mkdir()

        rc = restore_target(
            "testsite", snapshot_ts="latest", remote_name="local",
            dest_dir=str(restore_dest),
        )
        assert rc == 0

        # The restore puts files under restore_dest/{rel_path_of_folder}/
        src = real_backup_env["src"]
        etc_rel = str(src / "etc").lstrip("/")
        home_rel = str(src / "home").lstrip("/")

        restored_hosts = restore_dest / etc_rel / "hosts"
        assert restored_hosts.exists()
        assert restored_hosts.read_text() == "127.0.0.1 localhost\n"

        restored_nested = restore_dest / etc_rel / "subdir" / "nested.conf"
        assert restored_nested.exists()
        assert restored_nested.read_text() == "key=value\n"

        restored_user = restore_dest / home_rel / "user1" / "file.txt"
        assert restored_user.exists()
        assert restored_user.read_text() == "hello world\n"

        restored_data = restore_dest / home_rel / "user1" / "data.bin"
        assert restored_data.exists()
        assert restored_data.read_bytes() == b"\x00\x01\x02" * 100

    @patch("socket.gethostname", return_value="testhost")
    def test_folder_restore(self, mock_host, real_backup_env):
        from lib.core.backup import backup_target
        from lib.core.restore import restore_folder

        backup_target("testsite", "local")

        # Restore only etc/ folder
        restore_dest = real_backup_env["tmp_path"] / "restored_folder"
        restore_dest.mkdir()

        src = real_backup_env["src"]
        etc_folder = str(src / "etc")

        rc = restore_folder(
            "testsite", folder_path=etc_folder,
            snapshot_ts="latest", remote_name="local",
            dest_dir=str(restore_dest),
        )
        assert rc == 0

        etc_rel = str(src / "etc").lstrip("/")
        restored_hosts = restore_dest / etc_rel / "hosts"
        assert restored_hosts.exists()
        assert restored_hosts.read_text() == "127.0.0.1 localhost\n"

        # home/ should not be present (only etc/ was restored)
        home_rel = str(src / "home").lstrip("/")
        assert not (restore_dest / home_rel).exists()


# =====================================================================
# Phase 5: Error handling
# =====================================================================

class TestErrorHandling:
    """Phase 5: Failures leave clean state."""

    @patch("socket.gethostname", return_value="testhost")
    def test_missing_source_produces_empty_snapshot(self, mock_host, real_backup_env):
        # rsync exit 23 (partial transfer / vanished source) is accepted as
        # success by design. Verify the backup completes but the snapshot
        # contains no user files (only meta.json).
        conf = real_backup_env["conf"]
        (conf / "targets.d" / "badtarget.conf").write_text(
            'TARGET_FOLDERS="/nonexistent/path/abc123"\n'
            'TARGET_ENABLED="yes"\n'
            'TARGET_SOURCE_TYPE="local"\n'
        )

        import lib.config
        lib.config._conf_dir_cache.clear()

        from lib.core.backup import backup_target
        rc = backup_target("badtarget", "local")
        # rsync 23 is treated as success (vanished/missing source files)
        assert rc == 0

        snapshots = _find_snapshots(real_backup_env["backups"], target_name="badtarget")
        assert len(snapshots) == 1

        # The snapshot should exist but contain only meta.json (no source data)
        snap = snapshots[0]
        all_files = list(snap.rglob("*"))
        real_files = [f for f in all_files if f.is_file() and f.name != "meta.json"]
        assert len(real_files) == 0

    @patch("socket.gethostname", return_value="testhost")
    def test_pre_hook_failure_prevents_backup(self, mock_host, real_backup_env):
        # Pre-hook failure should return 1 and leave no finalized snapshot
        conf = real_backup_env["conf"]
        (conf / "targets.d" / "hookfail.conf").write_text(
            'TARGET_FOLDERS="%s/etc"\n' % real_backup_env["src"]
            + 'TARGET_ENABLED="yes"\n'
            + 'TARGET_SOURCE_TYPE="local"\n'
            + 'TARGET_PRE_HOOK="exit 1"\n'
        )

        import lib.config
        lib.config._conf_dir_cache.clear()

        from lib.core.backup import backup_target
        rc = backup_target("hookfail", "local")
        assert rc == 1

        # No snapshot should exist
        snap_base = (
            real_backup_env["backups"] / "testhost" / "targets" / "hookfail" / "snapshots"
        )
        if snap_base.exists():
            completed = [
                d for d in snap_base.iterdir()
                if d.is_dir() and not d.name.endswith(".partial")
            ]
            assert len(completed) == 0

    @patch("socket.gethostname", return_value="testhost")
    def test_lock_conflict(self, mock_host, real_backup_env):
        from lib.core.locking import TargetLock
        from lib.core.backup import backup_target

        # Acquire lock manually, then try backup_target
        held_lock = TargetLock("testsite", real_backup_env["work"])
        assert held_lock.acquire()

        try:
            rc = backup_target("testsite", "local")
            assert rc == 2
        finally:
            held_lock.release()

    @patch("socket.gethostname", return_value="testhost")
    def test_missing_target_config(self, mock_host, real_backup_env):
        from lib.core.backup import backup_target
        rc = backup_target("nonexistent_target", "local")
        assert rc == 1

    @patch("socket.gethostname", return_value="testhost")
    def test_disabled_target_returns_0(self, mock_host, real_backup_env):
        conf = real_backup_env["conf"]
        (conf / "targets.d" / "disabled.conf").write_text(
            'TARGET_FOLDERS="%s/etc"\n' % real_backup_env["src"]
            + 'TARGET_ENABLED="no"\n'
            + 'TARGET_SOURCE_TYPE="local"\n'
        )

        import lib.config
        lib.config._conf_dir_cache.clear()

        from lib.core.backup import backup_target
        rc = backup_target("disabled", "local")
        assert rc == 0


# =====================================================================
# Phase 6: Exclude filters
# =====================================================================

class TestFilters:
    """Phase 6: Exclude patterns work correctly."""

    @patch("socket.gethostname", return_value="testhost")
    def test_exclude_pattern(self, mock_host, real_backup_env):
        src = real_backup_env["src"]

        # Add files that should be excluded
        (src / "etc" / "debug.log").write_text("log data\n")
        (src / "etc" / "cache").mkdir()
        (src / "etc" / "cache" / "temp.dat").write_text("cached\n")

        # Configure target with exclude patterns
        conf = real_backup_env["conf"]
        (conf / "targets.d" / "filtered.conf").write_text(
            'TARGET_FOLDERS="%s/etc"\n' % src
            + 'TARGET_ENABLED="yes"\n'
            + 'TARGET_SOURCE_TYPE="local"\n'
            + 'TARGET_EXCLUDE="*.log,cache/"\n'
        )

        import lib.config
        lib.config._conf_dir_cache.clear()

        from lib.core.backup import backup_target
        rc = backup_target("filtered", "local")
        assert rc == 0

        snapshots = _find_snapshots(real_backup_env["backups"], target_name="filtered")
        assert len(snapshots) == 1

        snap = snapshots[0]

        # Included file should be present
        hosts = _find_file_in_snapshot(snap, src, "etc/hosts")
        assert hosts.exists()

        # Excluded files should be absent
        log_file = _find_file_in_snapshot(snap, src, "etc/debug.log")
        assert not log_file.exists()

        cache_dir = _find_file_in_snapshot(snap, src, "etc/cache")
        assert not cache_dir.exists()
