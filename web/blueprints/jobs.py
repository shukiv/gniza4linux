import time

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, Response,
)

from web.app import login_required
from web.jobs import web_job_manager

bp = Blueprint("jobs", __name__, url_prefix="/jobs")


@bp.route("/")
@login_required
def index():
    jobs = web_job_manager.list_jobs()
    # Sort: running first, then by started_at descending
    jobs.sort(key=lambda j: (j.status != "running", j.started_at), reverse=True)
    # Re-sort so running jobs appear first (reverse of the tuple sort)
    jobs.sort(key=lambda j: (0 if j.status == "running" else 1, -j.started_at.timestamp()))
    has_running = any(j.status == "running" for j in jobs)
    return render_template("jobs/index.html", jobs=jobs, has_running=has_running)


@bp.route("/table")
@login_required
def table():
    jobs = web_job_manager.list_jobs()
    jobs.sort(key=lambda j: (0 if j.status == "running" else 1, -j.started_at.timestamp()))
    has_running = any(j.status == "running" for j in jobs)
    return render_template("jobs/table_partial.html", jobs=jobs, has_running=has_running)


@bp.route("/running-badge")
@login_required
def running_badge():
    count = web_job_manager.running_count()
    return render_template("jobs/running_badge.html", count=count)


@bp.route("/<job_id>/log")
@login_required
def log(job_id):
    offset = request.args.get("offset", 0, type=int)
    lines, total = web_job_manager.get_log_lines(job_id, offset)
    job = web_job_manager.get_job(job_id)
    return render_template("jobs/log_partial.html", lines=lines, total=total, job=job)


@bp.route("/<job_id>/stream")
@login_required
def stream(job_id):
    def generate():
        offset = 0
        while True:
            lines, total = web_job_manager.get_log_lines(job_id, offset)
            for line in lines:
                yield f"data: {line}\n\n"
            offset = total
            job = web_job_manager.get_job(job_id)
            if job and job.status != "running":
                yield f"event: done\ndata: {job.status}\n\n"
                break
            time.sleep(1)
    return Response(generate(), mimetype="text/event-stream")


@bp.route("/<job_id>/kill", methods=["POST"])
@login_required
def kill(job_id):
    result = web_job_manager.kill_job(job_id)
    if result == "killed":
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
