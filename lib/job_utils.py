"""Shared job utilities for TUI, web, and daemon."""
from pathlib import Path


def _read_log_tail(log_file, tail_bytes=8192):
    """Read the tail of a log file efficiently.
    Returns the text content, or None if the file cannot be read.
    """
    try:
        path = Path(log_file) if not isinstance(log_file, Path) else log_file
        if not path.is_file():
            return None
        size = path.stat().st_size
        with open(path, 'r', errors='replace') as f:
            if size > tail_bytes:
                f.seek(size - tail_bytes)
                f.readline()  # skip partial line
            return f.read()
    except OSError:
        return None


def detect_return_code(log_file):
    """Try to determine exit code from log file content.
    Returns 0 for success, 1 for detected failure, None if unknown.
    """
    if not log_file:
        return None
    text = _read_log_tail(log_file)
    if text is None or not text.strip():
        return None
    try:
        if "Backup completed" in text:
            return 0
        if "Backup Summary" in text:
            # Check if any failures reported in the summary
            import re
            for line in text.splitlines():
                if "Failed:" in line:
                    m = re.search(r'Failed:\s*(\d+)', line)
                    if m and int(m.group(1)) > 0:
                        return 1
            return 0
        for line in text.splitlines():
            if "[FATAL]" in line or "[ERROR]" in line:
                return 1
        return None
    except OSError:
        return None


def is_skipped_job(log_file_or_output):
    """Check if all targets were skipped (disabled).
    Accepts either a file path (str) or list of output lines.
    """
    if isinstance(log_file_or_output, list):
        text = "\n".join(log_file_or_output)
    elif isinstance(log_file_or_output, str):
        text = _read_log_tail(log_file_or_output)
        if text is None:
            return False
    else:
        return False
    skip_markers = ("is disabled, skipping",
                    "nothing to do")
    active_markers = ("Backup completed", "Backup Summary", "Transferring",
                      "End transfer details", "dumps completed",
                      "Total bytes sent:", "Number of files:")
    return (any(m in text for m in skip_markers)
            and not any(m in text for m in active_markers))
