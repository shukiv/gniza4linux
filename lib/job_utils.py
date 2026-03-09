"""Shared job utilities for TUI, web, and daemon."""
from pathlib import Path


def detect_return_code(log_file):
    """Try to determine exit code from log file content.
    Returns 0 for success, 1 for detected failure, None if unknown.
    """
    if not log_file or not Path(log_file).is_file():
        return None
    try:
        text = Path(log_file).read_text()
        if not text.strip():
            return None
        if "Backup completed" in text or "Backup Summary" in text:
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
        if not Path(log_file_or_output).is_file():
            return False
        try:
            text = Path(log_file_or_output).read_text()
        except OSError:
            return False
    else:
        return False
    skip_markers = ("is disabled, skipping",
                    "previous backup still running",
                    "nothing to do")
    return (any(m in text for m in skip_markers)
            and "Backup completed" not in text
            and "Backup Summary" not in text)
