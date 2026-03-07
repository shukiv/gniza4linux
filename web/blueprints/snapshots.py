import re

from flask import (
    Blueprint, render_template, request,
)

from tui.config import list_conf_dir
from web.app import login_required
from web.backend import run_cli_sync

bp = Blueprint("snapshots", __name__, url_prefix="/snapshots")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_VALID_SNAPSHOT_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')


@bp.route("/")
@login_required
def index():
    targets = list_conf_dir("targets.d")
    remotes = list_conf_dir("remotes.d")
    return render_template("snapshots/index.html", targets=targets, remotes=remotes)


@bp.route("/list/<target>/<remote>")
@login_required
def list_snapshots(target, remote):
    if not _VALID_NAME_RE.match(target) or not _VALID_NAME_RE.match(remote):
        return render_template("snapshots/list_partial.html", snapshots=[], error="Invalid name.", target=target, remote=remote)
    snapshot_list = []
    error = ""
    try:
        rc, stdout, stderr = run_cli_sync(
            "list-snapshots", "--target", target, "--remote", remote,
            timeout=30,
        )
        if rc == 0 and stdout.strip():
            snapshot_list = [s.strip() for s in stdout.strip().splitlines() if s.strip()]
        elif rc != 0:
            error = stderr.strip() or "Failed to list snapshots."
    except Exception:
        error = "Timed out listing snapshots."
    return render_template("snapshots/list_partial.html", snapshots=snapshot_list, error=error, target=target, remote=remote)


@bp.route("/browse/<target>/<remote>/<snapshot>")
@login_required
def browse(target, remote, snapshot):
    if not _VALID_NAME_RE.match(target) or not _VALID_NAME_RE.match(remote) or not _VALID_SNAPSHOT_RE.match(snapshot):
        return render_template("snapshots/browse_partial.html", files=[], error="Invalid input.")
    files = []
    error = ""
    try:
        rc, stdout, stderr = run_cli_sync(
            "browse-snapshot", "--target", target, "--remote", remote, "--snapshot", snapshot,
            timeout=30,
        )
        if rc == 0 and stdout.strip():
            files = [f.strip() for f in stdout.strip().splitlines() if f.strip()]
        elif rc != 0:
            error = stderr.strip() or "Failed to browse snapshot."
    except Exception:
        error = "Timed out browsing snapshot."
    return render_template("snapshots/browse_partial.html", files=files, error=error)
