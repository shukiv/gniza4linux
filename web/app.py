import hashlib
import secrets
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask, request, redirect, url_for,
    session, jsonify,
)

from tui.config import CONFIG_DIR, parse_conf


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def create_app():
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
    )

    conf = parse_conf(CONFIG_DIR / "gniza.conf")
    stored_key = conf.get("WEB_API_KEY", "")
    if not stored_key:
        stored_key = secrets.token_urlsafe(32)
        print(f"\n{'='*60}")
        print(f"  No WEB_API_KEY configured.")
        print(f"  Set WEB_API_KEY in gniza.conf for persistent access.")
        print(f"{'='*60}\n")

    # Derive secret_key from API key — never use the credential itself as signing key
    app.secret_key = hashlib.sha256(
        b"gniza-flask-session:" + stored_key.encode()
    ).hexdigest()
    app.config["API_KEY"] = stored_key
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = 86400  # 24 hours

    # Navigation items for template context
    nav_items = [
        {"name": "Dashboard", "endpoint": "dashboard.index", "active": True},
        {"name": "Sources", "endpoint": "targets.index", "active": False},
        {"name": "Destinations", "endpoint": "remotes.index", "active": False},
        {"name": "Backup", "endpoint": "backup.index", "active": False},
        {"name": "Restore", "endpoint": "restore.index", "active": False},
        {"name": "Running Tasks", "endpoint": "jobs.index", "active": False},
        {"name": "Schedules", "endpoint": "schedules.index", "active": False},
        {"name": "Snapshots", "endpoint": "snapshots.index", "active": False},
        {"name": "Logs", "endpoint": "logs.index", "active": False},
        {"name": "Email Log", "endpoint": "email_log.index", "active": False},
        {"name": "Settings", "endpoint": "settings.index", "active": False},
        {"name": "Docs", "endpoint": "docs.index", "active": False},
        {"name": "Health", "endpoint": "health.index", "active": False},
    ]

    @app.context_processor
    def inject_globals():
        active_page = ""
        if request.endpoint:
            if request.endpoint.startswith("dashboard"):
                active_page = "dashboard"
            elif request.endpoint.startswith("targets"):
                active_page = "sources"
            elif request.endpoint.startswith("remotes"):
                active_page = "destinations"
            elif request.endpoint.startswith("backup"):
                active_page = "backup"
            elif request.endpoint.startswith("restore"):
                active_page = "restore"
            elif request.endpoint.startswith("jobs"):
                active_page = "running tasks"
            elif request.endpoint.startswith("schedules"):
                active_page = "schedules"
            elif request.endpoint.startswith("snapshots"):
                active_page = "snapshots"
            elif request.endpoint.startswith("email_log"):
                active_page = "email log"
            elif request.endpoint.startswith("logs"):
                active_page = "logs"
            elif request.endpoint.startswith("settings"):
                active_page = "settings"
            elif request.endpoint.startswith("docs"):
                active_page = "docs"
            elif request.endpoint.startswith("health"):
                active_page = "health"
        return {
            "nav_items": nav_items,
            "active_page": active_page,
            "app_name": "GNIZA",
            "app_version": "0.2.2",
            "current_year": datetime.now().year,
        }

    from web.blueprints.auth import bp as auth_bp
    from web.blueprints.dashboard import bp as dashboard_bp
    from web.blueprints.targets import bp as targets_bp
    from web.blueprints.remotes import bp as remotes_bp
    from web.blueprints.settings import bp as settings_bp
    from web.blueprints.backup import bp as backup_bp
    from web.blueprints.jobs import bp as jobs_bp
    from web.blueprints.restore import bp as restore_bp
    from web.blueprints.schedules import bp as schedules_bp
    from web.blueprints.snapshots import bp as snapshots_bp
    from web.blueprints.logs import bp as logs_bp
    from web.blueprints.email_log import bp as email_log_bp
    from web.blueprints.wizard import bp as wizard_bp
    from web.blueprints.api import bp as api_bp
    from web.blueprints.docs import bp as docs_bp
    from web.blueprints.health import bp as health_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(targets_bp)
    app.register_blueprint(remotes_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(restore_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(snapshots_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(email_log_bp)
    app.register_blueprint(wizard_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(docs_bp)
    app.register_blueprint(health_bp)

    return app
