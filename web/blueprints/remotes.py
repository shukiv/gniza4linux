import os
import re
import subprocess

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import CONFIG_DIR, parse_conf, write_conf
from tui.models import Remote
from web.app import login_required
from web.backend import run_cli_sync
from web.helpers import load_remotes
from web.ssh_utils import ssh_cmd

bp = Blueprint("remotes", __name__, url_prefix="/destinations")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_VALID_S3_PROVIDERS = {"AWS", "Backblaze", "Wasabi", "Other"}


def _test_remote(remote):
    if remote.type == "local":
        base = remote.base or "/backups"
        try:
            os.makedirs(base, exist_ok=True)
        except OSError as e:
            return False, f"Cannot create base path '{base}': {e}"
        return True, None

    if remote.type == "ssh":
        key = remote.key if remote.auth_method == "key" else ""
        password = remote.password if remote.auth_method == "password" else ""
        cmd = ssh_cmd(remote.host, remote.port, remote.user, key, password)
        env = None
        if password:
            env = os.environ.copy()
            env["SSHPASS"] = password
        base = remote.base or "/backups"
        try:
            result = subprocess.run(cmd + ["echo", "ok"], capture_output=True, text=True, timeout=15, env=env)
            if result.returncode != 0:
                return False, f"SSH connection failed: {result.stderr.strip() or 'unknown error'}"
        except subprocess.TimeoutExpired:
            return False, "SSH connection timed out"
        except OSError as e:
            return False, f"SSH connection failed: {e}"
        try:
            result = subprocess.run(cmd + ["mkdir", "-p", base], capture_output=True, text=True, timeout=15, env=env)
            if result.returncode != 0:
                return False, f"Failed to create base path: {result.stderr.strip()}"
        except (subprocess.TimeoutExpired, OSError) as e:
            return False, f"Failed to create base path: {e}"
        try:
            test_file = f"{base}/validation_success.txt"
            result = subprocess.run(
                cmd + ["sh", "-c", f'echo "gniza validation" > {test_file}'],
                capture_output=True, text=True, timeout=15, env=env,
            )
            if result.returncode != 0:
                return False, f"Failed to write test file: {result.stderr.strip()}"
        except (subprocess.TimeoutExpired, OSError) as e:
            return False, f"Failed to write test file: {e}"
        return True, None

    if remote.type == "s3":
        from tui.rclone_test import test_rclone_s3
        return test_rclone_s3(
            bucket=remote.s3_bucket,
            region=remote.s3_region,
            endpoint=remote.s3_endpoint,
            access_key_id=remote.s3_access_key_id,
            secret_access_key=remote.s3_secret_access_key,
            provider=remote.s3_provider,
        )

    if remote.type == "gdrive":
        from tui.rclone_test import test_rclone_gdrive
        return test_rclone_gdrive(
            sa_file=remote.gdrive_sa_file,
            root_folder_id=remote.gdrive_root_folder_id,
        )

    return True, None


@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1
    try:
        remotes = load_remotes()
    except Exception:
        remotes = []
        flash("Failed to load destinations.", "error")
    total = len(remotes)
    per_page = 20
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    remotes = remotes[start:start + per_page]
    return render_template("remotes/list.html", remotes=remotes, page=page, total_pages=total_pages)


@bp.route("/new")
@login_required
def new():
    remote = Remote()
    return render_template("remotes/edit.html", remote=remote, is_new=True)


@bp.route("/<name>/edit")
@login_required
def edit(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid name.", "error")
        return redirect(url_for("remotes.index"))
    conf_path = CONFIG_DIR / "remotes.d" / f"{name}.conf"
    if not conf_path.is_file():
        flash("Destination not found.", "error")
        return redirect(url_for("remotes.index"))
    data = parse_conf(conf_path)
    remote = Remote.from_conf(name, data)
    return render_template("remotes/edit.html", remote=remote, is_new=False)


@bp.route("/save", methods=["POST"])
@login_required
def save():
    form = request.form
    name = form.get("name", "").strip()
    original_name = form.get("original_name", "").strip()

    if not name or not _VALID_NAME_RE.match(name):
        flash("Invalid name. Use only letters, numbers, hyphens, and underscores.", "error")
        return redirect(url_for("remotes.index"))

    if original_name and original_name != name:
        if not _VALID_NAME_RE.match(original_name):
            flash("Invalid original name.", "error")
            return redirect(url_for("remotes.index"))
        old_path = CONFIG_DIR / "remotes.d" / f"{original_name}.conf"
        if old_path.is_file():
            os.unlink(old_path)

    remote = Remote(
        name=name,
        type=form.get("type", "local"),
        host=form.get("host", ""),
        port=form.get("port", "22"),
        user=form.get("user", "root"),
        auth_method=form.get("auth_method", "key"),
        key=form.get("key", ""),
        password=form.get("password", ""),
        base=form.get("base", "/backups"),
        bwlimit=form.get("bwlimit", "0"),
        s3_provider=form.get("s3_provider", "AWS") if form.get("s3_provider", "AWS") in _VALID_S3_PROVIDERS else "AWS",
        s3_bucket=form.get("s3_bucket", ""),
        s3_region=form.get("s3_region", "us-east-1"),
        s3_endpoint=form.get("s3_endpoint", ""),
        s3_access_key_id=form.get("s3_access_key_id", ""),
        s3_secret_access_key=form.get("s3_secret_access_key", ""),
        gdrive_sa_file=form.get("gdrive_sa_file", ""),
        gdrive_root_folder_id=form.get("gdrive_root_folder_id", ""),
    )

    ok, msg = _test_remote(remote)
    if ok is False:
        flash(msg, "error")
        if original_name:
            return redirect(url_for("remotes.edit", name=original_name))
        return redirect(url_for("remotes.new"))

    write_conf(CONFIG_DIR / "remotes.d" / f"{remote.name}.conf", remote.to_conf())
    flash(f"Destination '{remote.name}' saved.", "success")
    return redirect(url_for("remotes.index"))


@bp.route("/<name>/delete", methods=["POST"])
@login_required
def delete(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid name.", "error")
        return redirect(url_for("remotes.index"))
    conf_path = CONFIG_DIR / "remotes.d" / f"{name}.conf"
    if conf_path.is_file():
        os.unlink(conf_path)
        flash(f"Destination '{name}' deleted.", "success")
    else:
        flash("Destination not found.", "error")
    return redirect(url_for("remotes.index"))


@bp.route("/<name>/disk")
@login_required
def disk(name):
    if not _VALID_NAME_RE.match(name):
        return '<span class="text-error text-xs">Invalid</span>'
    try:
        rc, stdout, stderr = run_cli_sync("destinations", "disk-info-short", f"--name={name}", timeout=30)
        if rc == 0 and stdout.strip():
            return f'<span class="text-xs">{stdout.strip()}</span>'
        return '<span class="text-base-content/40 text-xs">N/A</span>'
    except Exception:
        return '<span class="text-base-content/40 text-xs">timeout</span>'


@bp.route("/<name>/test", methods=["POST"])
@login_required
def test(name):
    if not _VALID_NAME_RE.match(name):
        return render_template("remotes/test_result.html", result={"status": "error", "message": "Invalid name."})
    try:
        rc, stdout, stderr = run_cli_sync("destinations", "test", f"--name={name}", timeout=30)
        if rc == 0:
            result = {"status": "success", "message": stdout.strip() or "Connection successful."}
        else:
            result = {"status": "error", "message": stderr.strip() or stdout.strip() or "Connection failed."}
    except Exception as e:
        result = {"status": "error", "message": str(e)}
    return render_template("remotes/test_result.html", result=result)
