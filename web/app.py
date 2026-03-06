import os
import re
import subprocess
import secrets
from pathlib import Path
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash,
)

CONFIG_DIR = Path(os.environ.get("GNIZA_CONFIG_DIR", "/usr/local/gniza/etc"))
LOG_DIR = Path(os.environ.get("LOG_DIR", "/var/log/gniza"))


def _gniza_bin():
    gniza_dir = os.environ.get("GNIZA_DIR", "")
    if gniza_dir:
        return str(Path(gniza_dir) / "bin" / "gniza")
    here = Path(__file__).resolve().parent.parent / "bin" / "gniza"
    if here.is_file():
        return str(here)
    return "gniza"


def parse_conf(filepath):
    data = {}
    if not filepath.is_file():
        return data
    kv_re = re.compile(r'^([A-Z_][A-Z0-9_]*)="(.*)"$')
    for line in filepath.read_text().splitlines():
        line = line.strip()
        m = kv_re.match(line)
        if m:
            data[m.group(1)] = m.group(2)
    return data


def list_conf_dir(subdir):
    d = CONFIG_DIR / subdir
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.conf"))


def _get_api_key():
    conf = parse_conf(CONFIG_DIR / "gniza.conf")
    return conf.get("WEB_API_KEY", "")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def create_app():
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
    )

    stored_key = _get_api_key()
    if not stored_key:
        stored_key = secrets.token_urlsafe(32)
        print(f"\n{'='*60}")
        print(f"  No WEB_API_KEY configured.")
        print(f"  Generated temporary key: {stored_key}")
        print(f"  Set WEB_API_KEY in gniza.conf to persist this key.")
        print(f"{'='*60}\n")

    app.secret_key = stored_key

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            token = request.form.get("token", "")
            if token and secrets.compare_digest(token, stored_key):
                session["authenticated"] = True
                return redirect(url_for("dashboard"))
            flash("Invalid API key.")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        targets = _load_targets()
        remotes = _load_remotes()
        schedules = _load_schedules()
        last_log = _last_log_info()
        return render_template(
            "dashboard.html",
            targets=targets,
            remotes=remotes,
            schedules=schedules,
            last_log=last_log,
        )

    @app.route("/api/targets")
    @login_required
    def api_targets():
        return jsonify(_load_targets())

    @app.route("/api/remotes")
    @login_required
    def api_remotes():
        return jsonify(_load_remotes())

    @app.route("/api/schedules")
    @login_required
    def api_schedules():
        return jsonify(_load_schedules())

    @app.route("/api/logs")
    @login_required
    def api_logs():
        name = request.args.get("name")
        if name:
            safe_name = Path(name).name
            log_path = LOG_DIR / safe_name
            if not log_path.is_file() or not str(log_path.resolve()).startswith(str(LOG_DIR.resolve())):
                return jsonify({"error": "not found"}), 404
            return jsonify({"name": safe_name, "content": log_path.read_text(errors="replace")})
        files = []
        if LOG_DIR.is_dir():
            for p in sorted(LOG_DIR.glob("gniza-*.log"), key=lambda x: x.stat().st_mtime, reverse=True):
                files.append({"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime})
        return jsonify(files)

    @app.route("/api/status")
    @login_required
    def api_status():
        targets = _load_targets()
        enabled = sum(1 for t in targets if t.get("enabled") == "yes")
        last = _last_log_info()
        return jsonify({
            "targets_total": len(targets),
            "targets_enabled": enabled,
            "remotes_total": len(list_conf_dir("remotes.d")),
            "schedules_total": len(list_conf_dir("schedules.d")),
            "last_log": last,
        })

    @app.route("/api/backup", methods=["POST"])
    @login_required
    def api_backup():
        if request.is_json:
            target = (request.json or {}).get("target", "")
        else:
            target = request.form.get("target", "")
        if not target:
            return jsonify({"error": "target parameter required"}), 400
        safe_target = re.sub(r'[^a-zA-Z0-9_.-]', '', target)
        if not safe_target:
            return jsonify({"error": "invalid target name"}), 400
        try:
            subprocess.Popen(
                [_gniza_bin(), "--cli", "backup", f"--target={safe_target}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"status": "started", "target": safe_target})

    return app


def _load_targets():
    targets = []
    for name in list_conf_dir("targets.d"):
        conf = parse_conf(CONFIG_DIR / "targets.d" / f"{name}.conf")
        targets.append({
            "name": conf.get("TARGET_NAME", name),
            "folders": conf.get("TARGET_FOLDERS", ""),
            "remote": conf.get("TARGET_REMOTE", ""),
            "enabled": conf.get("TARGET_ENABLED", "yes"),
        })
    return targets


def _load_remotes():
    remotes = []
    for name in list_conf_dir("remotes.d"):
        conf = parse_conf(CONFIG_DIR / "remotes.d" / f"{name}.conf")
        remotes.append({
            "name": name,
            "type": conf.get("REMOTE_TYPE", "ssh"),
            "host": conf.get("REMOTE_HOST", ""),
            "base": conf.get("REMOTE_BASE", ""),
        })
    return remotes


def _load_schedules():
    schedules = []
    for name in list_conf_dir("schedules.d"):
        conf = parse_conf(CONFIG_DIR / "schedules.d" / f"{name}.conf")
        schedules.append({
            "name": name,
            "schedule": conf.get("SCHEDULE", "daily"),
            "time": conf.get("SCHEDULE_TIME", ""),
            "active": conf.get("SCHEDULE_ACTIVE", "yes"),
            "targets": conf.get("TARGETS", ""),
        })
    return schedules


def _last_log_info():
    if not LOG_DIR.is_dir():
        return None
    logs = sorted(LOG_DIR.glob("gniza-*.log"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not logs:
        return None
    latest = logs[0]
    lines = latest.read_text(errors="replace").splitlines()
    last_lines = lines[-10:] if len(lines) > 10 else lines
    status = "unknown"
    for line in reversed(lines):
        if "completed successfully" in line.lower() or "backup done" in line.lower():
            status = "success"
            break
        if "error" in line.lower() or "failed" in line.lower():
            status = "error"
            break
    return {
        "name": latest.name,
        "mtime": latest.stat().st_mtime,
        "status": status,
        "tail": "\n".join(last_lines),
    }
