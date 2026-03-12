import os
import shlex
import subprocess

from flask import Blueprint, request, render_template

from web.app import login_required
from web.ssh_utils import ssh_cmd

bp = Blueprint("api", __name__, url_prefix="/api")

_FOLDER_SVG = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" /></svg>'


def _list_dirs(path, show_hidden=False):
    """List subdirectories of path, optionally including hidden dirs."""
    path = os.path.realpath(path)
    if not os.path.isabs(path) or not os.path.isdir(path):
        return []
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return []
    dirs = []
    for entry in entries:
        if not show_hidden and entry.startswith("."):
            continue
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            dirs.append(entry)
    return dirs


@bp.route("/browse")
@login_required
def browse():
    """Return the full folder browser tree starting at a path."""
    path = request.args.get("path", "/")
    target = request.args.get("target", "")
    show_hidden = request.args.get("show_hidden", "") == "1"

    if not os.path.isabs(path):
        path = "/"
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        path = "/"

    dirs = _list_dirs(path, show_hidden=show_hidden)
    return render_template("components/folder_browser.html",
                           current_path=path, target=target, dirs=dirs,
                           show_hidden=show_hidden)


@bp.route("/browse/children")
@login_required
def browse_children():
    """Return child folder list items for lazy loading inside a <details>."""
    path = request.args.get("path", "/")
    target = request.args.get("target", "")
    show_hidden = request.args.get("show_hidden", "") == "1"

    if not os.path.isabs(path):
        return ""
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        return ""

    dirs = _list_dirs(path, show_hidden=show_hidden)
    return render_template("components/folder_browser_children.html",
                           parent_path=path, target=target, dirs=dirs,
                           show_hidden=show_hidden)


# ── SSH remote browsing ──────────────────────────────────────

def _ssh_list_dirs(host, path, port="22", user="root", key="", password="", show_hidden=False):
    """List directories on a remote SSH host."""
    quoted = shlex.quote(path)
    # Try find first, fall back to ls for restricted shells (e.g. Hetzner Storage Box)
    find_cmd = f"find {quoted} -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort"
    # -p appends / to directories so we can filter them
    ls_cmd = f"ls -1p {quoted}" if path != "/" else "ls -1p ."
    base_cmd = ssh_cmd(host, port, user, key, password)
    env = None
    if password:
        env = os.environ.copy()
        env["SSHPASS"] = password
    try:
        used_ls = False
        result = subprocess.run(base_cmd + [find_cmd], capture_output=True, text=True, timeout=15, env=env)
        if result.returncode != 0:
            used_ls = True
            # Fallback to ls -1p (works on restricted shells, -p marks dirs with /)
            result = subprocess.run(base_cmd + [ls_cmd], capture_output=True, text=True, timeout=15, env=env)
            if result.returncode != 0:
                # Path may not exist — fall back to home directory
                result = subprocess.run(base_cmd + ["ls", "-1p", "."], capture_output=True, text=True, timeout=15, env=env)
                if result.returncode != 0:
                    return None, result.stderr.strip() or "Connection failed"
                path = "/"
        dirs = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if not line or line == path:
                continue
            # With ls -1p, only entries ending with / are directories
            if used_ls and not line.endswith("/"):
                continue
            name = line.rstrip("/").rsplit("/", 1)[-1]
            if not show_hidden and name.startswith("."):
                continue
            dirs.append(name)
        return sorted(dirs), None
    except subprocess.TimeoutExpired:
        return None, "Connection timed out"
    except OSError as e:
        return None, str(e)


@bp.route("/browse/ssh", methods=["GET", "POST"])
@login_required
def browse_ssh():
    """Browse directories on a remote SSH host."""
    host = request.values.get("host", "")
    port = request.values.get("port", "22")
    user = request.values.get("user", "root")
    key = request.values.get("key", "")
    password = request.values.get("password", "")
    path = request.args.get("path", "/")
    target = request.args.get("target", "")
    show_hidden = request.args.get("show_hidden", "") == "1"

    if not host:
        return '<div class="alert alert-error text-sm">No host specified</div>'

    if not os.path.isabs(path):
        path = "/"

    dirs, err = _ssh_list_dirs(host, path, port, user, key, password, show_hidden=show_hidden)
    if err:
        return f'<div class="alert alert-error text-sm">{err}</div>'

    return render_template("components/folder_browser.html",
                           current_path=path, target=target, dirs=dirs,
                           show_hidden=show_hidden,
                           ssh=True, ssh_host=host, ssh_port=port,
                           ssh_user=user, ssh_key=key, ssh_password=password)


@bp.route("/browse/ssh/children", methods=["GET", "POST"])
@login_required
def browse_ssh_children():
    """Return child folders on an SSH host for lazy loading."""
    host = request.values.get("host", "")
    port = request.values.get("port", "22")
    user = request.values.get("user", "root")
    key = request.values.get("key", "")
    password = request.values.get("password", "")
    path = request.args.get("path", "/")
    target = request.args.get("target", "")
    show_hidden = request.args.get("show_hidden", "") == "1"

    if not host or not os.path.isabs(path):
        return ""

    dirs, err = _ssh_list_dirs(host, path, port, user, key, password, show_hidden=show_hidden)
    if err or dirs is None:
        return ""

    return render_template("components/folder_browser_children.html",
                           parent_path=path, target=target, dirs=dirs,
                           show_hidden=show_hidden,
                           ssh=True, ssh_host=host, ssh_port=port,
                           ssh_user=user, ssh_key=key, ssh_password=password)
