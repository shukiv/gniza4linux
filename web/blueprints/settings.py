from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import CONFIG_DIR, parse_conf, write_conf
from tui.models import AppSettings
from web.app import login_required

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/")
@login_required
def index():
    data = parse_conf(CONFIG_DIR / "gniza.conf")
    settings = AppSettings.from_conf(data)
    return render_template("settings/index.html", settings=settings)


@bp.route("/", methods=["POST"])
@login_required
def save():
    form = request.form
    settings = AppSettings(
        backup_mode=form.get("backup_mode", "incremental"),
        bwlimit=form.get("bwlimit", "0"),
        retention_count=form.get("retention_count", "7"),
        log_level=form.get("log_level", "INFO"),
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
        disk_usage_threshold=form.get("disk_usage_threshold", "95"),
        web_port=form.get("web_port", "2323"),
        web_host=form.get("web_host", "0.0.0.0"),
        web_api_key=form.get("web_api_key", ""),
    )
    write_conf(CONFIG_DIR / "gniza.conf", settings.to_conf())
    flash("Settings saved.", "success")
    return redirect(url_for("settings.index"))
