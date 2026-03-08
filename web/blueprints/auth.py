import secrets
import time
from collections import defaultdict

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, current_app,
)

bp = Blueprint("auth", __name__)

# Brute-force protection: track failed attempts per IP
_failed_attempts = defaultdict(list)  # ip -> [timestamp, ...]
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300  # 5 minutes


def _clean_old_attempts(ip):
    """Remove attempts older than the lockout window."""
    cutoff = time.monotonic() - _LOCKOUT_SECONDS
    _failed_attempts[ip] = [t for t in _failed_attempts[ip] if t > cutoff]
    if not _failed_attempts[ip]:
        _failed_attempts.pop(ip, None)


def _is_locked(ip):
    """Check if IP is locked out. Returns (locked, seconds_remaining)."""
    _clean_old_attempts(ip)
    attempts = _failed_attempts.get(ip, [])
    if len(attempts) >= _MAX_ATTEMPTS:
        oldest = attempts[0]
        remaining = int(_LOCKOUT_SECONDS - (time.monotonic() - oldest))
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

        attempts_left = _MAX_ATTEMPTS - len(_failed_attempts.get(ip, []))
        flash(f"Invalid API key. {attempts_left} attempt{'s' if attempts_left != 1 else ''} remaining.", "error")

    return render_template("auth/login.html", lockout_remaining=remaining if locked else 0)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
