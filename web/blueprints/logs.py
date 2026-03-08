import re
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint, render_template, request, abort, redirect, url_for, flash,
)

from tui.config import LOG_DIR
from web.app import login_required
from web.jobs import web_job_manager

bp = Blueprint("logs", __name__, url_prefix="/logs")

LOGS_PER_PAGE = 20
VIEW_LINES = 500

_SAFE_FILENAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)

_LOG_FILENAME_RE = re.compile(r'^gniza-(\d{8})-(\d{6})\.log$')


def _is_safe_filename(name):
    return all(c in _SAFE_FILENAME_CHARS for c in name) and ".." not in name


def _parse_log_filename(name):
    m = _LOG_FILENAME_RE.match(name)
    if not m:
        return None, None
    date_str = m.group(1)
    time_str = m.group(2)
    date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    time = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
    return date, time


def _has_running_jobs():
    """Check if any jobs are currently running."""
    try:
        return web_job_manager.running_count() > 0
    except Exception:
        return False


def _detect_status(filepath, has_running=False):
    try:
        stat = filepath.stat()
        size = stat.st_size
        if size == 0:
            return "Empty"
        read_size = min(size, 102400)
        with open(filepath, "rb") as f:
            if size > read_size:
                f.seek(size - read_size)
            tail = f.read(read_size).decode("utf-8", errors="replace")
    except OSError:
        return "Interrupted"

    has_error = "[ERROR]" in tail or "[FATAL]" in tail
    has_completed = "Backup completed" in tail or "Restore completed" in tail

    if has_completed and not has_error:
        return "Success"
    if has_error:
        return "Failed"
    if "Lock released" in tail:
        return "OK"
    if "is disabled, skipping" in tail:
        return "Skipped"

    # If jobs are running and file was modified in the last 5 minutes, it's likely in progress
    if has_running:
        import time
        if time.time() - stat.st_mtime < 300:
            return "Running"

    return "Interrupted"


@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    log_path = Path(LOG_DIR)
    has_running = _has_running_jobs()
    log_files = []
    if log_path.is_dir():
        for f in log_path.iterdir():
            if f.is_file() and _LOG_FILENAME_RE.match(f.name):
                stat = f.stat()
                date, time = _parse_log_filename(f.name)
                status = _detect_status(f, has_running)
                log_files.append({
                    "name": f.name,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime),
                    "date": date,
                    "time": time,
                    "status": status,
                })
    log_files.sort(key=lambda x: x["mtime"], reverse=True)

    total = len(log_files)
    total_pages = max(1, (total + LOGS_PER_PAGE - 1) // LOGS_PER_PAGE)
    page = min(page, total_pages)
    start = (page - 1) * LOGS_PER_PAGE
    end = start + LOGS_PER_PAGE
    page_files = log_files[start:end]

    return render_template(
        "logs/index.html",
        log_files=page_files,
        page=page,
        total_pages=total_pages,
    )


@bp.route("/clear", methods=["POST"])
@login_required
def clear():
    log_path = Path(LOG_DIR)
    removed = 0
    if log_path.is_dir():
        for f in log_path.iterdir():
            if f.is_file() and _LOG_FILENAME_RE.match(f.name):
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
    flash(f"Cleared {removed} log file(s)", "success")
    return redirect(url_for("logs.index"))


@bp.route("/<filename>")
@login_required
def view(filename):
    if not _is_safe_filename(filename):
        abort(400)

    log_path = Path(LOG_DIR) / filename
    if not log_path.is_file():
        abort(404)

    offset = request.args.get("offset", 0, type=int)

    try:
        with open(log_path) as f:
            all_lines = f.readlines()
    except OSError:
        abort(500)

    total_lines = len(all_lines)

    if offset == 0:
        start = max(0, total_lines - VIEW_LINES)
    else:
        start = max(0, offset)

    end = min(start + VIEW_LINES, total_lines)
    lines = [l.rstrip("\n") for l in all_lines[start:end]]

    return render_template(
        "logs/view.html",
        filename=filename,
        lines=lines,
        start=start,
        end=end,
        total_lines=total_lines,
        view_lines=VIEW_LINES,
    )
