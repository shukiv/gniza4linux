from pathlib import Path

from flask import (
    Blueprint, render_template, request, abort, redirect, url_for, flash,
    send_file,
)

from web.app import login_required
from web.jobs import web_job_manager
from tui.config import LOG_DIR

bp = Blueprint("logs", __name__, url_prefix="/logs")

LOGS_PER_PAGE = 20
VIEW_LINES = 500


def _safe_log_path(job):
    """Validate log_file is within LOG_DIR. Returns Path or None."""
    if not job or not job.log_file:
        return None
    try:
        p = Path(job.log_file).resolve()
        if not str(p).startswith(str(LOG_DIR.resolve())):
            return None
        return p
    except (OSError, ValueError):
        return None


@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    all_jobs = web_job_manager.list_jobs()
    finished = [j for j in all_jobs if j.status not in ("running", "queued")]
    finished.sort(key=lambda j: j.finished_at or j.started_at, reverse=True)

    total = len(finished)
    total_pages = max(1, (total + LOGS_PER_PAGE - 1) // LOGS_PER_PAGE)
    page = min(page, total_pages)
    start = (page - 1) * LOGS_PER_PAGE
    end = start + LOGS_PER_PAGE
    page_jobs = finished[start:end]

    # Build log file sizes
    log_sizes = {}
    for job in page_jobs:
        if job.log_file:
            try:
                log_sizes[job.id] = Path(job.log_file).stat().st_size
            except OSError:
                pass

    return render_template(
        "logs/index.html",
        jobs=page_jobs,
        page=page,
        total_pages=total_pages,
        log_sizes=log_sizes,
    )


@bp.route("/clear", methods=["POST"])
@login_required
def clear():
    """Clear finished job entries and delete their log files."""
    all_jobs = web_job_manager.list_jobs()
    deleted = 0
    for job in all_jobs:
        if job.status not in ("running", "queued"):
            log_path = _safe_log_path(job)
            if not log_path:
                continue
            try:
                if log_path.is_file():
                    log_path.unlink()
                    deleted += 1
            except OSError:
                pass
    web_job_manager.remove_finished()
    flash(f"Cleared finished jobs and deleted {deleted} log files", "success")
    return redirect(url_for("logs.index"))


@bp.route("/<job_id>")
@login_required
def view(job_id):
    job = web_job_manager.get_job(job_id)
    log_path = _safe_log_path(job)
    if not log_path:
        abort(404)

    offset = request.args.get("offset", 0, type=int)

    try:
        if not log_path.is_file():
            abort(404)
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
        job=job,
        lines=lines,
        start=start,
        end=end,
        total_lines=total_lines,
        view_lines=VIEW_LINES,
    )


@bp.route("/<job_id>/download")
@login_required
def download(job_id):
    job = web_job_manager.get_job(job_id)
    log_path = _safe_log_path(job)
    if not log_path or not log_path.is_file():
        abort(404)

    return send_file(
        log_path,
        mimetype="text/plain",
        as_attachment=True,
        download_name=log_path.name,
    )
