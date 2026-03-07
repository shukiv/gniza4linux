import os
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint, render_template, request, abort,
)

from tui.config import LOG_DIR
from web.app import login_required

bp = Blueprint("logs", __name__, url_prefix="/logs")

LOGS_PER_PAGE = 20
VIEW_LINES = 500

_SAFE_FILENAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


def _is_safe_filename(name):
    return all(c in _SAFE_FILENAME_CHARS for c in name) and ".." not in name


@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    log_path = Path(LOG_DIR)
    log_files = []
    if log_path.is_dir():
        for f in log_path.iterdir():
            if f.is_file():
                stat = f.stat()
                log_files.append({
                    "name": f.name,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime),
                })
    log_files.sort(key=lambda x: x["mtime"], reverse=True)

    total = len(log_files)
    total_pages = max(1, (total + LOGS_PER_PAGE - 1) // LOGS_PER_PAGE)
    start = (page - 1) * LOGS_PER_PAGE
    end = start + LOGS_PER_PAGE
    page_files = log_files[start:end]

    return render_template(
        "logs/index.html",
        log_files=page_files,
        page=page,
        total_pages=total_pages,
    )


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
