import re

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import list_conf_dir
from web.app import login_required
from web.backend import run_cli_sync
from web.jobs import web_job_manager

bp = Blueprint("restore", __name__, url_prefix="/restore")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_VALID_SNAPSHOT_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')


@bp.route("/")
@login_required
def index():
    targets = list_conf_dir("targets.d")
    return render_template("restore/index.html", targets=targets)


@bp.route("/destinations/<target_name>")
@login_required
def destinations(target_name):
    if not _VALID_NAME_RE.match(target_name):
        return ""
    remotes = list_conf_dir("remotes.d")
    return render_template("restore/destinations_partial.html", remotes=remotes)


@bp.route("/snapshots/<target_name>/<remote_name>")
@login_required
def snapshots(target_name, remote_name):
    if not _VALID_NAME_RE.match(target_name) or not _VALID_NAME_RE.match(remote_name):
        return render_template("restore/snapshots_partial.html", snapshots=[])
    snapshot_list = []
    try:
        rc, stdout, stderr = run_cli_sync(
            "list-snapshots", "--target", target_name, "--remote", remote_name,
            timeout=30,
        )
        if rc == 0 and stdout.strip():
            snapshot_list = [s.strip() for s in stdout.strip().splitlines() if s.strip()]
    except Exception:
        pass
    return render_template("restore/snapshots_partial.html", snapshots=snapshot_list)


@bp.route("/run", methods=["POST"])
@login_required
def run():
    target_name = request.form.get("target", "").strip()
    remote_name = request.form.get("remote", "").strip()
    snapshot = request.form.get("snapshot", "").strip()

    if not target_name or not remote_name or not snapshot:
        flash("Please select a source, destination, and snapshot.", "error")
        return redirect(url_for("restore.index"))

    if not _VALID_NAME_RE.match(target_name) or not _VALID_NAME_RE.match(remote_name) or not _VALID_SNAPSHOT_RE.match(snapshot):
        flash("Invalid input.", "error")
        return redirect(url_for("restore.index"))

    label = f"Restore {target_name} <- {remote_name} ({snapshot})"
    web_job_manager.create_and_start(
        "restore", label,
        "restore", "--target", target_name, "--remote", remote_name, "--snapshot", snapshot,
    )
    flash(f"Restore job started: {label}", "success")
    return redirect(url_for("jobs.index"))
