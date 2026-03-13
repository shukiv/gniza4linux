import json
import re
import subprocess
import threading

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    jsonify,
)

from web.app import login_required

# Background task tracking for OAuth flows
_bg_tasks = {}  # task_id -> {"status": "running"|"done"|"error", "result": ..., "error": ...}

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


def _rclone_config_create(name, ptype, params=None, state="", result_val=""):
    """Call rclone config create with optional state/result for multi-step flow.
    Returns (return_code, parsed_json_or_None, stderr)."""
    cmd = ["rclone", "config", "create", name, ptype]
    if params:
        for k, v in params.items():
            if v:
                cmd.append(f"{k}={v}")
    cmd.append("--non-interactive")
    cmd.append("--obscure")
    if state:
        cmd += ["--state", state]
    if result_val:
        cmd += ["--result", result_val]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                return proc.returncode, json.loads(proc.stdout), proc.stderr.strip()
            except json.JSONDecodeError:
                return proc.returncode, None, proc.stderr.strip()
        # Extract meaningful error — skip usage/help text
        err = proc.stderr.strip() or proc.stdout.strip()
        err_lines = [l for l in err.splitlines()
                     if l.strip() and not l.startswith("Usage:")
                     and not l.startswith("Flags:")
                     and not l.startswith("  --")
                     and not l.startswith("Use \"rclone")]
        err = err_lines[0] if err_lines else err.split("\n")[0]
        return proc.returncode, None, err
    except subprocess.TimeoutExpired:
        return 1, None, "Command timed out"
    except OSError as e:
        return 1, None, str(e)


# ── List ────────────────────────────────────────────────────

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


# ── Create: Step 1 — pick name + provider + fill fields ─────

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
        restore_step=None,
    )


@bp.route("/fields/<provider_type>")
@login_required
def fields(provider_type):
    advanced = request.args.get("advanced", "") == "1"
    providers = _get_providers()
    provider_names = [p["Name"] for p in providers]
    if provider_type not in provider_names:
        return '<div class="alert alert-error">Unknown provider type.</div>'
    all_opts = []
    for p in providers:
        if p.get("Name") == provider_type:
            all_opts = p.get("Options", [])
            break
    options = [o for o in all_opts if bool(o.get("Advanced", False)) == advanced]
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

    providers = _get_providers()

    if not remote_name or not _VALID_NAME_RE.match(remote_name):
        flash("Invalid remote name. Use only letters, numbers, hyphens, and underscores.", "error")
        return redirect(url_for("rclone_config.new"))

    provider_names = [p["Name"] for p in providers]
    if provider_type not in provider_names:
        flash("Invalid provider type.", "error")
        return redirect(url_for("rclone_config.new"))

    # Get ALL options (non-advanced + advanced) for this provider
    all_options = []
    for p in providers:
        if p.get("Name") == provider_type:
            all_options = p.get("Options", [])
            break

    # Collect submitted values for re-rendering on error
    submitted_values = {}
    for opt in all_options:
        val = form.get(opt["Name"], "")
        if val:
            submitted_values[opt["Name"]] = val

    # Check required non-advanced fields
    for opt in all_options:
        if not opt.get("Advanced") and opt.get("Required") and not form.get(opt["Name"], "").strip():
            flash(f"Field '{opt['Name']}' is required.", "error")
            non_adv = [o for o in all_options if not o.get("Advanced")]
            return render_template(
                "rclone_config/edit.html",
                is_new=True,
                remote_name=remote_name,
                provider_type=provider_type,
                providers=providers,
                fields=non_adv,
                values=submitted_values,
                restore_step=2,
            )

    # Build params from all submitted form fields
    params = {}
    for opt in all_options:
        val = form.get(opt["Name"], "")
        if val:
            params[opt["Name"]] = val

    rc, data, err = _rclone_config_create(remote_name, provider_type, params=params)

    # Check if rclone needs more steps (OAuth, etc.)
    if data and data.get("State") and data.get("Option"):
        # Store wizard state in session
        session["rclone_wizard"] = {
            "name": remote_name,
            "type": provider_type,
            "state": data["State"],
            "option": data["Option"],
            "step": 2,
        }
        return redirect(url_for("rclone_config.wizard_step"))

    if rc == 0:
        flash(f"Remote '{remote_name}' created successfully.", "success")
    else:
        flash(f"Failed to create remote: {err}", "error")

    return redirect(url_for("rclone_config.index"))


