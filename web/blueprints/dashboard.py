import re
from datetime import datetime
from pathlib import Path

from flask import Blueprint, render_template, flash, request

from tui.config import CONFIG_DIR, LOG_DIR, parse_conf, list_conf_dir
from tui.models import Target, Remote, Schedule
from web.app import login_required

_LOG_FILENAME_RE = re.compile(r'^gniza-(\d{8})-(\d{6})\.log$')
DASH_LOGS_PER_PAGE = 10

bp = Blueprint("dashboard", __name__)


def _load_targets():
    targets = []
    for name in list_conf_dir("targets.d"):
        data = parse_conf(CONFIG_DIR / "targets.d" / f"{name}.conf")
        targets.append(Target.from_conf(name, data))
    return targets


def _load_remotes():
    remotes = []
    for name in list_conf_dir("remotes.d"):
        data = parse_conf(CONFIG_DIR / "remotes.d" / f"{name}.conf")
        remotes.append(Remote.from_conf(name, data))
    return remotes


def _load_schedules():
    schedules = []
    for name in list_conf_dir("schedules.d"):
        data = parse_conf(CONFIG_DIR / "schedules.d" / f"{name}.conf")
        schedules.append(Schedule.from_conf(name, data))
    return schedules


def _detect_status(filepath):
    try:
        size = filepath.stat().st_size
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
    return "Interrupted"


def _load_logs(page=1):
    log_path = Path(LOG_DIR)
    log_files = []
    if log_path.is_dir():
        for f in log_path.iterdir():
            if f.is_file() and _LOG_FILENAME_RE.match(f.name):
                m = _LOG_FILENAME_RE.match(f.name)
                date_str, time_str = m.group(1), m.group(2)
                date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                time = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
                stat = f.stat()
                log_files.append({
                    "name": f.name,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime),
                    "date": date,
                    "time": time,
                    "status": _detect_status(f),
                })
    log_files.sort(key=lambda x: x["mtime"], reverse=True)
    total = len(log_files)
    total_pages = max(1, (total + DASH_LOGS_PER_PAGE - 1) // DASH_LOGS_PER_PAGE)
    start = (page - 1) * DASH_LOGS_PER_PAGE
    return log_files[start:start + DASH_LOGS_PER_PAGE], page, total_pages


@bp.route("/")
@login_required
def index():
    targets, remotes, schedules = [], [], []
    log_files, log_page, log_total_pages = [], 1, 1
    try:
        targets = _load_targets()
    except Exception:
        flash("Failed to load sources.", "error")
    try:
        remotes = _load_remotes()
    except Exception:
        flash("Failed to load destinations.", "error")
    try:
        schedules = _load_schedules()
    except Exception:
        flash("Failed to load schedules.", "error")
    try:
        page = request.args.get("log_page", 1, type=int)
        if page < 1:
            page = 1
        log_files, log_page, log_total_pages = _load_logs(page)
    except Exception:
        pass
    return render_template(
        "dashboard/index.html",
        targets=targets,
        remotes=remotes,
        schedules=schedules,
        log_files=log_files,
        log_page=log_page,
        log_total_pages=log_total_pages,
    )
