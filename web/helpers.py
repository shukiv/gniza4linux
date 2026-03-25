"""Shared helper functions for web blueprints."""

import subprocess

from lib.config import parse_conf, CONFIG_DIR, list_conf_dir
from lib.models import Target, Remote
from lib.validation import VALID_NAME_RE as _VALID_NAME_RE  # noqa: F401 — re-exported for blueprints



def paginate(items, page, per_page=20):
    """Paginate a list, returning (page_items, page, total_pages)."""
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    return items[start:start + per_page], page, total_pages


def format_bytes(b):
    """Format bytes into human-readable size."""
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    elif b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    elif b < 1024 ** 4:
        return f"{b / (1024 ** 3):.1f} GB"
    else:
        return f"{b / (1024 ** 4):.2f} TB"


def format_bytes_short(b):
    """Format bytes into compact size (M/G/T) for narrow table columns."""
    if b < 1024 ** 3:
        return f"{b / (1024 ** 2):.0f}M"
    elif b < 1024 ** 4:
        return f"{b / (1024 ** 3):.1f}G"
    else:
        return f"{b / (1024 ** 4):.1f}T"


def parse_schedule_day(schedule_type, form):
    """Extract schedule day value from form based on schedule type."""
    if schedule_type == "daily":
        return ",".join(form.getlist("day"))
    elif schedule_type == "weekly":
        return form.get("weekly_day", "")
    elif schedule_type == "monthly":
        return form.get("monthly_day", "")
    elif schedule_type == "hourly":
        return form.get("hourly_interval", "1")
    return ""


def get_rclone_remotes(config_path=""):
    """Return sorted list of rclone remote names (without trailing colon)."""
    cmd = ["rclone", "listremotes"]
    if config_path:
        cmd += ["--config", config_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return []
        remotes = []
        for line in result.stdout.strip().splitlines():
            name = line.strip().rstrip(":")
            if name:
                remotes.append(name)
        return sorted(remotes)
    except Exception:
        return []


def load_targets():
    targets = []
    for name in list_conf_dir("targets.d"):
        data = parse_conf(CONFIG_DIR / "targets.d" / f"{name}.conf")
        targets.append(Target.from_conf(name, data))
    return targets


def load_remotes():
    remotes = []
    for name in list_conf_dir("remotes.d"):
        data = parse_conf(CONFIG_DIR / "remotes.d" / f"{name}.conf")
        remotes.append(Remote.from_conf(name, data))
    return remotes
