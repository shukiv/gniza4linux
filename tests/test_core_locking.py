"""Tests for lib.core.locking — flock-based per-target concurrency control."""
import pytest
from pathlib import Path
from lib.core.locking import TargetLock


class TestTargetLock:
    def test_acquire_and_release(self, tmp_path):
        lock = TargetLock("test-target", tmp_path)
        assert lock.acquire() is True
        lock.release()

    def test_double_acquire_fails(self, tmp_path):
        lock1 = TargetLock("test-target", tmp_path)
        lock2 = TargetLock("test-target", tmp_path)
        assert lock1.acquire() is True
        assert lock2.acquire() is False
        lock1.release()

    def test_acquire_after_release(self, tmp_path):
        lock1 = TargetLock("test-target", tmp_path)
        assert lock1.acquire() is True
        lock1.release()

        lock2 = TargetLock("test-target", tmp_path)
        assert lock2.acquire() is True
        lock2.release()

    def test_different_targets_no_conflict(self, tmp_path):
        lock1 = TargetLock("target-a", tmp_path)
        lock2 = TargetLock("target-b", tmp_path)
        assert lock1.acquire() is True
        assert lock2.acquire() is True
        lock1.release()
        lock2.release()

    def test_context_manager(self, tmp_path):
        with TargetLock("test-target", tmp_path) as lock:
            assert lock is not None
        # After exiting, the lock should be released
        lock2 = TargetLock("test-target", tmp_path)
        assert lock2.acquire() is True
        lock2.release()

    def test_context_manager_raises_on_conflict(self, tmp_path):
        lock1 = TargetLock("test-target", tmp_path)
        assert lock1.acquire() is True
        with pytest.raises(RuntimeError, match="Could not acquire lock"):
            with TargetLock("test-target", tmp_path):
                pass
        lock1.release()

    def test_creates_lock_file(self, tmp_path):
        lock = TargetLock("mylock", tmp_path)
        lock.acquire()
        assert (tmp_path / "gniza-lock-mylock.lock").exists()
        lock.release()

    def test_release_idempotent(self, tmp_path):
        lock = TargetLock("test-target", tmp_path)
        lock.acquire()
        lock.release()
        lock.release()  # should not raise