# ── Create: Step 2+ — wizard follow-up questions ────────────

def _run_bg_config(task_id, name, ptype, state, result_val):
    """Run rclone config create in background thread (for OAuth flows)."""
    rc, data, err = _rclone_config_create(name, ptype, state=state, result_val=result_val)
    if data and data.get("State") and data.get("Option"):
        _bg_tasks[task_id] = {"status": "more_steps", "data": data}
    elif rc == 0:
        _bg_tasks[task_id] = {"status": "done", "name": name}
    else:
        _bg_tasks[task_id] = {"status": "error", "error": err, "name": name}


@bp.route("/wizard", methods=["GET", "POST"])
@login_required
def wizard_step():
    wiz = session.get("rclone_wizard")
    if not wiz:
        flash("No wizard in progress.", "error")
        return redirect(url_for("rclone_config.index"))

    if request.method == "POST":
        answer = request.form.get("answer", "")

        # For OAuth auto-config steps, run in background and show waiting page
        option = wiz.get("option", {})
        is_oauth_step = option.get("Name") in ("config_is_local", "config_token")

        if is_oauth_step and answer.lower() in ("true", "yes"):
            import secrets
            task_id = secrets.token_hex(8)
            _bg_tasks[task_id] = {"status": "running"}
            t = threading.Thread(
                target=_run_bg_config,
                args=(task_id, wiz["name"], wiz["type"], wiz["state"], answer),
                daemon=True,
            )
            t.start()
            return render_template(
                "rclone_config/waiting.html",
                name=wiz["name"],
                provider_type=wiz["type"],
                task_id=task_id,
            )

        # Non-OAuth steps: run synchronously
        rc, data, err = _rclone_config_create(
            wiz["name"], wiz["type"],
            state=wiz["state"], result_val=answer,
        )

        if data and data.get("State") and data.get("Option"):
            session["rclone_wizard"] = {
                "name": wiz["name"],
                "type": wiz["type"],
                "state": data["State"],
                "option": data["Option"],
                "step": wiz["step"] + 1,
            }
            return redirect(url_for("rclone_config.wizard_step"))

        session.pop("rclone_wizard", None)
        if rc == 0:
            flash(f"Remote '{wiz['name']}' created successfully.", "success")
        else:
            flash(f"Failed to create remote: {err}", "error")
        return redirect(url_for("rclone_config.index"))

    # GET — render the current question
    option = wiz["option"]
    return render_template(
        "rclone_config/wizard_step.html",
        name=wiz["name"],
        provider_type=wiz["type"],
        step=wiz["step"],
        option=option,
    )


@bp.route("/wizard/poll/<task_id>")
@login_required
def wizard_poll(task_id):
    """Poll background OAuth task status."""
    task = _bg_tasks.get(task_id)
    if not task:
        return jsonify({"status": "error", "error": "Task not found"})
    if task["status"] == "running":
        return jsonify({"status": "running"})
    # Clean up completed task
    _bg_tasks.pop(task_id, None)
    if task["status"] == "done":
        session.pop("rclone_wizard", None)
        return jsonify({"status": "done", "redirect": url_for("rclone_config.index")})
    if task["status"] == "more_steps":
        data = task["data"]
        wiz = session.get("rclone_wizard", {})
        session["rclone_wizard"] = {
            "name": wiz.get("name", ""),
            "type": wiz.get("type", ""),
            "state": data["State"],
            "option": data["Option"],
            "step": wiz.get("step", 2) + 1,
        }
        return jsonify({"status": "done", "redirect": url_for("rclone_config.wizard_step")})
    return jsonify({"status": "error", "error": task.get("error", "Unknown error")})


# ── Edit ─────────────────────────────────────────────────────

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


# ── Delete ───────────────────────────────────────────────────

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
