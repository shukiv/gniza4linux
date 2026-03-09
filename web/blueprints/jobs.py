import time

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, Response,
)

from web.app import login_required
from web.jobs import web_job_manager

bp = Blueprint("jobs", __name__, url_prefix="/jobs")


def _build_job_progress(jobs):
    """Build a dict of job_id -> progress for all running jobs."""
    result = {}
    for job in jobs:
        if job.status == "running":
            prog = web_job_manager.get_progress(job.id)
            if prog:
                result[job.id] = prog
    return result


@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1
    jobs = web_job_manager.list_jobs()
    jobs.sort(key=lambda j: (0 if j.status == "running" else 1 if j.status == "queued" else 2, -j.started_at.timestamp()))
    has_running = any(j.status == "running" for j in jobs)
    has_queued = any(j.status == "queued" for j in jobs)
    total = len(jobs)
    per_page = 20
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    page_jobs = jobs[start:start + per_page]
    job_progress = _build_job_progress(page_jobs)
    return render_template("jobs/index.html", jobs=page_jobs, has_running=has_running,
                           has_queued=has_queued, page=page, total_pages=total_pages,
                           job_progress=job_progress)


@bp.route("/table")
@login_required
def table():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1
    jobs = web_job_manager.list_jobs()
    jobs.sort(key=lambda j: (0 if j.status == "running" else 1, -j.started_at.timestamp()))
    has_running = any(j.status == "running" for j in jobs)
    has_queued = any(j.status == "queued" for j in jobs)
    total = len(jobs)
    per_page = 20
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    page_jobs = jobs[start:start + per_page]
    job_progress = _build_job_progress(page_jobs)
    return render_template("jobs/table_partial.html", jobs=page_jobs, has_running=has_running,
                           has_queued=has_queued, page=page, total_pages=total_pages,
                           job_progress=job_progress)


@bp.route("/running-badge")
@login_required
def running_badge():
    count = web_job_manager.running_count()
    queued = sum(1 for j in web_job_manager.list_jobs() if j.status == "queued")
    return render_template("jobs/running_badge.html", count=count, queued=queued)


@bp.route("/sidebar-badge")
@login_required
def sidebar_badge():
    count = web_job_manager.running_count()
    return render_template("jobs/sidebar_badge.html", count=count)


@bp.route("/<job_id>/viewer")
@login_required
def viewer(job_id):
    job = web_job_manager.get_job(job_id)
    if not job:
        return '<span class="text-error">Job not found</span>'
    return render_template("jobs/viewer_partial.html", job=job)


@bp.route("/<job_id>/log")
@login_required
def log(job_id):
    lines, total = web_job_manager.get_log_lines(job_id)
    job = web_job_manager.get_job(job_id)
    return render_template("jobs/log_partial.html", lines=lines, total=total, job=job)


@bp.route("/<job_id>/progress")
@login_required
def progress(job_id):
    job = web_job_manager.get_job(job_id)
    prog = web_job_manager.get_progress(job_id) if job and job.status == "running" else None
    return render_template("jobs/progress_partial.html", progress=prog)


@bp.route("/<job_id>/stream")
@login_required
def stream(job_id):
    def generate():
        while True:
            lines, total = web_job_manager.get_log_lines(job_id)
            for line in lines:
                yield f"data: {line}\n\n"
            job = web_job_manager.get_job(job_id)
            if not job:
                yield f"event: done\ndata: not_found\n\n"
                break
            if job.status != "running":
                yield f"event: done\ndata: {job.status}\n\n"
                break
            time.sleep(1)
    return Response(generate(), mimetype="text/event-stream")


@bp.route("/<job_id>/kill", methods=["POST"])
@login_required
def kill(job_id):
    result = web_job_manager.kill_job(job_id)
    if result in ("killed", "cancelled"):
        flash("Job killed.", "success")
    else:
        flash(f"Could not kill job: {result}", "error")
    return redirect(url_for("jobs.index"))


@bp.route("/clear", methods=["POST"])
@login_required
def clear():
    web_job_manager.remove_finished()
    flash("Finished jobs cleared.", "success")
    return redirect(url_for("jobs.index"))
