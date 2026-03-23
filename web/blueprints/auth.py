import json
import logging
import secrets
import time

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, current_app,
)

from lib.config import CONFIG_DIR, parse_conf
from web.app import csrf

bp = Blueprint("auth", __name__)
audit = logging.getLogger("gniza.audit")

# Brute-force protection: file-backed to survive restarts
_LOCKOUT_FILE = None  # set lazily in _get_lockout_file()


def _get_lockout_file():
    global _LOCKOUT_FILE
    if _LOCKOUT_FILE is None:
        from lib.config import WORK_DIR
        _LOCKOUT_FILE = WORK_DIR / "login-attempts.json"
    return _LOCKOUT_FILE


def _load_attempts():
    f = _get_lockout_file()
    try:
        if f.is_file():
            data = json.loads(f.read_text())
            now = time.time()
            return {ip: [t for t in times if now - t < 3600]
                    for ip, times in data.items() if any(now - t < 3600 for t in times)}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_attempts(data):
    try:
        _get_lockout_file().write_text(json.dumps(data))
    except OSError:
        pass


_last_cleanup = 0.0


def _periodic_cleanup():
    """Remove stale entries from all IPs every 10 minutes."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < 600:
        return
    _last_cleanup = now
    data = _load_attempts()
    _save_attempts(data)


def _get_limits():
    """Read login limits from config (cached per request via app config)."""
    try:
        conf = parse_conf(CONFIG_DIR / "gniza.conf")
        max_attempts = max(1, int(conf.get("LOGIN_MAX_ATTEMPTS", "5")))
        lockout_seconds = max(10, int(conf.get("LOGIN_LOCKOUT_SECONDS", "300")))
    except (ValueError, TypeError):
        max_attempts, lockout_seconds = 5, 300
    return max_attempts, lockout_seconds


def _is_locked(ip):
    """Check if IP is locked out. Returns (locked, seconds_remaining)."""
    max_attempts, lockout_seconds = _get_limits()
    attempts = _load_attempts()
    cutoff = time.time() - lockout_seconds
    timestamps = [t for t in attempts.get(ip, []) if t > cutoff]
    if len(timestamps) >= max_attempts:
        oldest = timestamps[0]
        remaining = int(lockout_seconds - (time.time() - oldest))
        return True, max(1, remaining)
    return False, 0


def _record_failure(ip):
    attempts = _load_attempts()
    attempts.setdefault(ip, []).append(time.time())
    _save_attempts(attempts)


def _clear_failures(ip):
    attempts = _load_attempts()
    attempts.pop(ip, None)
    _save_attempts(attempts)


@bp.route("/login", methods=["GET", "POST"])
@csrf.exempt
def login():
    _periodic_cleanup()
    ip = request.remote_addr or "unknown"
    locked, remaining = _is_locked(ip)

    if request.method == "POST":
        if locked:
            audit.warning("Login BLOCKED (lockout) from %s", ip)
            flash(f"Too many failed attempts. Try again in {remaining} seconds.", "error")
            return render_template("auth/login.html", lockout_remaining=remaining)

        token = request.form.get("token", "")
        stored_key = current_app.config["API_KEY"]
        if token and secrets.compare_digest(token, stored_key):
            _clear_failures(ip)
            session.clear()
            session["logged_in"] = True
            session.permanent = True
            audit.info("Login SUCCESS from %s", ip)
            return redirect(url_for("dashboard.index"))

        _record_failure(ip)
        audit.warning("Login FAILED from %s", ip)
        # Check if this failure triggered a lockout
        locked, remaining = _is_locked(ip)
        if locked:
            flash(f"Too many failed attempts. Try again in {remaining} seconds.", "error")
            return render_template("auth/login.html", lockout_remaining=remaining)

        max_attempts, lockout_seconds = _get_limits()
        current = _load_attempts()
        cutoff = time.time() - lockout_seconds
        recent = [t for t in current.get(ip, []) if t > cutoff]
        attempts_left = max_attempts - len(recent)
        flash(f"Invalid password. {attempts_left} attempt{'s' if attempts_left != 1 else ''} remaining.", "error")

    return render_template("auth/login.html", lockout_remaining=remaining if locked else 0)


@bp.route("/logout")
def logout():
    audit.info("Logout from %s", request.remote_addr or "unknown")
    session.clear()
    return redirect(url_for("auth.login"))
