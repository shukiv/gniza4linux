import re

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import list_conf_dir
from web.app import login_required
from web.jobs import web_job_manager

bp = Blueprint("retention", __name__, url_prefix="/retention")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')


@bp.route("/")
@login_required
def index():
    targets = list_conf_dir("targets.d")
    remotes = list_conf_dir("remotes.d")
    return render_template("retention/index.html", targets=targets, remotes=remotes)


@bp.route("/run", methods=["POST"])
@login_required
def run():
    target_name = request.form.get("target", "").strip()
    remote_name = request.form.get("remote", "").strip()
    dry_run = request.form.get("dry_run")

    if target_name and not _VALID_NAME_RE.match(target_name):
        flash("Invalid source name.", "error")
        return redirect(url_for("retention.index"))
    if remote_name and not _VALID_NAME_RE.match(remote_name):
        flash("Invalid destination name.", "error")
        return redirect(url_for("retention.index"))

    args = ["retention"]
    label_parts = ["Retention"]

    if target_name:
        args += ["--target", target_name]
        label_parts.append(target_name)
    if remote_name:
        args += ["--remote", remote_name]
        label_parts.append(remote_name)
    if dry_run:
        args.append("--dry-run")
        label_parts.append("(dry-run)")

    label = " ".join(label_parts)
    web_job_manager.create_and_start("retention", label, *args)
    flash(f"Retention job started: {label}", "success")
    return redirect(url_for("jobs.index"))
