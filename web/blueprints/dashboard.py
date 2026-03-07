from flask import Blueprint, render_template, flash

from tui.config import CONFIG_DIR, LOG_DIR, parse_conf, list_conf_dir
from tui.models import Target, Remote, Schedule
from web.app import login_required

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


def _last_log_info():
    if not LOG_DIR.is_dir():
        return None
    logs = sorted(
        LOG_DIR.glob("gniza-*.log"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    if not logs:
        return None
    latest = logs[0]
    from collections import deque
    with open(latest, errors="replace") as f:
        lines = deque(f, maxlen=200)
    lines = [l.rstrip("\n") for l in lines]
    last_lines = list(lines)[-50:]
    status = "unknown"
    for line in reversed(list(lines)):
        lower = line.lower()
        if "completed successfully" in lower or "backup done" in lower:
            status = "success"
            break
        if "error" in lower or "failed" in lower:
            status = "error"
            break
    return {
        "name": latest.name,
        "mtime": latest.stat().st_mtime,
        "status": status,
        "tail": "\n".join(last_lines),
    }


@bp.route("/")
@login_required
def index():
    targets, remotes, schedules, last_log = [], [], [], None
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
        last_log = _last_log_info()
    except Exception:
        pass
    return render_template(
        "dashboard/index.html",
        targets=targets,
        remotes=remotes,
        schedules=schedules,
        last_log=last_log,
    )
