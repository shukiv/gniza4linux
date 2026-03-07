from flask import Blueprint, render_template

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
    lines = latest.read_text(errors="replace").splitlines()
    last_lines = lines[-50:] if len(lines) > 50 else lines
    status = "unknown"
    for line in reversed(lines):
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
    targets = _load_targets()
    remotes = _load_remotes()
    schedules = _load_schedules()
    last_log = _last_log_info()
    return render_template(
        "dashboard.html",
        targets=targets,
        remotes=remotes,
        schedules=schedules,
        last_log=last_log,
    )
