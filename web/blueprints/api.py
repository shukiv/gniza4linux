import os
import re
import shlex
import subprocess

from flask import Blueprint, request, render_template
from markupsafe import escape

from web.app import login_required
from web.helpers import get_rclone_remotes, _VALID_NAME_RE
from web.ssh_utils import ssh_cmd, sftp_cmd as build_sftp_cmd

bp = Blueprint("api", __name__, url_prefix="/api")


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

def _sftp_list_dirs(host, path, port="22", user="root", key="", password="", show_hidden=False):
    """List directories via sftp (for restricted shells like Hetzner Storage Box)."""
    sftp_cmd = build_sftp_cmd(host, port, user, key, password)
    env = None
    if password:
        env = os.environ.copy()
        env["SSHPASS"] = password
    if "\n" in path or "\r" in path:
        path = "/"
    sftp_path = shlex.quote(path if path and path != "/" else ".")
    try:
        result = subprocess.run(
            sftp_cmd, input=f"ls -1 {sftp_path}\nbye\n",
            capture_output=True, text=True, timeout=15, env=env,
        )
        if result.returncode != 0:
            return None, result.stderr.strip() or "SFTP connection failed"
        dirs = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("sftp>") or line.startswith("Connected"):
                continue
            name = line.rstrip("/").rsplit("/", 1)[-1]
            if not name or name in (".", ".."):
                continue
            if not show_hidden and name.startswith("."):
                continue
            dirs.append(name)
        return sorted(dirs), None
    except subprocess.TimeoutExpired:
        return None, "Connection timed out"
    except OSError as e:
        return None, str(e)


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
                    # All SSH commands failed — try sftp as last resort (restricted shell)
                    return _sftp_list_dirs(host, path, port, user, key, password, show_hidden)
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

    if not host or not re.match(r'^[a-zA-Z0-9._:-]+$', host):
        return '<div class="alert alert-error text-sm">Invalid host</div>'
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        return '<div class="alert alert-error text-sm">Invalid port</div>'
    if user and not re.match(r'^[a-zA-Z0-9._@-]+$', user):
        return '<div class="alert alert-error text-sm">Invalid user</div>'
    if key and (not os.path.isabs(key) or '..' in key):
        return '<div class="alert alert-error text-sm">Invalid key path</div>'

    if not os.path.isabs(path):
        path = "/"

    dirs, err = _ssh_list_dirs(host, path, port, user, key, password, show_hidden=show_hidden)
    if err:
        return f'<div class="alert alert-error text-sm">{escape(err)}</div>'

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

    if not host or not re.match(r'^[a-zA-Z0-9._:-]+$', host):
        return ""
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        return ""
    if user and not re.match(r'^[a-zA-Z0-9._@-]+$', user):
        return ""
    if key and (not os.path.isabs(key) or '..' in key):
        return ""
    if not os.path.isabs(path):
        return ""

    dirs, err = _ssh_list_dirs(host, path, port, user, key, password, show_hidden=show_hidden)
    if err or dirs is None:
        return ""

    return render_template("components/folder_browser_children.html",
                           parent_path=path, target=target, dirs=dirs,
                           show_hidden=show_hidden,
                           ssh=True, ssh_host=host, ssh_port=port,
                           ssh_user=user, ssh_key=key, ssh_password=password)


def _rclone_list_dirs(remote_name, path="", config_path="", show_hidden=False):
    """List directories on an rclone remote."""
    cmd = ["rclone", "lsf", "--dirs-only"]
    if config_path:
        cmd += ["--config", config_path]
    # Build remote:path string
    rpath = f"{remote_name}:{path}"
    cmd.append(rpath)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            err = result.stderr.strip() or "Failed to list remote path"
            return None, err
        dirs = []
        for line in result.stdout.strip().splitlines():
            name = line.strip().rstrip("/")
            if not name:
                continue
            if not show_hidden and name.startswith("."):
                continue
            dirs.append(name)
        return sorted(dirs), None
    except FileNotFoundError:
        return None, "rclone is not installed"
    except subprocess.TimeoutExpired:
        return None, "Connection timed out"
    except OSError as e:
        return None, str(e)


@bp.route("/browse/rclone")
@login_required
def browse_rclone():
    """Browse directories on an rclone remote."""
    remote_name = request.args.get("remote_name", "")
    config_path = request.args.get("config_path", "")
    path = request.args.get("path", "")
    target = request.args.get("target", "")
    show_hidden = request.args.get("show_hidden", "") == "1"

    if not remote_name or not _VALID_NAME_RE.match(remote_name):
        return '<div class="alert alert-error text-sm">Invalid remote name</div>'
    if config_path:
        config_path = os.path.realpath(config_path)
        allowed_dirs = [os.path.expanduser("~/.config/rclone"), "/etc/gniza", os.path.expanduser("~")]
        if not any(config_path.startswith(d) for d in allowed_dirs):
            return '<div class="alert alert-error text-sm">Config path not in allowed directory</div>'
        if not os.path.isfile(config_path):
            return '<div class="alert alert-error text-sm">Invalid config path</div>'
    if '..' in path.split('/'):
        return '<div class="alert alert-error text-sm">Invalid path</div>'

    dirs, err = _rclone_list_dirs(remote_name, path, config_path, show_hidden=show_hidden)
    if err:
        return f'<div class="alert alert-error text-sm">{escape(err)}</div>'

    return render_template("components/folder_browser.html",
                           current_path=path, target=target, dirs=dirs,
                           show_hidden=show_hidden,
                           rclone=True, rclone_remote_name=remote_name,
                           rclone_config_path=config_path)


@bp.route("/browse/rclone/children")
@login_required
def browse_rclone_children():
    """Return child folders on an rclone remote for lazy loading."""
    remote_name = request.args.get("remote_name", "")
    config_path = request.args.get("config_path", "")
    path = request.args.get("path", "")
    target = request.args.get("target", "")
    show_hidden = request.args.get("show_hidden", "") == "1"

    if not remote_name or not _VALID_NAME_RE.match(remote_name):
        return ""
    if config_path:
        config_path = os.path.realpath(config_path)
        allowed_dirs = [os.path.expanduser("~/.config/rclone"), "/etc/gniza", os.path.expanduser("~")]
        if not any(config_path.startswith(d) for d in allowed_dirs):
            return ""
        if not os.path.isfile(config_path):
            return ""
    if '..' in path.split('/'):
        return ""

    dirs, err = _rclone_list_dirs(remote_name, path, config_path, show_hidden=show_hidden)
    if err or dirs is None:
        return ""

    return render_template("components/folder_browser_children.html",
                           parent_path=path, target=target, dirs=dirs,
                           show_hidden=show_hidden,
                           rclone=True, rclone_remote_name=remote_name,
                           rclone_config_path=config_path)


@bp.route("/rclone-remotes")
@login_required
def rclone_remotes():
    config_path = request.args.get("rclone_config_path", "") or request.args.get("source_rclone_config_path", "")
    if config_path:
        config_path = os.path.realpath(config_path)
        allowed_dirs = [os.path.expanduser("~/.config/rclone"), "/etc/gniza", os.path.expanduser("~")]
        if not any(config_path.startswith(d) for d in allowed_dirs):
            return '<option value="">Config path not in allowed directory</option>'
    remotes = get_rclone_remotes(config_path)
    selected = request.args.get("selected", "")
    if not remotes:
        return '<option value="">No remotes found</option>'
    html = '<option value="">-- Select a remote --</option>'
    for r in remotes:
        sel = ' selected' if r == selected else ''
        html += f'<option value="{escape(r)}"{sel}>{escape(r)}</option>'
    return html
