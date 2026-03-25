"""Logging for backup operations — matches Bash log format."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class GnizaFormatter(logging.Formatter):
    """Format: [DD/MM/YYYY HH:MM:SS] [LEVEL] message"""

    LEVEL_MAP = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARN",
        logging.ERROR: "ERROR",
    }

    def format(self, record):
        now = datetime.now(timezone.utc)
        ts = now.strftime("%d/%m/%Y %H:%M:%S")
        level = self.LEVEL_MAP.get(record.levelno, record.levelname)
        return "[%s] [%s] %s" % (ts, level, record.getMessage())


def setup_backup_logger(
    name: str = "gniza",
    log_dir: Optional[Path] = None,
    log_file: Optional[str] = None,
    level: str = "info",
) -> logging.Logger:
    """Set up a logger with gniza format. Logs to file and optionally stderr."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = GnizaFormatter()

    if log_dir and log_file:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / log_file)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    # Always log to stderr (CLI sees output, daemon captures it)
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    return logger


def get_logger() -> logging.Logger:
    """Get the gniza logger (or create a basic one)."""
    logger = logging.getLogger("gniza")
    if not logger.handlers:
        return setup_backup_logger()
    return logger
