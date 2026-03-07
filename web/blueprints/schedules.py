import os
import re

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import CONFIG_DIR, parse_conf, write_conf, list_conf_dir
from tui.models import Schedule
from web.app import login_required

bp = Blueprint("schedules", __name__, url_prefix="/schedules")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')


def _load_schedules():
    schedules = []
    for name in list_conf_dir("schedules.d"):
        data = parse_conf(CONFIG_DIR / "schedules.d" / f"{name}.conf")
        schedules.append(Schedule.from_conf(name, data))
    return schedules


@bp.route("/")
@login_required
def index():
    try:
        schedules = _load_schedules()
    except Exception:
        schedules = []
        flash("Failed to load schedules.", "error")
    return render_template("schedules/list.html", schedules=schedules)


@bp.route("/new")
@login_required
def new():
    schedule = Schedule()
    targets = list_conf_dir("targets.d")
    remotes = list_conf_dir("remotes.d")
    return render_template("schedules/edit.html", schedule=schedule, targets=targets, remotes=remotes, is_new=True)


@bp.route("/<name>/edit")
@login_required
def edit(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid name.", "error")
        return redirect(url_for("schedules.index"))
    conf_path = CONFIG_DIR / "schedules.d" / f"{name}.conf"
    if not conf_path.is_file():
        flash("Schedule not found.", "error")
        return redirect(url_for("schedules.index"))
    data = parse_conf(conf_path)
    schedule = Schedule.from_conf(name, data)
    targets = list_conf_dir("targets.d")
    remotes = list_conf_dir("remotes.d")
    return render_template("schedules/edit.html", schedule=schedule, targets=targets, remotes=remotes, is_new=False)


@bp.route("/save", methods=["POST"])
@login_required
def save():
    form = request.form
    name = form.get("name", "").strip()
    original_name = form.get("original_name", "").strip()

    if not name or not _VALID_NAME_RE.match(name):
        flash("Invalid name. Use only letters, numbers, hyphens, and underscores.", "error")
        return redirect(url_for("schedules.index"))

    if original_name and original_name != name:
        if not _VALID_NAME_RE.match(original_name):
            flash("Invalid original name.", "error")
            return redirect(url_for("schedules.index"))
        old_path = CONFIG_DIR / "schedules.d" / f"{original_name}.conf"
        if old_path.is_file():
            os.unlink(old_path)

    schedule_type = form.get("schedule", "daily")

    day = ""
    if schedule_type == "daily":
        day = ",".join(form.getlist("day"))
    elif schedule_type == "weekly":
        day = form.get("weekly_day", "")
    elif schedule_type == "monthly":
        day = form.get("monthly_day", "")
    elif schedule_type == "hourly":
        day = form.get("hourly_interval", "1")

    selected_targets = form.getlist("targets")
    selected_remotes = form.getlist("remotes")

    schedule = Schedule(
        name=name,
        schedule=schedule_type,
        time=form.get("time", "02:00"),
        day=day,
        cron=form.get("cron", ""),
        targets=",".join(selected_targets),
        remotes=",".join(selected_remotes),
        active="yes" if form.get("active") else "no",
        retention_count=form.get("retention_count", ""),
    )

    conf_dir = CONFIG_DIR / "schedules.d"
    conf_dir.mkdir(parents=True, exist_ok=True)
    write_conf(conf_dir / f"{schedule.name}.conf", schedule.to_conf())
    flash(f"Schedule '{schedule.name}' saved.", "success")
    return redirect(url_for("schedules.index"))


@bp.route("/<name>/delete", methods=["POST"])
@login_required
def delete(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid name.", "error")
        return redirect(url_for("schedules.index"))
    conf_path = CONFIG_DIR / "schedules.d" / f"{name}.conf"
    if conf_path.is_file():
        os.unlink(conf_path)
        flash(f"Schedule '{name}' deleted.", "success")
    else:
        flash("Schedule not found.", "error")
    return redirect(url_for("schedules.index"))


@bp.route("/<name>/toggle", methods=["POST"])
@login_required
def toggle(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid name.", "error")
        return redirect(url_for("schedules.index"))
    conf_path = CONFIG_DIR / "schedules.d" / f"{name}.conf"
    if not conf_path.is_file():
        flash("Schedule not found.", "error")
        return redirect(url_for("schedules.index"))
    data = parse_conf(conf_path)
    schedule = Schedule.from_conf(name, data)
    schedule.active = "no" if schedule.active == "yes" else "yes"
    write_conf(conf_path, schedule.to_conf())
    flash(f"Schedule '{name}' {'activated' if schedule.active == 'yes' else 'deactivated'}.", "success")
    return redirect(url_for("schedules.index"))
