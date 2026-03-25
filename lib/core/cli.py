"""Python CLI for gniza backup core."""
from __future__ import annotations

import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gniza-core", description="GNIZA Backup Core")
    sub = parser.add_subparsers(dest="command")

    # backup subcommand
    bp = sub.add_parser("backup")
    bp.add_argument("--source", help="Target name")
    bp.add_argument("--destination", help="Remote name")
    bp.add_argument("--all", action="store_true", help="Backup all targets")
    bp.add_argument("--schedule", help="Schedule name (for scheduled-run)")

    # restore subcommand
    rp = sub.add_parser("restore")
    rp.add_argument("--source", required=True, help="Target name")
    rp.add_argument("--destination", required=True, help="Remote name")
    rp.add_argument("--snapshot", required=True, help="Snapshot timestamp or 'latest'")
    rp.add_argument("--folder", help="Specific folder to restore")
    rp.add_argument("--dest", help="Custom restore destination")
    rp.add_argument("--skip-mysql", action="store_true")
    rp.add_argument("--skip-postgresql", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "backup":
        return _run_backup(args)
    elif args.command == "restore":
        return _run_restore(args)
    else:
        parser.print_help()
        return 1


def _run_backup(args):
    from lib.core.backup import backup_target, backup_all_targets
    from lib.core.logging import setup_backup_logger
    from lib.config import LOG_DIR
    from lib.core.utils import make_timestamp

    setup_backup_logger(log_dir=LOG_DIR, log_file="gniza-%s.log" % make_timestamp())

    if args.all:
        return backup_all_targets(args.destination)
    elif args.schedule:
        return _run_scheduled(args.schedule)
    elif args.source:
        return backup_target(args.source, args.destination)
    else:
        print("Error: --source or --all required", file=sys.stderr)
        return 1


def _run_scheduled(schedule_name):
    """Run a scheduled backup (all targets/remotes in the schedule)."""
    from lib.config import CONFIG_DIR, parse_conf
    from lib.models import Schedule
    from lib.core.backup import backup_target

    sched_conf = CONFIG_DIR / "schedules.d" / ("%s.conf" % schedule_name)
    if not sched_conf.exists():
        print("Schedule not found: %s" % schedule_name, file=sys.stderr)
        return 1

    data = parse_conf(sched_conf)
    schedule = Schedule.from_conf(schedule_name, data)

    targets = [t.strip() for t in schedule.targets.split(",") if t.strip()]
    remotes = [r.strip() for r in schedule.remotes.split(",") if r.strip()]

    if not targets or not remotes:
        print("Schedule %s has no targets or remotes" % schedule_name, file=sys.stderr)
        return 1

    retention_count = None
    if schedule.retention_count:
        try:
            retention_count = int(schedule.retention_count)
        except (ValueError, TypeError):
            pass

    failures = 0
    for target in targets:
        for remote in remotes:
            rc = backup_target(target, remote, schedule_retention_count=retention_count)
            if rc == 1:
                failures += 1

    return 1 if failures > 0 else 0


def _run_restore(args):
    from lib.core.logging import setup_backup_logger
    from lib.config import LOG_DIR
    from lib.core.utils import make_timestamp

    setup_backup_logger(log_dir=LOG_DIR, log_file="gniza-%s.log" % make_timestamp())

    if args.folder:
        from lib.core.restore import restore_folder
        return restore_folder(
            args.source, args.folder, args.snapshot, args.destination,
            dest_dir=args.dest or "",
        )
    else:
        from lib.core.restore import restore_target
        return restore_target(
            args.source, args.snapshot, args.destination,
            dest_dir=args.dest or "",
            skip_mysql=args.skip_mysql,
            skip_postgresql=args.skip_postgresql,
        )


if __name__ == "__main__":
    sys.exit(main())
