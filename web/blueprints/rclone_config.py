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

def _ensure_noop_xdg_open():
    """Create a no-op xdg-open script so rclone can't open a browser."""
    import os, stat, tempfile
    noop_dir = os.path.join(tempfile.gettempdir(), "rclone-nobrowser")
    noop_script = os.path.join(noop_dir, "xdg-open")
    if not os.path.exists(noop_script):
        os.makedirs(noop_dir, exist_ok=True)
        with open(noop_script, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(noop_script, stat.S_IRWXU)
    return noop_dir


def _serve_redirect_on_port(port, redirect_url, timeout_secs=30):
    """Start a tiny HTTP server on the given port that redirects all requests.

    After rclone's OAuth server shuts down, we take over port 53682 and serve
    a page that auto-redirects the browser back to gniza.  Runs in a daemon
    thread and shuts down after *timeout_secs*.
    """
    import http.server
    import time

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", redirect_url)
            self.end_headers()

        def log_message(self, *args):
            pass  # silence logs

    start = time.time()
    while time.time() - start < 5:
        try:
            srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            time.sleep(0.3)
    else:
        return  # couldn't bind

    srv.timeout = 1
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        srv.handle_request()
    srv.server_close()


def _run_bg_config(task_id, name, ptype, state, result_val, redirect_base=""):
    """Run rclone config create in background thread (for OAuth flows).

    Suppresses rclone's browser opening by prepending a no-op xdg-open to PATH,
    then captures the auth URL from rclone's stderr NOTICE line so the waiting
    page can display it as a clickable link.  After rclone finishes, takes over
    port 53682 to redirect the Success page back to gniza.
    """
    import os

    cmd = ["rclone", "config", "create", name, ptype,
           "--non-interactive", "--obscure"]
    if state:
        cmd += ["--state", state]
    if result_val:
        cmd += ["--result", result_val]

    # Prepend a dir with a no-op xdg-open so rclone can't open a browser
    noop_dir = _ensure_noop_xdg_open()
    env = os.environ.copy()
    env["PATH"] = noop_dir + ":" + env.get("PATH", "")

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env,
        )

        # Read stderr line by line to capture the auth URL early
        stderr_lines = []
        for line in proc.stderr:
            stderr_lines.append(line)
            # rclone prints: "NOTICE: If your browser doesn't open automatically
            #   go to the following link: http://127.0.0.1:53682/auth?state=..."
            if "http" in line:
                url_match = re.search(r'(https?://\S+)', line)
                if url_match:
                    _bg_tasks[task_id]["auth_url"] = url_match.group(1)

        stdout = proc.stdout.read()
        proc.wait(timeout=120)

        rc = proc.returncode
        data = None
        if rc == 0 and stdout.strip():
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                pass

        if data and data.get("State") and data.get("Option"):
            _bg_tasks[task_id].update({"status": "more_steps", "data": data})
        elif rc == 0:
            _bg_tasks[task_id].update({"status": "done", "name": name})
        else:
            err = "".join(stderr_lines).strip() or stdout.strip()
            err_lines = [l for l in err.splitlines()
                         if l.strip() and not l.startswith("Usage:")
                         and not l.startswith("Flags:")
                         and not l.startswith("  --")
                         and not l.startswith("Use \"rclone")]
            err = err_lines[0] if err_lines else err.split("\n")[0]
            _bg_tasks[task_id].update({"status": "error", "error": err, "name": name})

        # After rclone exits, take over port 53682 to redirect the browser
        # tab (which is showing rclone's "Success!" page) back to gniza.
        redirect_url = (redirect_base.rstrip("/") + "/rclone-config/") if redirect_base else "http://localhost:2323/rclone-config/"
        threading.Thread(
            target=_serve_redirect_on_port,
            args=(53682, redirect_url),
            daemon=True,
        ).start()

    except subprocess.TimeoutExpired:
        proc.kill()
        _bg_tasks[task_id].update({"status": "error", "error": "Command timed out", "name": name})
    except OSError as e:
        _bg_tasks[task_id].update({"status": "error", "error": str(e), "name": name})


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
            host_url = request.host_url  # e.g. "http://localhost:2323/"
            t = threading.Thread(
                target=_run_bg_config,
                args=(task_id, wiz["name"], wiz["type"], wiz["state"], answer),
                kwargs={"redirect_base": host_url},
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
        resp = {"status": "running"}
        if task.get("auth_url"):
            resp["auth_url"] = task["auth_url"]
        return jsonify(resp)
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


# ── Test ──────────────────────────────────────────────────────

@bp.route("/<name>/test", methods=["POST"])
@login_required
def test(name):
    """Test an rclone remote by running 'rclone about <remote>:'."""
    if not _VALID_NAME_RE.match(name):
        return jsonify({"ok": False, "error": "Invalid remote name."})

    remotes = _get_remotes()
    if name not in remotes:
        return jsonify({"ok": False, "error": "Remote not found."})

    try:
        result = subprocess.run(
            ["rclone", "about", f"{name}:", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            try:
                info = json.loads(result.stdout)
                parts = []
                if "total" in info:
                    total_gb = info["total"] / (1024**3)
                    parts.append(f"Total: {total_gb:.1f} GB")
                if "used" in info:
                    used_gb = info["used"] / (1024**3)
                    parts.append(f"Used: {used_gb:.1f} GB")
                if "free" in info:
                    free_gb = info["free"] / (1024**3)
                    parts.append(f"Free: {free_gb:.1f} GB")
                detail = " | ".join(parts) if parts else "Connected"
                return jsonify({"ok": True, "detail": detail})
            except (json.JSONDecodeError, KeyError):
                return jsonify({"ok": True, "detail": "Connected"})
        # about not supported — fall back to lsd
        result2 = subprocess.run(
            ["rclone", "lsd", f"{name}:", "--max-depth", "0"],
            capture_output=True, text=True, timeout=30,
        )
        if result2.returncode == 0:
            return jsonify({"ok": True, "detail": "Connected"})
        err = result.stderr.strip() or result2.stderr.strip()
        return jsonify({"ok": False, "error": err.split("\n")[0] if err else "Connection failed"})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Connection timed out"})
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)})


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
