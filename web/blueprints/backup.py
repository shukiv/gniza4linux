from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from lib.backup_orchestrator import BackupOrchestrator
from web.app import login_required
from web.helpers import _VALID_NAME_RE
from web.jobs import web_job_manager

bp = Blueprint("backup", __name__, url_prefix="/backup")

_orchestrator = BackupOrchestrator()


@bp.route("/")
@login_required
def index():
    targets = _orchestrator.list_targets()
    remotes = _orchestrator.list_remotes()
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

    if target_name:
        ok, msg = _orchestrator.validate_target(target_name)
        if not ok:
            flash(msg, "error")
            return redirect(url_for("backup.index"))
        if remote_name:
            ok, msg = _orchestrator.validate_remote(remote_name)
            if not ok:
                flash(msg, "error")
                return redirect(url_for("backup.index"))

    cmd = _orchestrator.build_backup_command(
        target=target_name or None,
        remote=remote_name or None,
        all_targets=not target_name,
    )
    cli_args = _orchestrator.cli_args(cmd)

    if not target_name:
        label = "Backup All"
    else:
        label_parts = [f"Backup {target_name}"]
        if remote_name:
            label_parts.append(f"-> {remote_name}")
        label = " ".join(label_parts)

    web_job_manager.create_and_start("backup", label, *cli_args)
    flash(f"Backup job started: {label}", "success")
    return redirect(url_for("jobs.index"))
