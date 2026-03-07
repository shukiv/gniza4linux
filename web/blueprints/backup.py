import re

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import list_conf_dir
from web.app import login_required
from web.jobs import web_job_manager

bp = Blueprint("backup", __name__, url_prefix="/backup")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')


@bp.route("/")
@login_required
def index():
    targets = list_conf_dir("targets.d")
    remotes = list_conf_dir("remotes.d")
    return render_template("backup/index.html", targets=targets, remotes=remotes)


@bp.route("/run", methods=["POST"])
@login_required
def run():
    target_name = request.form.get("target", "").strip()
    remote_name = request.form.get("remote", "").strip()

    if not target_name or not remote_name:
        flash("Please select both a source and a destination.", "error")
        return redirect(url_for("backup.index"))

    if not _VALID_NAME_RE.match(target_name) or not _VALID_NAME_RE.match(remote_name):
        flash("Invalid source or destination name.", "error")
        return redirect(url_for("backup.index"))

    label = f"Backup {target_name} -> {remote_name}"
    web_job_manager.create_and_start(
        "backup", label,
        "backup", "--target", target_name, "--remote", remote_name,
    )
    flash(f"Backup job started: {label}", "success")
    return redirect(url_for("jobs.index"))
