from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import CONFIG_DIR, list_conf_dir, parse_conf, update_conf_key
from web.app import login_required
from web.helpers import _VALID_NAME_RE
from web.jobs import web_job_manager

bp = Blueprint("retention", __name__, url_prefix="/retention")


@bp.route("/")
@login_required
def index():
    targets = list_conf_dir("targets.d")
    data = parse_conf(CONFIG_DIR / "gniza.conf")
    retention_count = data.get("RETENTION_COUNT", "30")
    return render_template("retention/index.html", targets=targets, retention_count=retention_count)


@bp.route("/run", methods=["POST"])
@login_required
def run():
    target_name = request.form.get("target", "").strip()

    if target_name and not _VALID_NAME_RE.match(target_name):
        flash("Invalid source name.", "error")
        return redirect(url_for("retention.index"))

    args = ["retention"]
    label_parts = ["Retention"]

    if target_name:
        args.append(f"--source={target_name}")
        label_parts.append(target_name)
    else:
        args.append("--all")
        label_parts.append("(all)")

    label = " ".join(label_parts)
    web_job_manager.create_and_start("retention", label, *args)
    flash(f"Retention job started: {label}", "success")
    return redirect(url_for("jobs.index"))


@bp.route("/save-default", methods=["POST"])
@login_required
def save_default():
    retention_count = request.form.get("retention_count", "").strip()
    if not retention_count.isdigit() or int(retention_count) < 1:
        flash("Retention count must be a positive number.", "error")
        return redirect(url_for("retention.index"))
    update_conf_key(CONFIG_DIR / "gniza.conf", "RETENTION_COUNT", retention_count)
    flash(f"Default retention count set to {retention_count}.", "success")
    return redirect(url_for("retention.index"))
