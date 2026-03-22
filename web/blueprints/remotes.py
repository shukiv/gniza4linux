import os
import secrets

from markupsafe import escape
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify,
)

from lib.auto_configure import receive_and_configure
from lib.connection_test import test_remote as _test_remote
from lib.ssh_auto_configure import start_ssh_setup, get_task, pop_task
from tui.config import CONFIG_DIR, parse_conf, write_conf
from tui.models import Remote
from web.app import login_required
from web.backend import run_cli_sync
from web.helpers import load_remotes, get_rclone_remotes, _VALID_NAME_RE, paginate
from web.ssh_utils import get_ssh_keys as _get_ssh_keys

bp = Blueprint("remotes", __name__, url_prefix="/destinations")
_VALID_S3_PROVIDERS = {"AWS", "Backblaze", "Wasabi", "Other"}


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
    remotes, page, total_pages = paginate(remotes, page)
    return render_template("remotes/list.html", remotes=remotes, page=page, total_pages=total_pages)


@bp.route("/new")
@login_required
def new():
    remote = Remote()
    return render_template("remotes/edit.html", remote=remote, is_new=True, ssh_keys=_get_ssh_keys(), rclone_remotes=get_rclone_remotes())


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
    return render_template("remotes/edit.html", remote=remote, is_new=False, ssh_keys=_get_ssh_keys(), rclone_remotes=get_rclone_remotes(remote.rclone_config_path))


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
        rclone_config_path=form.get("rclone_config_path", ""),
        rclone_remote_name=form.get("rclone_remote_name", ""),
        sudo="yes" if form.get("sudo") else "no",
    )

    ok, msg = _test_remote(remote)
    if ok is False:
        flash(f"Test failed — not saved. {msg}", "error")
        is_new = not original_name
        return render_template("remotes/edit.html", remote=remote, is_new=is_new, ssh_keys=_get_ssh_keys(), rclone_remotes=get_rclone_remotes(remote.rclone_config_path))

    write_conf(CONFIG_DIR / "remotes.d" / f"{remote.name}.conf", remote.to_conf())
    if ok is None and msg:
        flash(f"Destination '{remote.name}' saved. Warning: {msg}", "warning")
    else:
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


@bp.route("/auto-configure")
@login_required
def auto_configure():
    return render_template("remotes/auto_configure.html")


@bp.route("/auto-configure", methods=["POST"])
@login_required
def auto_configure_receive():
    form = request.form
    dest_name = form.get("name", "").strip()
    code = form.get("code", "").strip()

    if not dest_name:
        flash("Destination name is required.", "error")
        return render_template("remotes/auto_configure.html")
    if not code:
        flash("Croc code is required.", "error")
        return render_template("remotes/auto_configure.html")

    remote, error = receive_and_configure(code, dest_name)
    if error:
        flash(error, "error")
        return render_template("remotes/auto_configure.html")

    # Test connection
    ok, msg = _test_remote(remote)
    if ok is False:
        # Still save the config even if test fails — user can fix later
        write_conf(CONFIG_DIR / "remotes.d" / f"{remote.name}.conf", remote.to_conf())
        flash(f"Destination '{remote.name}' saved but connection test failed: {msg}", "warning")
        return redirect(url_for("remotes.index"))

    write_conf(CONFIG_DIR / "remotes.d" / f"{remote.name}.conf", remote.to_conf())
    flash(f"Destination '{remote.name}' auto-configured successfully!", "success")
    return redirect(url_for("remotes.index"))


@bp.route("/ssh-keys")
@login_required
def ssh_keys():
    """Return existing SSH keys as JSON for the auto-configure form."""
    return jsonify(keys=_get_ssh_keys())


@bp.route("/ssh-auto-configure", methods=["POST"])
@login_required
def ssh_auto_configure():
    """Start SSH-based auto-configure in a background thread."""
    form = request.form
    name = form.get("name", "").strip()
    ssh_host = form.get("ssh_host", "").strip()
    ssh_port = form.get("ssh_port", "22").strip()
    ssh_user = form.get("ssh_user", "root").strip()
    auth_method = form.get("auth_method", "password").strip()
    ssh_password = form.get("ssh_password", "") if auth_method == "password" else ""
    ssh_key = form.get("ssh_key", "") if auth_method == "key" else ""
    backup_user = form.get("backup_user", "gniza").strip()
    base_dir = form.get("base_dir", "").strip()

    # Validation
    from lib.ssh_auto_configure import validate_inputs
    err = validate_inputs(name, ssh_host, ssh_port, ssh_user, backup_user, base_dir, "")
    if err:
        return jsonify(error=err), 400
    conf_path = CONFIG_DIR / "remotes.d" / f"{name}.conf"
    if conf_path.exists():
        return jsonify(error=f"Destination '{name}' already exists."), 400
    if auth_method == "password" and not ssh_password:
        return jsonify(error="SSH password is required."), 400
    if auth_method == "key" and not ssh_key:
        return jsonify(error="SSH key is required."), 400
    port_int = int(ssh_port)

    task_id = secrets.token_urlsafe(16)
    start_ssh_setup(
        task_id=task_id, name=name, mode="destination",
        ssh_host=ssh_host, ssh_port=str(port_int), ssh_user=ssh_user,
        ssh_password=ssh_password, ssh_key=ssh_key,
        backup_user=backup_user, base_dir=base_dir, folders="",
    )
    return jsonify(task_id=task_id)


@bp.route("/ssh-auto-configure/poll/<task_id>")
@login_required
def ssh_auto_configure_poll(task_id):
    """Poll SSH auto-configure task status."""
    task = get_task(task_id)
    if not task:
        return jsonify(status="error", error="Task not found."), 404

    resp = {"status": task["status"], "logs": task["logs"]}

    if task["status"] == "error":
        resp["error"] = task["error"]
        pop_task(task_id)
        return jsonify(resp)

    if task["status"] == "done":
        data = task["result"]
        key_path = task.get("key_path", "")
        pop_task(task_id)

        # Build Remote from result data (same pattern as auto_configure_receive)
        name = request.args.get("name", "").strip()
        if not name or not _VALID_NAME_RE.match(name):
            return jsonify(status="error", error="Invalid destination name."), 400

        remote = Remote(
            name=name,
            type="ssh",
            host=data.get("host", ""),
            port=data.get("port", "22"),
            user=data.get("user", "gniza"),
            auth_method="key",
            key=key_path,
            base=data.get("base", "/backups"),
            sudo=data.get("sudo", "yes"),
        )

        # Test connection
        try:
            ok, msg = _test_remote(remote)
        except Exception:
            ok, msg = None, ""

        write_conf(CONFIG_DIR / "remotes.d" / f"{remote.name}.conf", remote.to_conf())

        if ok is False:
            resp["warning"] = f"Destination saved but connection test failed: {msg}"
        resp["redirect"] = url_for("remotes.index")
        return jsonify(resp)

    return jsonify(resp)


@bp.route("/<name>/disk")
@login_required
def disk(name):
    if not _VALID_NAME_RE.match(name):
        return '<span class="text-error text-xs">Invalid</span>'
    try:
        rc, stdout, stderr = run_cli_sync("destinations", "disk-info-short", f"--name={name}", timeout=30)
        if rc == 0 and stdout.strip():
            return f'<span class="text-xs">{escape(stdout.strip())}</span>'
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
