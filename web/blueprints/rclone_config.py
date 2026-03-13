import json
import re
import subprocess

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from web.app import login_required

bp = Blueprint("rclone_config", __name__, url_prefix="/rclone-config")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')

# Module-level cache for providers
_providers_cache = None


def _get_providers():
    global _providers_cache
    if _providers_cache is not None:
        return _providers_cache
    try:
        result = subprocess.run(
            ["rclone", "config", "providers"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            _providers_cache = data if isinstance(data, list) else data.get("providers", [])
            return _providers_cache
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        pass
    return []


def _get_remotes():
    try:
        result = subprocess.run(
            ["rclone", "config", "dump"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        pass
    return {}


def _get_provider_options(provider_type):
    """Return non-advanced options for a given provider type."""
    providers = _get_providers()
    for p in providers:
        if p.get("Name") == provider_type:
            return [
                opt for opt in p.get("Options", [])
                if not opt.get("Advanced", False)
            ]
    return []


@bp.route("/")
@login_required
def index():
    remotes = _get_remotes()
    remote_list = []
    for name, config in remotes.items():
        remote_list.append({
            "name": name,
            "type": config.get("type", "unknown"),
        })
    return render_template("rclone_config/list.html", remotes=remote_list)


@bp.route("/new")
@login_required
def new():
    providers = _get_providers()
    return render_template(
        "rclone_config/edit.html",
        is_new=True,
        remote_name="",
        provider_type="",
        providers=providers,
        fields=[],
        values={},
    )


@bp.route("/fields/<provider_type>")
@login_required
def fields(provider_type):
    providers = _get_providers()
    provider_names = [p["Name"] for p in providers]
    if provider_type not in provider_names:
        return '<div class="alert alert-error">Unknown provider type.</div>'
    options = _get_provider_options(provider_type)
    return render_template(
        "rclone_config/fields_partial.html",
        fields=options,
        values={},
    )


@bp.route("/create", methods=["POST"])
@login_required
def create():
    form = request.form
    remote_name = form.get("remote_name", "").strip()
    provider_type = form.get("provider_type", "").strip()

    if not remote_name or not _VALID_NAME_RE.match(remote_name):
        flash("Invalid remote name. Use only letters, numbers, hyphens, and underscores.", "error")
        return redirect(url_for("rclone_config.new"))

    providers = _get_providers()
    provider_names = [p["Name"] for p in providers]
    if provider_type not in provider_names:
        flash("Invalid provider type.", "error")
        return redirect(url_for("rclone_config.new"))

    # Check required fields
    options = _get_provider_options(provider_type)
    for opt in options:
        if opt.get("Required") and not form.get(opt["Name"], "").strip():
            flash(f"Field '{opt['Name']}' is required.", "error")
            return redirect(url_for("rclone_config.new"))

    # Build key=value pairs for rclone config create
    cmd = ["rclone", "config", "create", remote_name, provider_type]
    for opt in options:
        val = form.get(opt["Name"], "")
        if val:
            cmd.append(f"{opt['Name']}={val}")
    cmd += ["--non-interactive", "--obscure"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            flash(f"Remote '{remote_name}' created successfully.", "success")
        else:
            flash(f"Failed to create remote: {result.stderr.strip() or result.stdout.strip()}", "error")
    except (subprocess.TimeoutExpired, OSError) as e:
        flash(f"Failed to create remote: {e}", "error")

    return redirect(url_for("rclone_config.index"))


@bp.route("/<name>/edit")
@login_required
def edit(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid remote name.", "error")
        return redirect(url_for("rclone_config.index"))

    remotes = _get_remotes()
    if name not in remotes:
        flash(f"Remote '{name}' not found.", "error")
        return redirect(url_for("rclone_config.index"))

    config = remotes[name]
    provider_type = config.get("type", "")
    options = _get_provider_options(provider_type)
    providers = _get_providers()

    return render_template(
        "rclone_config/edit.html",
        is_new=False,
        remote_name=name,
        provider_type=provider_type,
        providers=providers,
        fields=options,
        values=config,
    )


@bp.route("/<name>/update", methods=["POST"])
@login_required
def update(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid remote name.", "error")
        return redirect(url_for("rclone_config.index"))

    remotes = _get_remotes()
    if name not in remotes:
        flash(f"Remote '{name}' not found.", "error")
        return redirect(url_for("rclone_config.index"))

    config = remotes[name]
    provider_type = config.get("type", "")
    options = _get_provider_options(provider_type)

    # Check required fields
    form = request.form
    for opt in options:
        if opt.get("Required") and not form.get(opt["Name"], "").strip():
            flash(f"Field '{opt['Name']}' is required.", "error")
            return redirect(url_for("rclone_config.edit", name=name))

    cmd = ["rclone", "config", "update", name]
    for opt in options:
        val = form.get(opt["Name"], "")
        if val:
            cmd.append(f"{opt['Name']}={val}")
    cmd += ["--non-interactive", "--obscure"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            flash(f"Remote '{name}' updated successfully.", "success")
        else:
            flash(f"Failed to update remote: {result.stderr.strip() or result.stdout.strip()}", "error")
    except (subprocess.TimeoutExpired, OSError) as e:
        flash(f"Failed to update remote: {e}", "error")

    return redirect(url_for("rclone_config.index"))


@bp.route("/<name>/delete", methods=["POST"])
@login_required
def delete(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid remote name.", "error")
        return redirect(url_for("rclone_config.index"))

    try:
        result = subprocess.run(
            ["rclone", "config", "delete", name],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            flash(f"Remote '{name}' deleted.", "success")
        else:
            flash(f"Failed to delete remote: {result.stderr.strip()}", "error")
    except (subprocess.TimeoutExpired, OSError) as e:
        flash(f"Failed to delete remote: {e}", "error")

    return redirect(url_for("rclone_config.index"))
