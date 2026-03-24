"""Pure utility functions for the backup core."""
from __future__ import annotations

import re
import socket
from datetime import datetime

_VALID_TS_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{6}$')


def make_timestamp() -> str:
    """Generate a backup timestamp: YYYY-MM-DDTHHMMSS."""
    return datetime.now().strftime("%Y-%m-%dT%H%M%S")


def human_size(size_bytes: int | float) -> str:
    """Format bytes as human-readable string."""
    if size_bytes < 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024.0:
            if unit == "B":
                return "%d %s" % (int(size_bytes), unit)
            return "%.1f %s" % (size_bytes, unit)
        size_bytes /= 1024.0
    return "%.1f PB" % size_bytes


def human_duration(seconds: int | float) -> str:
    """Format seconds as Xh Ym Zs."""
    seconds = int(seconds)
    if seconds < 0:
        return "0s"
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    parts = []
    if h:
        parts.append("%dh" % h)
        parts.append("%dm" % m)
    elif m:
        parts.append("%dm" % m)
    parts.append("%ds" % s)
    return " ".join(parts)


def validate_timestamp(ts: str) -> bool:
    """Check if a timestamp matches YYYY-MM-DDTHHMMSS format."""
    return bool(_VALID_TS_RE.match(ts))


def get_hostname() -> str:
    """Get the system hostname."""
    return socket.gethostname()


def shquote(s: str) -> str:
    """Shell-quote a string (for embedding in remote SSH commands)."""
    import shlex
    return shlex.quote(s)
