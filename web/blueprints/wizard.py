import re

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import CONFIG_DIR, parse_conf, write_conf, list_conf_dir
from tui.models import Remote, Target, Schedule
from web.app import login_required

bp = Blueprint("wizard", __name__, url_prefix="/wizard")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')


@bp.route("/")
@login_required
def index():
    targets = list_conf_dir("targets.d")
    remotes = list_conf_dir("remotes.d")
    schedules = list_conf_dir("schedules.d")
    return render_template("wizard/index.html", targets=targets, remotes=remotes, schedules=schedules)


@bp.route("/step/<int:n>", methods=["POST"])
@login_required
def step(n):
    form = request.form

    if n == 1:
        api_key = form.get("api_key", "").strip()
        if api_key:
            conf_path = CONFIG_DIR / "gniza.conf"
            data = parse_conf(conf_path) if conf_path.is_file() else {}
            data["WEB_API_KEY"] = api_key
            write_conf(conf_path, data)
            flash("API key saved.", "success")
        else:
            flash("API key is required.", "error")

    elif n == 2:
        name = form.get("name", "").strip()
        if not name or not _VALID_NAME_RE.match(name):
            flash("Invalid destination name.", "error")
            return redirect(url_for("wizard.index") + "?step=2")

        remote = Remote(
            name=name,
            type=form.get("type", "local"),
            host=form.get("host", ""),
            port=form.get("port", "22"),
            user=form.get("user", "root"),
            base=form.get("base", "/backups"),
        )
        conf_dir = CONFIG_DIR / "remotes.d"
        conf_dir.mkdir(parents=True, exist_ok=True)
        write_conf(conf_dir / f"{remote.name}.conf", remote.to_conf())
        flash(f"Destination '{remote.name}' created.", "success")

    elif n == 3:
        name = form.get("name", "").strip()
        if not name or not _VALID_NAME_RE.match(name):
            flash("Invalid source name.", "error")
            return redirect(url_for("wizard.index") + "?step=3")

        target = Target(
            name=name,
            folders=form.get("folders", ""),
            remote=form.get("remote", ""),
            enabled="yes",
        )
        conf_dir = CONFIG_DIR / "targets.d"
        conf_dir.mkdir(parents=True, exist_ok=True)
        write_conf(conf_dir / f"{target.name}.conf", target.to_conf())
        flash(f"Source '{target.name}' created.", "success")

    elif n == 4:
        name = form.get("name", "").strip()
        if not name or not _VALID_NAME_RE.match(name):
            flash("Invalid schedule name.", "error")
            return redirect(url_for("wizard.index") + "?step=4")

        schedule = Schedule(
            name=name,
            schedule=form.get("schedule", "daily"),
            time=form.get("time", "02:00"),
            targets=form.get("targets", ""),
            remotes=form.get("remotes", ""),
            active="yes",
        )
        conf_dir = CONFIG_DIR / "schedules.d"
        conf_dir.mkdir(parents=True, exist_ok=True)
        write_conf(conf_dir / f"{schedule.name}.conf", schedule.to_conf())
        flash(f"Schedule '{schedule.name}' created.", "success")

    return redirect(url_for("wizard.index") + f"?step={n + 1}")
