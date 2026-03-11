import os
import re
import subprocess
from pathlib import Path

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify,
)

from tui.config import CONFIG_DIR, parse_conf, write_conf, list_conf_dir
from tui.models import Remote, Target, Schedule
from web.app import login_required
from web.blueprints.remotes import _test_remote
from web.blueprints.targets import _test_source, _lines_to_csv
from web.blueprints.schedules import _reinstall_cron
from web.jobs import web_job_manager

bp = Blueprint("wizard", __name__, url_prefix="/wizard")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_VALID_REMOTE_TYPES = {"ssh", "local", "s3", "gdrive"}
_VALID_SOURCE_TYPES = {"local", "ssh", "s3", "gdrive"}
_VALID_SCHEDULE_TYPES = {"hourly", "daily", "weekly", "monthly", "custom"}


def _config_state():
    """Return current config state for wizard progress detection."""
    targets = list_conf_dir("targets.d")
    remotes = list_conf_dir("remotes.d")
    schedules = list_conf_dir("schedules.d")
    return targets, remotes, schedules


def _auto_step(targets, remotes, schedules):
    """Determine which step to show based on config state."""
    if not remotes:
        return 0
    if not targets:
        return 2
    if not schedules:
        return 3
    return 4


@bp.route("/")
@login_required
def index():
    targets, remotes, schedules = _config_state()
    requested_step = request.args.get("step", -1, type=int)
    auto = _auto_step(targets, remotes, schedules)
    step = requested_step if 0 <= requested_step <= 4 else auto
    ssh_keys = _get_ssh_keys()
    return render_template(
        "wizard/index.html",
        targets=targets,
        remotes=remotes,
        schedules=schedules,
        step=step,
        ssh_keys=ssh_keys,
    )


@bp.route("/step/2", methods=["POST"])
@login_required
def save_destination():
    form = request.form
    name = form.get("name", "").strip()

    if not name or not _VALID_NAME_RE.match(name):
        flash("Invalid name. Use only letters, numbers, hyphens, and underscores.", "error")
        return redirect(url_for("wizard.index") + "?step=1")

    rtype = form.get("type", "local")
    if rtype not in _VALID_REMOTE_TYPES:
        flash("Invalid destination type.", "error")
        return redirect(url_for("wizard.index") + "?step=1")

    remote = Remote(
        name=name,
        type=rtype,
        host=form.get("host", ""),
        port=form.get("port", "22"),
        user=form.get("user", "root"),
        auth_method=form.get("auth_method", "key"),
        key=form.get("key", ""),
        password=form.get("password", ""),
        base=form.get("base", "/backups"),
        bwlimit=form.get("bwlimit", "0"),
        s3_bucket=form.get("s3_bucket", ""),
        s3_region=form.get("s3_region", "us-east-1"),
        s3_endpoint=form.get("s3_endpoint", ""),
        s3_access_key_id=form.get("s3_access_key_id", ""),
        s3_secret_access_key=form.get("s3_secret_access_key", ""),
        gdrive_sa_file=form.get("gdrive_sa_file", ""),
        gdrive_root_folder_id=form.get("gdrive_root_folder_id", ""),
    )

    ok, msg = _test_remote(remote)
    if ok is False:
        flash(msg, "error")
        return redirect(url_for("wizard.index") + "?step=1")

    conf_dir = CONFIG_DIR / "remotes.d"
    conf_dir.mkdir(parents=True, exist_ok=True)
    write_conf(conf_dir / f"{remote.name}.conf", remote.to_conf())
    flash(f"Destination '{remote.name}' saved.", "success")
    return redirect(url_for("wizard.index") + "?step=2")


