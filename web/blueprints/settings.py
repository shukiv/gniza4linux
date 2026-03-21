import os
import subprocess
import threading
from pathlib import Path

from flask import (
    Blueprint, render_template, render_template_string, request, redirect, url_for, flash,
)

from tui.config import CONFIG_DIR, parse_conf, write_conf
from tui.models import AppSettings
from web.app import login_required
from web.backend import run_cli_sync
from lib.notify_py import send_test_notification

bp = Blueprint("settings", __name__, url_prefix="/settings")

RESTART_WAIT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>GNIZA — Restarting</title>
<style>body{font-family:system-ui;background:#1d232a;color:#a6adbb;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.box{text-align:center}.spinner{width:40px;height:40px;border:4px solid #333;border-top-color:#6419e6;border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 1rem}
@keyframes spin{to{transform:rotate(360deg)}}</style></head>
<body><div class="box"><div class="spinner"></div><p>{{ message }}</p><p id="status" style="font-size:.85rem;opacity:.6">Waiting for service to come back...</p></div>
<script>
var url = "{{ redirect_url }}";
function check() {
    fetch(url, {method: 'HEAD', cache: 'no-store'})
        .then(function(r) { if (r.ok) window.location.href = url; else setTimeout(check, 1000); })
        .catch(function() { setTimeout(check, 1000); });
}
setTimeout(check, 3000);
</script></body></html>"""


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
    if request.args.get("restarted"):
        flash("Services restarted successfully.", "success")
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
        telegram_bot_token=form.get("telegram_bot_token", ""),
        telegram_chat_id=form.get("telegram_chat_id", ""),
        webhook_url=form.get("webhook_url", ""),
        webhook_type=form.get("webhook_type", "slack"),
        ntfy_url=form.get("ntfy_url", ""),
        ntfy_token=form.get("ntfy_token", ""),
        ntfy_priority=form.get("ntfy_priority", "default"),
        healthchecks_url=form.get("healthchecks_url", ""),
        stale_alert_hours=form.get("stale_alert_hours", "0"),
        ssh_timeout=form.get("ssh_timeout", "30"),
        ssh_retries=form.get("ssh_retries", "3"),
        rsync_extra_opts=form.get("rsync_extra_opts", ""),
        rsync_compress=form.get("rsync_compress", "no"),
        rsync_checksum="yes" if form.get("rsync_checksum") else "no",
        disk_usage_threshold=form.get("disk_usage_threshold", "95"),
        max_concurrent_jobs=form.get("max_concurrent_jobs", "1"),
        work_dir=form.get("work_dir", ""),
        web_port=form.get("web_port", "2323"),
        web_host=form.get("web_host", "0.0.0.0"),
        web_api_key=form.get("web_api_key", ""),
        login_max_attempts=form.get("login_max_attempts", "5"),
        login_lockout_seconds=form.get("login_lockout_seconds", "300"),
    )
    old_api_key = old_data.get("WEB_API_KEY", "")
    write_conf(CONFIG_DIR / "gniza.conf", settings.to_conf())

    import hmac
    if not hmac.compare_digest(settings.web_api_key, old_api_key):
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
        output = (stdout + stderr).strip()
        if "Already up to date" in output:
            flash("You are running the latest version.", "success")
        elif "commit(s) behind" in output:
            import re
            m = re.search(r'v([\d.]+)\s*\(', output)
            latest = re.search(r'Latest:\s*v([\d.]+)', output)
            behind = re.search(r'(\d+)\s*commit', output)
            msg = "A new update is available!"
            if latest:
                msg += f" Latest: v{latest.group(1)}"
            if behind:
                msg += f" ({behind.group(1)} commits behind)"
            msg += " Click 'Update Now' to apply."
            flash(msg, "warning")
        elif rc == 0:
            flash("You are running the latest version.", "success")
        else:
            flash(f"Update check failed: {output[:200]}", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("settings.index", tab="update"))


@bp.route("/restart-services", methods=["POST"])
@login_required
def restart_services():
    def _delayed_restart():
        import time
        time.sleep(2)
        if os.geteuid() == 0:
            subprocess.run(["systemctl", "restart", "gniza-web"], check=False)
            subprocess.run(["systemctl", "restart", "gniza-daemon"], check=False)
        else:
            subprocess.run(["systemctl", "--user", "restart", "gniza-web"], check=False)
            subprocess.run(["systemctl", "--user", "restart", "gniza-daemon"], check=False)
    threading.Thread(target=_delayed_restart, daemon=True).start()
    return render_template_string(RESTART_WAIT_PAGE,
                                  message="Restarting services...",
                                  redirect_url=url_for("settings.index", tab="update", restarted="1"))


@bp.route("/apply-update", methods=["POST"])
@login_required
def apply_update():
    try:
        rc, stdout, stderr = run_cli_sync("update", "--no-restart", timeout=120)
        if rc == 0:
            # Defer service restart so the HTTP response is sent first
            def _delayed_restart():
                import time
                time.sleep(2)
                if os.geteuid() == 0:
                    subprocess.run(["systemctl", "restart", "gniza-web"], check=False)
                    subprocess.run(["systemctl", "restart", "gniza-daemon"], check=False)
                else:
                    subprocess.run(["systemctl", "--user", "restart", "gniza-web"], check=False)
                    subprocess.run(["systemctl", "--user", "restart", "gniza-daemon"], check=False)
            threading.Thread(target=_delayed_restart, daemon=True).start()
            return render_template_string(RESTART_WAIT_PAGE,
                                          message="Update applied. Restarting services...",
                                          redirect_url=url_for("settings.index", tab="update", restarted="1"))
        else:
            flash(stderr.strip() or stdout.strip() or "Update failed.", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("settings.index", tab="update"))


@bp.route("/test-notification/<channel>", methods=["POST"])
@login_required
def test_notification(channel):
    try:
        ok, msg = send_test_notification(channel)
        flash(msg, "success" if ok else "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("settings.index", tab="notifications"))
