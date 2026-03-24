"""flock-based per-target concurrency control."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Optional


class TargetLock:
    """Per-target lock using flock. Use as a context manager."""

    def __init__(self, target_name: str, work_dir: Path):
        self._lock_file = work_dir / ("gniza-lock-%s.lock" % target_name)
        self._fd = None  # type: Optional[int]

    def acquire(self, blocking: bool = False) -> bool:
        """Try to acquire the lock. Returns True if acquired."""
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(str(self._lock_file), os.O_CREAT | os.O_RDWR)
        try:
            flags = fcntl.LOCK_EX
            if not blocking:
                flags |= fcntl.LOCK_NB
            fcntl.flock(self._fd, flags)
            return True
        except OSError:
            os.close(self._fd)
            self._fd = None
            return False

    def release(self):
        """Release the lock."""
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Could not acquire lock for target (already running?)")
        return self

    def __exit__(self, *args):
        self.release()

    def __del__(self):
        self.release()
