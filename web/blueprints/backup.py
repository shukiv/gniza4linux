from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import list_conf_dir
from web.app import login_required
from web.helpers import _VALID_NAME_RE
from web.jobs import web_job_manager

bp = Blueprint("backup", __name__, url_prefix="/backup")


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
    if target_name == "all":
        target_name = ""
    if remote_name == "all":
        remote_name = ""

    if target_name and not _VALID_NAME_RE.match(target_name):
        flash("Invalid source name.", "error")
        return redirect(url_for("backup.index"))
    if remote_name and not _VALID_NAME_RE.match(remote_name):
        flash("Invalid destination name.", "error")
        return redirect(url_for("backup.index"))

    if not target_name:
        label = "Backup All"
        web_job_manager.create_and_start(
            "backup", label,
            "backup", "--all",
        )
    else:
        args = ["backup", f"--source={target_name}"]
        label_parts = [f"Backup {target_name}"]
        if remote_name:
            args.append(f"--destination={remote_name}")
            label_parts.append(f"-> {remote_name}")
        label = " ".join(label_parts)
        web_job_manager.create_and_start("backup", label, *args)

    flash(f"Backup job started: {label}", "success")
    return redirect(url_for("jobs.index"))
