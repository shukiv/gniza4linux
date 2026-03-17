"""Backward compatibility — config moved to lib.config."""
from lib.config import *  # noqa: F401,F403
from lib.config import (  # noqa: F401
    CONFIG_DIR, LOG_DIR, WORK_DIR,
    parse_conf, write_conf, update_conf_key, list_conf_dir,
    has_targets, has_remotes,
    get_log_retain_days, get_max_concurrent_jobs, get_daemon_interval,
)
