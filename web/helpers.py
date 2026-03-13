"""Shared helper functions for web blueprints."""

import subprocess

from tui.config import parse_conf, CONFIG_DIR, list_conf_dir
from tui.models import Target, Remote


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
