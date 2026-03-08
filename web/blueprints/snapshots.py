import os
import re
import shlex
import socket
import subprocess

from flask import (
    Blueprint, render_template, request,
)

from tui.config import CONFIG_DIR, list_conf_dir, parse_conf
from web.app import login_required
from web.backend import run_cli_sync
from web.ssh_utils import ssh_cmd_from_conf

bp = Blueprint("snapshots", __name__, url_prefix="/snapshots")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_VALID_SNAPSHOT_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')
# Block path traversal
_VALID_SUBPATH_RE = re.compile(r'^[A-Za-z0-9_./ -]*$')


def _get_remote_conf(remote_name):
    """Load remote config dict."""
    conf = CONFIG_DIR / "remotes.d" / f"{remote_name}.conf"
    if not conf.is_file():
        return None
    return parse_conf(conf)


def _snapshot_base(remote_conf, target, snapshot):
    """Build the snapshot base path on the destination."""
    base = remote_conf.get("REMOTE_BASE", "/backups").rstrip("/")
    hostname = socket.getfqdn()
    return f"{base}/{hostname}/targets/{target}/snapshots/{snapshot}"


def _list_dir_local(path):
    """List dirs and files at a local path. Returns (dirs, files) or (None, error)."""
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        return None, "Directory not found"
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return None, "Permission denied"
    dirs = []
    files = []
    for e in entries:
        full = os.path.join(path, e)
        if os.path.isdir(full):
            dirs.append(e)
        elif os.path.isfile(full):
            files.append(e)
    return (dirs, files), None


def _list_dir_ssh(remote_conf, path):
    """List dirs and files at a path on an SSH remote. Returns (dirs, files) or (None, error)."""
    sq = shlex.quote(path)
    # List dirs and files separately with markers
    cmd_str = (
        f"if [ -d {sq} ]; then "
        f"  for f in {sq}/*; do "
        f"    [ -e \"$f\" ] || continue; "
        f"    if [ -d \"$f\" ]; then echo \"D:$(basename \"$f\")\"; "
        f"    else echo \"F:$(basename \"$f\")\"; fi; "
        f"  done | sort; "
        f"else echo 'ERROR:not_found'; fi"
    )
    cmd, sshpass_pw = ssh_cmd_from_conf(remote_conf)
    cmd = cmd + [cmd_str]
    env = None
    if sshpass_pw:
        env = os.environ.copy()
        env["SSHPASS"] = sshpass_pw
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=env)
        if result.returncode != 0:
            return None, result.stderr.strip() or "SSH connection failed"
        dirs = []
        files = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line == "ERROR:not_found":
                return None, "Directory not found"
            if line.startswith("D:"):
                dirs.append(line[2:])
            elif line.startswith("F:"):
                files.append(line[2:])
        return (dirs, files), None
    except subprocess.TimeoutExpired:
        return None, "Connection timed out"
    except OSError as e:
        return None, str(e)


def _list_snapshot_dir(remote_conf, target, snapshot, subpath=""):
    """List dirs and files at a subpath within a snapshot."""
    rtype = remote_conf.get("REMOTE_TYPE", "ssh")
    base = _snapshot_base(remote_conf, target, snapshot)
    full_path = base if not subpath else f"{base}/{subpath.strip('/')}"

    if rtype == "local":
        return _list_dir_local(full_path)
    elif rtype == "ssh":
        return _list_dir_ssh(remote_conf, full_path)
    else:
        return None, f"Unsupported destination type: {rtype}"


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
            "snapshots", "list", f"--source={target}", f"--destination={remote}",
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
    """Browse the top-level of a snapshot as a file manager."""
    if not _VALID_NAME_RE.match(target) or not _VALID_NAME_RE.match(remote) or not _VALID_SNAPSHOT_RE.match(snapshot):
        return render_template("snapshots/browse_partial.html", dirs=[], files=[], error="Invalid input.",
                               target=target, remote=remote, snapshot=snapshot, subpath="")
    subpath = request.args.get("path", "").strip("/")
    if subpath and not _VALID_SUBPATH_RE.match(subpath):
        return render_template("snapshots/browse_partial.html", dirs=[], files=[], error="Invalid path.",
                               target=target, remote=remote, snapshot=snapshot, subpath="")
    # Block traversal
    if ".." in subpath:
        return render_template("snapshots/browse_partial.html", dirs=[], files=[], error="Invalid path.",
                               target=target, remote=remote, snapshot=snapshot, subpath="")

    remote_conf = _get_remote_conf(remote)
    if not remote_conf:
        return render_template("snapshots/browse_partial.html", dirs=[], files=[], error="Destination not found.",
                               target=target, remote=remote, snapshot=snapshot, subpath=subpath)

    result, error = _list_snapshot_dir(remote_conf, target, snapshot, subpath)
    dirs, files = result if result else ([], [])
    return render_template("snapshots/browse_partial.html",
                           dirs=dirs, files=files, error=error or "",
                           target=target, remote=remote, snapshot=snapshot, subpath=subpath)


@bp.route("/browse_children/<target>/<remote>/<snapshot>")
@login_required
def browse_children(target, remote, snapshot):
    """Lazy-load children of a directory within a snapshot."""
    if not _VALID_NAME_RE.match(target) or not _VALID_NAME_RE.match(remote) or not _VALID_SNAPSHOT_RE.match(snapshot):
        return ""
    subpath = request.args.get("path", "").strip("/")
    if (subpath and not _VALID_SUBPATH_RE.match(subpath)) or ".." in subpath:
        return ""

    remote_conf = _get_remote_conf(remote)
    if not remote_conf:
        return ""

    result, error = _list_snapshot_dir(remote_conf, target, snapshot, subpath)
    if error or not result:
        return '<li><span class="text-base-content/40 italic text-xs px-2 py-1">Cannot read directory</span></li>'
    dirs, files = result
    return render_template("snapshots/browse_children.html",
                           dirs=dirs, files=files,
                           target=target, remote=remote, snapshot=snapshot, parent_path=subpath)
