from datetime import datetime, timedelta

from flask import Blueprint, render_template, flash, request, redirect, url_for

from tui.config import CONFIG_DIR, parse_conf, list_conf_dir
from tui.models import Schedule
from web.app import login_required
from web.helpers import load_targets, load_remotes
from web.jobs import web_job_manager

DASH_LOGS_PER_PAGE = 10

bp = Blueprint("dashboard", __name__)


def _load_schedules():
    schedules = []
    for name in list_conf_dir("schedules.d"):
        data = parse_conf(CONFIG_DIR / "schedules.d" / f"{name}.conf")
        schedules.append(Schedule.from_conf(name, data))
    return schedules


def _count_errors_past_month():
    cutoff = datetime.now() - timedelta(days=30)
    count = 0
    for j in web_job_manager.list_jobs():
        if j.status in ("running", "queued"):
            continue
        if j.finished_at and j.finished_at >= cutoff and j.status == "failed":
            count += 1
    return count


def _load_finished_jobs(page=1):
    all_jobs = web_job_manager.list_jobs()
    finished = [j for j in all_jobs if j.status not in ("running", "queued")]
    finished.sort(key=lambda j: j.finished_at or j.started_at, reverse=True)
    total = len(finished)
    total_pages = max(1, (total + DASH_LOGS_PER_PAGE - 1) // DASH_LOGS_PER_PAGE)
    page = min(page, total_pages)
    start = (page - 1) * DASH_LOGS_PER_PAGE
    return finished[start:start + DASH_LOGS_PER_PAGE], page, total_pages


@bp.route("/")
@login_required
def index():
    if not list_conf_dir("remotes.d") and not list_conf_dir("targets.d"):
        return redirect(url_for("wizard.index"))
    targets, remotes, schedules = [], [], []
    log_files, log_page, log_total_pages = [], 1, 1
    try:
        targets = load_targets()
    except Exception:
        flash("Failed to load sources.", "error")
    try:
        remotes = load_remotes()
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
        recent_jobs, log_page, log_total_pages = _load_finished_jobs(page)
    except Exception:
        recent_jobs, log_page, log_total_pages = [], 1, 1
    errors_past_month = 0
    try:
        errors_past_month = _count_errors_past_month()
    except Exception:
        pass
    return render_template(
        "dashboard/index.html",
        targets=targets,
        remotes=remotes,
        schedules=schedules,
        recent_jobs=recent_jobs,
        log_page=log_page,
        log_total_pages=log_total_pages,
        errors_past_month=errors_past_month,
    )
