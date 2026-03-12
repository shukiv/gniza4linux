import os
import subprocess
import threading
from pathlib import Path

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import CONFIG_DIR, parse_conf, write_conf
from tui.models import AppSettings
from web.app import login_required
from web.backend import run_cli_sync
from daemon.notify import send_test_email

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/")
@login_required
def index():
    data = parse_conf(CONFIG_DIR / "gniza.conf")
    settings = AppSettings.from_conf(data)
    version = "unknown"
    gniza_dir = os.environ.get("GNIZA_DIR", str(Path(__file__).resolve().parent.parent.parent))
    constants_path = Path(gniza_dir) / "lib" / "constants.sh"
    if constants_path.exists():
        for line in constants_path.read_text().splitlines():
            if line.startswith("readonly GNIZA4LINUX_VERSION="):
                version = line.split('"')[1]
                break
    tab = request.args.get("tab", "general")
    return render_template("settings/index.html", settings=settings, version=version, active_tab=tab)


@bp.route("/", methods=["POST"])
@login_required
def save():
    form = request.form
    old_data = parse_conf(CONFIG_DIR / "gniza.conf")
    settings = AppSettings(
        backup_mode=old_data.get("BACKUP_MODE", "incremental"),
        bwlimit=form.get("bwlimit", "0"),
        retention_count=form.get("retention_count", "7"),
        log_level=form.get("log_level", "info"),
        log_retain=form.get("log_retain", "30"),
        notify_email=form.get("notify_email", ""),
        notify_on=form.get("notify_on", "failure"),
        smtp_host=form.get("smtp_host", ""),
        smtp_port=form.get("smtp_port", "587"),
        smtp_user=form.get("smtp_user", ""),
        smtp_password=form.get("smtp_password", ""),
        smtp_from=form.get("smtp_from", ""),
        smtp_security=form.get("smtp_security", "tls"),
        ssh_timeout=form.get("ssh_timeout", "30"),
        ssh_retries=form.get("ssh_retries", "3"),
        rsync_extra_opts=form.get("rsync_extra_opts", ""),
        rsync_compress=form.get("rsync_compress", "no"),
        rsync_checksum="yes" if form.get("rsync_checksum") else "no",
        disk_usage_threshold=form.get("disk_usage_threshold", "95"),
        max_concurrent_jobs=form.get("max_concurrent_jobs", "1"),
        web_port=form.get("web_port", "2323"),
        web_host=form.get("web_host", "0.0.0.0"),
        web_api_key=form.get("web_api_key", ""),
        login_max_attempts=form.get("login_max_attempts", "5"),
        login_lockout_seconds=form.get("login_lockout_seconds", "300"),
    )
    old_api_key = old_data.get("WEB_API_KEY", "")
    write_conf(CONFIG_DIR / "gniza.conf", settings.to_conf())

    if settings.web_api_key != old_api_key:
        flash("Settings saved. Password changed — restarting web service...", "success")

        def _delayed_restart():
            import time
            time.sleep(1)
            if os.geteuid() == 0:
                subprocess.run(["systemctl", "restart", "gniza-web"], check=False)
            else:
                subprocess.run(["systemctl", "--user", "restart", "gniza-web"], check=False)

        threading.Thread(target=_delayed_restart, daemon=True).start()
    else:
        flash("Settings saved.", "success")

    return redirect(url_for("settings.index"))


@bp.route("/check-update", methods=["POST"])
@login_required
def check_update():
    try:
        rc, stdout, stderr = run_cli_sync("update", "--check", timeout=60)
        if rc == 0:
            flash(stdout.strip() or "Already up to date.", "success")
        else:
            flash(stderr.strip() or stdout.strip() or "Update check failed.", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("settings.index", tab="update"))


@bp.route("/apply-update", methods=["POST"])
@login_required
def apply_update():
    try:
        rc, stdout, stderr = run_cli_sync("update", "--no-restart", timeout=120)
        if rc == 0:
            flash(stdout.strip() or "Update applied. Restarting services...", "success")
            # Defer service restart so the HTTP response is sent first
            def _delayed_restart():
                import time
                time.sleep(1)
                if os.geteuid() == 0:
                    subprocess.run(["systemctl", "restart", "gniza-web"], check=False)
                    subprocess.run(["systemctl", "restart", "gniza-daemon"], check=False)
                else:
                    subprocess.run(["systemctl", "--user", "restart", "gniza-web"], check=False)
                    subprocess.run(["systemctl", "--user", "restart", "gniza-daemon"], check=False)
            threading.Thread(target=_delayed_restart, daemon=True).start()
        else:
            flash(stderr.strip() or stdout.strip() or "Update failed.", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("settings.index", tab="update"))


@bp.route("/test-email", methods=["POST"])
@login_required
def test_email():
    try:
        ok, msg = send_test_email()
        flash(msg, "success" if ok else "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("settings.index", tab="email"))
