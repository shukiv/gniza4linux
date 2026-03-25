# Plan: Integration Tests for Python Backup Core

> Source PRD: https://github.com/shukiv/gniza4linux/issues/7

## Architectural decisions

- **Test file**: `tests/test_integration.py` — single file, marked with `@pytest.mark.integration`
- **Fixture**: `real_backup_env` creates temp source files, temp config, temp destination per test
- **Remote type**: All tests use `REMOTE_TYPE=local` — no SSH, no network
- **Patches**: Only `CONFIG_DIR`, `WORK_DIR`, `LOG_DIR`, `socket.gethostname()` — everything else runs real
- **Requires**: `rsync` binary (skip gracefully if not found)
- **Source data**: Small set of files (~10 files, subdirs, ~1KB each) for speed
- **Hostname**: Patched to `testhost` for predictable snapshot paths
- **Snapshot path**: `{tmp_path}/backups/testhost/targets/{name}/snapshots/{timestamp}/`

---

## Phase 1: Tracer bullet — single backup, files on disk

**User stories**: 1, 4, 5, 9

### What to build

One integration test that creates source files, runs `backup_target()` with a local remote, and verifies the complete snapshot directory structure on disk. This proves the entire pipeline works end-to-end: config loading, context creation, rsync transfer, `.partial` rename, `latest` symlink, and `meta.json` generation.

### Acceptance criteria

- [ ] Test creates source files in a temp directory
- [ ] `backup_target()` returns 0 (success)
- [ ] Snapshot directory exists at expected path (no `.partial` suffix)
- [ ] Source files are present in the snapshot with correct content
- [ ] `meta.json` exists with correct target name, hostname, and status
- [ ] `latest` symlink points to the snapshot directory
- [ ] Test runs in under 2 seconds

---

## Phase 2: Incremental backup — hardlink dedup

**User stories**: 2, 8

### What to build

Run two backups in sequence. First backup creates the initial snapshot. Second backup (with no file changes) should use `--link-dest` to create hardlinks instead of copying. Then modify one file and run a third backup — only the changed file should be a new copy, unchanged files should be hardlinks to the second snapshot.

### Acceptance criteria

- [ ] First backup creates snapshot with all files
- [ ] Second backup creates new snapshot; unchanged files are hardlinks to first (same inode)
- [ ] After modifying one source file, third backup has a new copy of that file (different inode) but hardlinks for unchanged files
- [ ] Disk usage of second snapshot is near-zero (hardlinks don't use extra space)

---

## Phase 3: Retention — delete old snapshots on disk

**User stories**: 3

### What to build

Run multiple backups to create several snapshots, then call `enforce_retention()` with a keep count lower than the snapshot count. Verify that old snapshots are physically deleted from disk and only the expected number remain.

### Acceptance criteria

- [ ] Create 4 snapshots via sequential backups
- [ ] Call `enforce_retention()` with keep=2
- [ ] Only 2 newest snapshots remain on disk
- [ ] Deleted snapshot directories are gone (not just renamed)
- [ ] `latest` symlink still points to the newest snapshot

---

## Phase 4: Restore round-trip — backup then restore

**User stories**: 6, 14

### What to build

Run a backup, then restore to a custom directory. Verify the restored files are identical to the originals. Also test folder-level restore — restore only one subdirectory and verify only that folder's files appear.

### Acceptance criteria

- [ ] Full restore: all files in custom destination match originals (same content, same relative paths)
- [ ] Folder restore: only the specified folder's files appear in the custom destination
- [ ] Restored file contents are byte-identical to originals

---

## Phase 5: Error handling — no snapshot on failure

**User stories**: 12, 13

### What to build

Test that when the source directory doesn't exist, `backup_target()` returns non-zero and no snapshot directory (or `.partial`) is left on disk. Also test the lock mechanism — start a backup, try to start another for the same target concurrently, verify the second returns code 2 (lock conflict).

### Acceptance criteria

- [ ] Missing source directory: `backup_target()` returns non-zero
- [ ] No snapshot or `.partial` directory created for failed backup
- [ ] Lock conflict: second concurrent backup returns 2
- [ ] First backup completes successfully despite the second's attempt

---

## Phase 6: Filters — include/exclude

**User stories**: 7

### What to build

Configure a target with exclude patterns (e.g., `*.log`, `cache/`). Run a backup and verify that excluded files are NOT present in the snapshot while included files are.

### Acceptance criteria

- [ ] Source has both included and excluded files
- [ ] Snapshot contains only non-excluded files
- [ ] Excluded files (matching pattern) are absent from snapshot
- [ ] Excluded directories are absent from snapshot
