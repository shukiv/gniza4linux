"""gniza background health daemon."""
import argparse
import logging
import sys
import os

def main():
    parser = argparse.ArgumentParser(description="gniza background health daemon")
    parser.add_argument("--interval", type=int, default=None,
                        help="Check interval in seconds (default: from config or 10)")
    parser.add_argument("--foreground", action="store_true",
                        help="Run in foreground with console logging")
    args = parser.parse_args()

    # Setup logging
    logger = logging.getLogger("gniza-daemon")
    logger.setLevel(logging.INFO)

    if args.foreground:
        handler = logging.StreamHandler()
    else:
        # Log to the gniza log directory
        from tui.config import LOG_DIR
        from pathlib import Path
        log_dir = Path(LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "gniza-daemon.log")

    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)

    # Get interval
    interval = args.interval
    if interval is None:
        from tui.config import get_daemon_interval
        interval = get_daemon_interval()

    from daemon.core import run
    run(interval=interval)


if __name__ == "__main__":
    main()
