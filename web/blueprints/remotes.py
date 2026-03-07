import os
import re

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import CONFIG_DIR, parse_conf, write_conf, list_conf_dir
from tui.models import Remote
from web.app import login_required
from web.backend import run_cli_sync

bp = Blueprint("remotes", __name__, url_prefix="/destinations")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')


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
        remotes = _load_remotes()
    except Exception:
        remotes = []
        flash("Failed to load destinations.", "error")
    return render_template("remotes/list.html", remotes=remotes)


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
        type=form.get("type", "ssh"),
        host=form.get("host", ""),
        port=form.get("port", "22"),
        user=form.get("user", "root"),
        auth_method=form.get("auth_method", "key"),
        key=form.get("key", ""),
        password=form.get("password", ""),
        base=form.get("base", "/backups"),
        bwlimit=form.get("bwlimit", "0"),
        retention_count=form.get("retention_count", "30"),
        s3_bucket=form.get("s3_bucket", ""),
        s3_region=form.get("s3_region", "us-east-1"),
        s3_endpoint=form.get("s3_endpoint", ""),
        s3_access_key_id=form.get("s3_access_key_id", ""),
        s3_secret_access_key=form.get("s3_secret_access_key", ""),
        gdrive_sa_file=form.get("gdrive_sa_file", ""),
        gdrive_root_folder_id=form.get("gdrive_root_folder_id", ""),
    )

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


@bp.route("/<name>/test", methods=["POST"])
@login_required
def test(name):
    if not _VALID_NAME_RE.match(name):
        return render_template("remotes/test_result.html", result={"status": "error", "message": "Invalid name."})
    try:
        rc, stdout, stderr = run_cli_sync("test-remote", name, timeout=30)
        if rc == 0:
            result = {"status": "success", "message": stdout.strip() or "Connection successful."}
        else:
            result = {"status": "error", "message": stderr.strip() or stdout.strip() or "Connection failed."}
    except Exception as e:
        result = {"status": "error", "message": str(e)}
    return render_template("remotes/test_result.html", result=result)
