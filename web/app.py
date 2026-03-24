import hashlib
import re
import secrets
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask, request, redirect, url_for,
    session, jsonify,
)
from flask_wtf.csrf import CSRFProtect

from lib.config import CONFIG_DIR, parse_conf


def _get_version():
    try:
        constants = Path(__file__).resolve().parent.parent / "lib" / "constants.sh"
        for line in constants.read_text().splitlines():
            m = re.match(r'(?:readonly\s+)?GNIZA4LINUX_VERSION="([^"]+)"', line)
            if m:
                return m.group(1)
    except Exception:
        pass
    return "0.0"

csrf = CSRFProtect()


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
        print(f"  No WEB_API_KEY (password) configured.")
        print(f"  Set WEB_API_KEY in gniza.conf to set a password.")
        print(f"{'='*60}\n")

    # Read or generate salt
    salt = conf.get("WEB_SALT", "")
    if not salt:
        # Use a deterministic fallback based on the machine ID + install path
        try:
            machine_id = Path("/etc/machine-id").read_text().strip()
        except Exception:
            machine_id = str(Path(__file__).resolve())
        salt = hashlib.sha256(machine_id.encode()).hexdigest()[:32]

    # Derive secret_key from password — never use the credential itself as signing key
    app.secret_key = hashlib.pbkdf2_hmac(
        'sha256', stored_key.encode(), salt.encode(), 100_000
    ).hex()
    app.config["API_KEY"] = stored_key
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Set Secure flag when accessed over HTTPS (auto-detected from config or proxy)
    app.config["SESSION_COOKIE_SECURE"] = conf.get("WEB_SECURE_COOKIE", "") == "yes"
    app.config["PERMANENT_SESSION_LIFETIME"] = 86400  # 24 hours

    # CSRF protection
    csrf.init_app(app)

    # Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        return response

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
        {"name": "Notification Log", "endpoint": "notification_log.index", "active": False},
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
            elif request.endpoint.startswith("notification_log"):
                active_page = "notification log"
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
            "app_version": _get_version(),
            "current_year": datetime.now().year,
        }

    # Jinja filter: convert URLs in text to clickable links
    _url_re = re.compile(r'(https?://[^\s<>"\']+)')

    @app.template_filter("linkify")
    def linkify_filter(text):
        from markupsafe import Markup, escape
        escaped = str(escape(text))
        result = _url_re.sub(r'<a href="\1" target="_blank" class="link link-primary">\1</a>', escaped)
        return Markup(result)

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
    from web.blueprints.notification_log import bp as notification_log_bp
    from web.blueprints.wizard import bp as wizard_bp
    from web.blueprints.api import bp as api_bp
    from web.blueprints.docs import bp as docs_bp
    from web.blueprints.health import bp as health_bp
    from web.blueprints.rclone_config import bp as rclone_config_bp
    from web.blueprints.retention import bp as retention_bp

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
    app.register_blueprint(notification_log_bp)
    app.register_blueprint(wizard_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(docs_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(rclone_config_bp)
    app.register_blueprint(retention_bp)

    return app
