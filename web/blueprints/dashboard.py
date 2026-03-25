import time
from datetime import datetime, timedelta

import psutil
from flask import Blueprint, render_template, flash, request, redirect, url_for

from lib.config import CONFIG_DIR, parse_conf, list_conf_dir
from lib.models import Schedule
from web.app import login_required
from web.helpers import load_targets, load_remotes, paginate, format_bytes
from web.jobs import web_job_manager

DASH_LOGS_PER_PAGE = 10

bp = Blueprint("dashboard", __name__)

# Network I/O tracking for rate calculation
_prev_net = {"time": 0.0, "bytes_sent": 0, "bytes_recv": 0}

# Initialize cpu_percent so next call returns a real value
psutil.cpu_percent(interval=None)


def _format_bytes_rate(bps):
    """Format bytes/sec into human-readable rate."""
    if bps < 1024:
        return f"{bps:.0f} B/s"
    elif bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    elif bps < 1024 * 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    else:
        return f"{bps / (1024 * 1024 * 1024):.2f} GB/s"


def _load_schedules():
    schedules = []
    for name in list_conf_dir("schedules.d"):
        data = parse_conf(CONFIG_DIR / "schedules.d" / f"{name}.conf")
        schedules.append(Schedule.from_conf(name, data))
    return schedules


def _count_errors_past_month():
    cutoff = datetime.now() - timedelta(days=30)
    count = 0
    for j in web_job_manager.list_jobs():
        if j.status in ("running", "queued"):
            continue
        if j.finished_at and j.finished_at >= cutoff and j.status == "failed":
            count += 1
    return count


def _load_finished_jobs(page=1):
    all_jobs = web_job_manager.list_jobs()
    finished = [j for j in all_jobs if j.status not in ("running", "queued")]
    finished.sort(key=lambda j: j.finished_at or j.started_at, reverse=True)
    return paginate(finished, page, DASH_LOGS_PER_PAGE)


@bp.route("/")
@login_required
def index():
    if not list_conf_dir("remotes.d") and not list_conf_dir("targets.d"):
        return redirect(url_for("wizard.index"))
    targets, remotes, schedules = [], [], []
    _, log_page, log_total_pages = [], 1, 1
    try:
        targets = load_targets()
    except Exception:
        flash("Failed to load sources.", "error")
    try:
        remotes = load_remotes()
    except Exception:
        flash("Failed to load destinations.", "error")
    try:
        schedules = _load_schedules()
    except Exception:
        flash("Failed to load schedules.", "error")
    try:
        page = request.args.get("log_page", 1, type=int)
        if page < 1:
            page = 1
        recent_jobs, log_page, log_total_pages = _load_finished_jobs(page)
    except Exception:
        recent_jobs, log_page, log_total_pages = [], 1, 1
    errors_past_month = 0
    try:
        errors_past_month = _count_errors_past_month()
    except Exception:
        pass
    return render_template(
        "dashboard/index.html",
        targets=targets,
        remotes=remotes,
        schedules=schedules,
        recent_jobs=recent_jobs,
        log_page=log_page,
        log_total_pages=log_total_pages,
        errors_past_month=errors_past_month,
    )


@bp.route("/system-stats")
@login_required
def system_stats():
    global _prev_net

    # CPU
    cpu_percent = psutil.cpu_percent(interval=None)

    # IO wait (Linux only)
    cpu_times = psutil.cpu_times_percent(interval=None)
    iowait = getattr(cpu_times, "iowait", 0.0)

    # Memory
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Network rates
    net = psutil.net_io_counters()
    now = time.monotonic()
    elapsed = now - _prev_net["time"] if _prev_net["time"] > 0 else 0
    if elapsed > 0:
        send_rate = (net.bytes_sent - _prev_net["bytes_sent"]) / elapsed
        recv_rate = (net.bytes_recv - _prev_net["bytes_recv"]) / elapsed
    else:
        send_rate = 0.0
        recv_rate = 0.0
    _prev_net = {"time": now, "bytes_sent": net.bytes_sent, "bytes_recv": net.bytes_recv}

    # Disk usage — all real partitions (skip tmpfs, devtmpfs, squashfs, etc.)
    disks = []
    seen_devices = set()
    for part in psutil.disk_partitions(all=False):
        if part.device in seen_devices:
            continue
        if part.fstype in ("tmpfs", "devtmpfs", "squashfs", "overlay", "iso9660"):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            if usage.total < 100 * 1024 * 1024:  # skip tiny (<100MB)
                continue
            seen_devices.add(part.device)
            disks.append({
                "mount": part.mountpoint,
                "percent": usage.percent,
                "used_gb": usage.used / (1024 ** 3),
                "total_gb": usage.total / (1024 ** 3),
            })
        except (PermissionError, OSError):
            continue

    return render_template(
        "dashboard/system_stats_partial.html",
        cpu_percent=cpu_percent,
        iowait=iowait,
        mem_percent=mem.percent,
        mem_used_gb=mem.used / (1024 ** 3),
        mem_total_gb=mem.total / (1024 ** 3),
        swap_percent=swap.percent,
        swap_used_gb=swap.used / (1024 ** 3),
        swap_total_gb=swap.total / (1024 ** 3),
        net_send_rate=_format_bytes_rate(send_rate),
        net_recv_rate=_format_bytes_rate(recv_rate),
        net_sent_total=format_bytes(net.bytes_sent),
        net_recv_total=format_bytes(net.bytes_recv),
        disks=disks,
    )
