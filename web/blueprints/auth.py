import secrets
import time
from collections import defaultdict

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, current_app,
)

from tui.config import CONFIG_DIR, parse_conf

bp = Blueprint("auth", __name__)

# Brute-force protection: track failed attempts per IP
_failed_attempts = defaultdict(list)  # ip -> [timestamp, ...]


def _get_limits():
    """Read login limits from config (cached per request via app config)."""
    try:
        conf = parse_conf(CONFIG_DIR / "gniza.conf")
        max_attempts = max(1, int(conf.get("LOGIN_MAX_ATTEMPTS", "5")))
        lockout_seconds = max(10, int(conf.get("LOGIN_LOCKOUT_SECONDS", "300")))
    except (ValueError, TypeError):
        max_attempts, lockout_seconds = 5, 300
    return max_attempts, lockout_seconds


def _clean_old_attempts(ip, lockout_seconds):
    """Remove attempts older than the lockout window."""
    cutoff = time.monotonic() - lockout_seconds
    _failed_attempts[ip] = [t for t in _failed_attempts[ip] if t > cutoff]
    if not _failed_attempts[ip]:
        _failed_attempts.pop(ip, None)


def _is_locked(ip):
    """Check if IP is locked out. Returns (locked, seconds_remaining)."""
    max_attempts, lockout_seconds = _get_limits()
    _clean_old_attempts(ip, lockout_seconds)
    attempts = _failed_attempts.get(ip, [])
    if len(attempts) >= max_attempts:
        oldest = attempts[0]
        remaining = int(lockout_seconds - (time.monotonic() - oldest))
        return True, max(1, remaining)
    return False, 0


def _record_failure(ip):
    _failed_attempts[ip].append(time.monotonic())


def _clear_failures(ip):
    _failed_attempts.pop(ip, None)


@bp.route("/login", methods=["GET", "POST"])
def login():
    ip = request.remote_addr or "unknown"
    locked, remaining = _is_locked(ip)

    if request.method == "POST":
        if locked:
            flash(f"Too many failed attempts. Try again in {remaining} seconds.", "error")
            return render_template("auth/login.html", lockout_remaining=remaining)

        token = request.form.get("token", "")
        stored_key = current_app.config["API_KEY"]
        if token and secrets.compare_digest(token, stored_key):
            _clear_failures(ip)
            session.clear()
            session["logged_in"] = True
            return redirect(url_for("dashboard.index"))

        _record_failure(ip)
        # Check if this failure triggered a lockout
        locked, remaining = _is_locked(ip)
        if locked:
            flash(f"Too many failed attempts. Try again in {remaining} seconds.", "error")
            return render_template("auth/login.html", lockout_remaining=remaining)

        max_attempts, _ = _get_limits()
        attempts_left = max_attempts - len(_failed_attempts.get(ip, []))
        flash(f"Invalid API key. {attempts_left} attempt{'s' if attempts_left != 1 else ''} remaining.", "error")

    return render_template("auth/login.html", lockout_remaining=remaining if locked else 0)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
