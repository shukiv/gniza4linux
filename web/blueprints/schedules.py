import os
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from tui.config import CONFIG_DIR, parse_conf, write_conf, list_conf_dir
from tui.models import Schedule
from web.app import login_required
from web.backend import run_cli_sync
from web.helpers import _VALID_NAME_RE
from web.jobs import web_job_manager

bp = Blueprint("schedules", __name__, url_prefix="/schedules")


def _reinstall_cron():
    """Reinstall cron entries so they reflect current schedule configs."""
    try:
        run_cli_sync("schedule", "install", timeout=30)
    except Exception:
        pass


def _calc_next_run(s):
    now = datetime.now()
    try:
        hour, minute = (int(x) for x in s.time.split(":")) if s.time else (2, 0)
    except (ValueError, IndexError):
        hour, minute = 2, 0

    if s.schedule == "hourly":
        next_dt = now.replace(minute=minute, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += timedelta(hours=1)
    elif s.schedule == "daily":
        next_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += timedelta(days=1)
    elif s.schedule == "weekly":
        try:
            target_dow = int(s.day) if s.day else 0
        except ValueError:
            target_dow = 0
        next_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (target_dow - now.weekday()) % 7
        if days_ahead == 0 and next_dt <= now:
            days_ahead = 7
        next_dt += timedelta(days=days_ahead)
    elif s.schedule == "monthly":
        try:
            target_dom = int(s.day) if s.day else 1
        except ValueError:
            target_dom = 1
        try:
            next_dt = now.replace(day=target_dom, hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            # Day doesn't exist in current month, try next month
            if now.month == 12:
                next_dt = datetime(now.year + 1, 1, min(target_dom, 28), hour, minute)
            else:
                import calendar
                max_day = calendar.monthrange(now.year, now.month + 1)[1]
                next_dt = datetime(now.year, now.month + 1, min(target_dom, max_day), hour, minute)
            return next_dt.strftime("%Y-%m-%d %H:%M")
        if next_dt <= now:
            try:
                if now.month == 12:
                    next_dt = next_dt.replace(year=now.year + 1, month=1)
                else:
                    next_dt = next_dt.replace(month=now.month + 1)
            except ValueError:
                import calendar
                next_month = now.month + 1 if now.month < 12 else 1
                next_year = now.year if now.month < 12 else now.year + 1
                max_day = calendar.monthrange(next_year, next_month)[1]
                next_dt = datetime(next_year, next_month, min(target_dom, max_day), hour, minute)
    else:
        return "--"
    return next_dt.strftime("%Y-%m-%d %H:%M")


def _cron_to_text(expr):
    """Convert a 5-field cron expression to human-readable text."""
    parts = expr.split()
    if len(parts) != 5:
        return expr
    minute, hour, dom, month, dow = parts

    dow_names = {'0': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed', '4': 'Thu', '5': 'Fri', '6': 'Sat', '7': 'Sun'}
    month_names = {'1': 'Jan', '2': 'Feb', '3': 'Mar', '4': 'Apr', '5': 'May', '6': 'Jun',
                   '7': 'Jul', '8': 'Aug', '9': 'Sep', '10': 'Oct', '11': 'Nov', '12': 'Dec'}

    def _ordinal(n):
        n = int(n)
        return f"{n}{'st' if n in (1,21,31) else 'nd' if n in (2,22) else 'rd' if n in (3,23) else 'th'}"

    def _fmt_time(h, m):
        return f"{int(h):02d}:{int(m):02d}"

    def _fmt_dow(val):
        if val == '*':
            return None
        names = []
        for part in val.split(','):
            names.append(dow_names.get(part, part))
        return ', '.join(names)

    # Every minute
    if all(p == '*' for p in parts):
        return "Every minute"

    # */N patterns
    if '/' in minute and hour == '*' and dom == '*' and month == '*' and dow == '*':
        n = minute.split('/')[1]
        return f"Every {n} minutes"

    if '/' in hour and dom == '*' and month == '*' and dow == '*':
        n = hour.split('/')[1]
        m = minute if minute != '0' else '00'
        return f"Every {n} hours at :{m.zfill(2)}"

    pieces = []

    # Time part
    if hour != '*' and minute != '*':
        time_str = _fmt_time(hour, minute)
    elif hour != '*':
        time_str = f"{int(hour):02d}:00"
    elif minute != '*':
        time_str = f":{int(minute):02d}"
    else:
        time_str = None

    # Day of week
    dow_str = _fmt_dow(dow)

    # Day of month
    if dom != '*':
        dom_parts = [_ordinal(d) for d in dom.split(',')]
        pieces.append(', '.join(dom_parts))

    # Month
    if month != '*':
        m_names = [month_names.get(m, m) for m in month.split(',')]
        pieces.append(', '.join(m_names))

    if dow_str:
        pieces.insert(0, dow_str)

    if time_str:
        pieces.append(time_str)

    return ' '.join(pieces) if pieces else expr


def _load_schedules():
    schedules = []
    for name in list_conf_dir("schedules.d"):
        data = parse_conf(CONFIG_DIR / "schedules.d" / f"{name}.conf")
        s = Schedule.from_conf(name, data)
        s._last_run = data.get("LAST_RUN", "") or "never"
        s._next_run = _calc_next_run(s) if s.active == "yes" else "inactive"
        if s.schedule == "custom" and s.cron:
            s._cron_text = _cron_to_text(s.cron)
        schedules.append(s)
    return schedules


@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1
    try:
        schedules = _load_schedules()
    except Exception:
        schedules = []
        flash("Failed to load schedules.", "error")
    total = len(schedules)
    per_page = 20
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    schedules = schedules[start:start + per_page]
    return render_template("schedules/list.html", schedules=schedules, page=page, total_pages=total_pages)


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
    _reinstall_cron()
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
        _reinstall_cron()
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
    _reinstall_cron()
    flash(f"Schedule '{name}' {'activated' if schedule.active == 'yes' else 'deactivated'}.", "success")
    return redirect(url_for("schedules.index"))


@bp.route("/<name>/run", methods=["POST"])
@login_required
def run_now(name):
    if not _VALID_NAME_RE.match(name):
        flash("Invalid name.", "error")
        return redirect(url_for("schedules.index"))
    conf_path = CONFIG_DIR / "schedules.d" / f"{name}.conf"
    if not conf_path.is_file():
        flash("Schedule not found.", "error")
        return redirect(url_for("schedules.index"))
    data = parse_conf(conf_path)
    schedule = Schedule.from_conf(name, data)
    args = ["scheduled-run", f"--schedule={name}"]
    if schedule.targets:
        args.append(f"--source={schedule.targets}")
    if schedule.remotes:
        args.append(f"--destination={schedule.remotes}")
    label = f"Scheduled: {name}"
    if schedule.targets:
        label += f" ({schedule.targets}"
        if schedule.remotes:
            label += f" → {schedule.remotes}"
        label += ")"
    web_job_manager.create_and_start("backup", label, *args)
    flash(f"Schedule '{name}' started.", "success")
    return redirect(url_for("jobs.index"))


@bp.route("/run-all", methods=["POST"])
@login_required
def run_all():
    schedules = _load_schedules()
    active = [s for s in schedules if s.active == "yes"]
    if not active:
        flash("No active schedules to run.", "warning")
        return redirect(url_for("schedules.index"))
    for s in active:
        args = ["scheduled-run", f"--schedule={s.name}"]
        if s.targets:
            args.append(f"--source={s.targets}")
        if s.remotes:
            args.append(f"--destination={s.remotes}")
        label = f"Scheduled: {s.name}"
        if s.targets:
            label += f" ({s.targets}"
            if s.remotes:
                label += f" → {s.remotes}"
            label += ")"
        web_job_manager.create_and_start("backup", label, *args)
    flash(f"Started {len(active)} schedule(s).", "success")
    return redirect(url_for("jobs.index"))
