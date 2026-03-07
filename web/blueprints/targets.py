import os
import re
import subprocess

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import CONFIG_DIR, parse_conf, write_conf, list_conf_dir
from tui.models import Target, Remote
from web.app import login_required

bp = Blueprint("targets", __name__, url_prefix="/sources")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')


def _ssh_cmd(host, port="22", user="root", key="", password=""):
    ssh_opts = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-p", port or "22",
    ]
    if key:
        ssh_opts += ["-i", key]
    ssh_opts.append(f"{user}@{host}")
    if password:
        return ["sshpass", "-p", password] + ssh_opts
    return ssh_opts


def _test_source(target):
    if target.source_type == "local":
        if target.folders:
            folder_list = [f.strip() for f in target.folders.split(",") if f.strip()]
            missing = [f for f in folder_list if not os.path.isdir(f)]
            if missing:
                return None, f"Warning: folders not found: {', '.join(missing)}"
        return True, None

    if target.source_type == "ssh":
        host = target.source_host
        port = target.source_port or "22"
        user = target.source_user or "root"
        key = target.source_key if target.source_auth_method == "key" else ""
        password = target.source_password if target.source_auth_method == "password" else ""
        cmd = _ssh_cmd(host, port, user, key, password)
        try:
            result = subprocess.run(cmd + ["echo", "ok"], capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                return False, f"SSH connection failed: {result.stderr.strip() or 'unknown error'}"
        except subprocess.TimeoutExpired:
            return False, "SSH connection timed out"
        except OSError as e:
            return False, f"SSH connection failed: {e}"
        if target.folders:
            folder_list = [f.strip() for f in target.folders.split(",") if f.strip()]
            try:
                result = subprocess.run(
                    cmd + ["test", "-d", folder_list[0]],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode != 0:
                    return None, f"Warning: folder '{folder_list[0]}' not accessible on remote"
            except (subprocess.TimeoutExpired, OSError):
                pass
        return True, None

    if target.source_type == "s3":
        from tui.rclone_test import test_rclone_s3
        return test_rclone_s3(
            bucket=target.source_s3_bucket,
            region=target.source_s3_region,
            endpoint=target.source_s3_endpoint,
            access_key_id=target.source_s3_access_key_id,
            secret_access_key=target.source_s3_secret_access_key,
        )

    if target.source_type == "gdrive":
        from tui.rclone_test import test_rclone_gdrive
        return test_rclone_gdrive(
            sa_file=target.source_gdrive_sa_file,
            root_folder_id=target.source_gdrive_root_folder_id,
        )

    return True, None


def _load_targets():
    targets = []
    for name in list_conf_dir("targets.d"):
        data = parse_conf(CONFIG_DIR / "targets.d" / f"{name}.conf")
        targets.append(Target.from_conf(name, data))
    return targets


def _load_remotes():
    remotes = []
    for name in list_conf_dir("remotes.d"):
        data = parse_conf(CONFIG_DIR / "remotes.d" / f"{name}.conf")
        remotes.append(Remote.from_conf(name, data))
    return remotes


@bp.route("/")
@login_required
def index():
    try:
        targets = _load_targets()
    except Exception:
        targets = []
        flash("Failed to load sources.", "error")
    return render_template("targets/list.html", targets=targets)


@bp.route("/new")
@login_required
def new():
    target = Target()
    remotes = _load_remotes()
    return render_template("targets/edit.html", target=target, remotes=remotes, is_new=True)


@bp.route("/<name>/edit")
@login_required
def edit(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid name.", "error")
        return redirect(url_for("targets.index"))
    conf_path = CONFIG_DIR / "targets.d" / f"{name}.conf"
    if not conf_path.is_file():
        flash("Source not found.", "error")
        return redirect(url_for("targets.index"))
    data = parse_conf(conf_path)
    target = Target.from_conf(name, data)
    remotes = _load_remotes()
    return render_template("targets/edit.html", target=target, remotes=remotes, is_new=False)


@bp.route("/save", methods=["POST"])
@login_required
def save():
    form = request.form
    name = form.get("name", "").strip()
    original_name = form.get("original_name", "").strip()

    if not name or not _VALID_NAME_RE.match(name):
        flash("Invalid name. Use only letters, numbers, hyphens, and underscores.", "error")
        return redirect(url_for("targets.index"))

    # If renaming, delete old file
    if original_name and original_name != name:
        if not _VALID_NAME_RE.match(original_name):
            flash("Invalid original name.", "error")
            return redirect(url_for("targets.index"))
        old_path = CONFIG_DIR / "targets.d" / f"{original_name}.conf"
        if old_path.is_file():
            os.unlink(old_path)

    target = Target(
        name=name,
        folders=form.get("folders", ""),
        exclude=form.get("exclude", ""),
        include=form.get("include", ""),
        remote=form.get("remote", ""),
        pre_hook=form.get("pre_hook", ""),
        post_hook=form.get("post_hook", ""),
        enabled="yes" if form.get("enabled") else "no",
        source_type=form.get("source_type", "local"),
        source_host=form.get("source_host", ""),
        source_port=form.get("source_port", "22"),
        source_user=form.get("source_user", "root"),
        source_auth_method=form.get("source_auth_method", "key"),
        source_key=form.get("source_key", ""),
        source_password=form.get("source_password", ""),
        source_s3_bucket=form.get("source_s3_bucket", ""),
        source_s3_region=form.get("source_s3_region", "us-east-1"),
        source_s3_endpoint=form.get("source_s3_endpoint", ""),
        source_s3_access_key_id=form.get("source_s3_access_key_id", ""),
        source_s3_secret_access_key=form.get("source_s3_secret_access_key", ""),
        source_gdrive_sa_file=form.get("source_gdrive_sa_file", ""),
        source_gdrive_root_folder_id=form.get("source_gdrive_root_folder_id", ""),
        mysql_enabled="yes" if form.get("mysql_enabled") else "no",
        mysql_mode=form.get("mysql_mode", "all"),
        mysql_databases=form.get("mysql_databases", ""),
        mysql_exclude=form.get("mysql_exclude", ""),
        mysql_user=form.get("mysql_user", ""),
        mysql_password=form.get("mysql_password", ""),
        mysql_host=form.get("mysql_host", "localhost"),
        mysql_port=form.get("mysql_port", "3306"),
        mysql_extra_opts=form.get("mysql_extra_opts", "--single-transaction --routines --triggers"),
    )

    ok, msg = _test_source(target)
    if ok is False:
        flash(msg, "error")
        if original_name:
            return redirect(url_for("targets.edit", name=original_name))
        return redirect(url_for("targets.new"))
    if ok is None and msg:
        flash(msg, "warning")

    write_conf(CONFIG_DIR / "targets.d" / f"{target.name}.conf", target.to_conf())
    flash(f"Source '{target.name}' saved.", "success")
    return redirect(url_for("targets.index"))


@bp.route("/<name>/delete", methods=["POST"])
@login_required
def delete(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid name.", "error")
        return redirect(url_for("targets.index"))
    conf_path = CONFIG_DIR / "targets.d" / f"{name}.conf"
    if conf_path.is_file():
        os.unlink(conf_path)
        flash(f"Source '{name}' deleted.", "success")
    else:
        flash("Source not found.", "error")
    return redirect(url_for("targets.index"))


@bp.route("/<name>/toggle", methods=["POST"])
@login_required
def toggle(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid name.", "error")
        return redirect(url_for("targets.index"))
    conf_path = CONFIG_DIR / "targets.d" / f"{name}.conf"
    if not conf_path.is_file():
        flash("Source not found.", "error")
        return redirect(url_for("targets.index"))
    data = parse_conf(conf_path)
    target = Target.from_conf(name, data)
    target.enabled = "no" if target.enabled == "yes" else "yes"
    write_conf(conf_path, target.to_conf())
    flash(f"Source '{name}' {'enabled' if target.enabled == 'yes' else 'disabled'}.", "success")
    return redirect(url_for("targets.index"))