@bp.route("/step/3", methods=["POST"])
@login_required
def save_source():
    form = request.form
    name = form.get("name", "").strip()

    if not name or not _VALID_NAME_RE.match(name):
        flash("Invalid name. Use only letters, numbers, hyphens, and underscores.", "error")
        return redirect(url_for("wizard.index") + "?step=2")

    stype = form.get("source_type", "local")
    if stype not in _VALID_SOURCE_TYPES:
        flash("Invalid source type.", "error")
        return redirect(url_for("wizard.index") + "?step=2")

    target = Target(
        name=name,
        folders=_lines_to_csv(form.get("folders", "")),
        exclude=_lines_to_csv(form.get("exclude", "")),
        include=_lines_to_csv(form.get("include", "")),
        remote="",
        pre_hook=form.get("pre_hook", ""),
        post_hook=form.get("post_hook", ""),
        enabled="yes" if form.get("enabled") else "no",
        source_type=stype,
        source_host=form.get("source_host", ""),
        source_port=form.get("source_port", "22"),
        source_user=form.get("source_user", "root"),
        source_auth_method=form.get("source_auth_method", "key"),
        source_key=form.get("source_key", ""),
        source_password=form.get("source_password", ""),
        source_s3_bucket=form.get("source_s3_bucket", ""),
        source_s3_region=form.get("source_s3_region", "us-east-1"),
        source_s3_endpoint=form.get("source_s3_endpoint", ""),
        source_s3_access_key_id=form.get("source_s3_access_key_id", ""),
        source_s3_secret_access_key=form.get("source_s3_secret_access_key", ""),
        source_gdrive_sa_file=form.get("source_gdrive_sa_file", ""),
        source_gdrive_root_folder_id=form.get("source_gdrive_root_folder_id", ""),
        mysql_enabled="yes" if form.get("mysql_enabled") else "no",
        mysql_mode=form.get("mysql_mode", "all"),
        mysql_databases=form.get("mysql_databases", ""),
        mysql_exclude=form.get("mysql_exclude", ""),
        mysql_user=form.get("mysql_user", ""),
        mysql_password=form.get("mysql_password", ""),
        mysql_host=form.get("mysql_host", "localhost"),
        mysql_port=form.get("mysql_port", "3306"),
        mysql_extra_opts=form.get("mysql_extra_opts", "--single-transaction --routines --triggers"),
    )

    ok, msg = _test_source(target)
    if ok is False:
        flash(msg, "error")
        return redirect(url_for("wizard.index") + "?step=2")
    if ok is None and msg:
        flash(msg, "warning")

    conf_dir = CONFIG_DIR / "targets.d"
    conf_dir.mkdir(parents=True, exist_ok=True)
    write_conf(conf_dir / f"{target.name}.conf", target.to_conf())
    flash(f"Source '{target.name}' saved.", "success")
    return redirect(url_for("wizard.index") + "?step=3")


@bp.route("/step/4", methods=["POST"])
@login_required
def save_schedule():
    form = request.form
    name = form.get("name", "").strip()

    if not name or not _VALID_NAME_RE.match(name):
        flash("Invalid name. Use only letters, numbers, hyphens, and underscores.", "error")
        return redirect(url_for("wizard.index") + "?step=3")

    schedule_type = form.get("schedule", "daily")
    if schedule_type not in _VALID_SCHEDULE_TYPES:
        flash("Invalid schedule type.", "error")
        return redirect(url_for("wizard.index") + "?step=3")

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
    _reinstall_cron()
    flash(f"Schedule '{schedule.name}' saved.", "success")
    return redirect(url_for("wizard.index") + "?step=4")


@bp.route("/backup", methods=["POST"])
@login_required
def run_backup():
    targets = list_conf_dir("targets.d")
    remotes = list_conf_dir("remotes.d")
    schedules = list_conf_dir("schedules.d")

    if not targets or not remotes:
        flash("Configure at least one source and one destination first.", "error")
        return redirect(url_for("wizard.index"))

    if schedules:
        schedule_name = schedules[0]
        args = ["scheduled-run", f"--schedule={schedule_name}"]
        label = f"First backup: {schedule_name}"
    else:
        args = ["backup", f"--source={targets[0]}", f"--destination={remotes[0]}"]
        label = f"First backup: {targets[0]} -> {remotes[0]}"

    web_job_manager.create_and_start("backup", label, *args)
    flash("First backup started.", "success")
    return redirect(url_for("jobs.index"))


def _get_ssh_keys():
    """Find existing SSH key pairs (private + public)."""
    ssh_dir = Path.home() / ".ssh"
    keys = []
    if ssh_dir.is_dir():
        for pub in sorted(ssh_dir.glob("*.pub")):
            private = pub.with_suffix("")
            try:
                content = pub.read_text().strip()
                keys.append({
                    "name": pub.stem,
                    "private_path": str(private),
                    "pub_path": str(pub),
                    "content": content,
                })
            except OSError:
                pass
    return keys


@bp.route("/ssh-keys")
@login_required
def ssh_keys():
    """Return existing SSH public keys as JSON."""
    return jsonify(keys=_get_ssh_keys())


@bp.route("/ssh-keygen", methods=["POST"])
@login_required
def ssh_keygen():
    """Generate a new Ed25519 SSH key pair for backups."""
    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    key_path = ssh_dir / "id_ed25519_gniza"
    if key_path.exists():
        pub = key_path.with_suffix(".pub").read_text().strip() if key_path.with_suffix(".pub").exists() else ""
        return jsonify(ok=True, message="Key already exists", path=str(key_path), public_key=pub)
    try:
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-C", "gniza-backup"],
            check=True, capture_output=True, text=True,
        )
        pub = key_path.with_suffix(".pub").read_text().strip()
        return jsonify(ok=True, message="Key generated", path=str(key_path), public_key=pub)
    except subprocess.CalledProcessError as e:
        return jsonify(ok=False, message=f"ssh-keygen failed: {e.stderr.strip()}"), 500
