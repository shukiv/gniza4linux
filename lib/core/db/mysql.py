"""MySQL/MariaDB database dump and restore — port of lib/mysql.sh.

All passwords are passed via the MYSQL_PWD environment variable,
never on the command line.
"""
from __future__ import annotations

import gzip
import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.core.context import BackupContext
    from lib.models import Target

from lib.core.db.common import (
    is_db_remote,
    run_db_command,
    ssh_run_raw,
    validate_db_name,
    validate_extra_opts,
)

logger = logging.getLogger(__name__)

# System databases always excluded from dumps
SYSTEM_DBS = frozenset({"information_schema", "performance_schema", "sys"})

# System users to skip when dumping grants
SYSTEM_USERS = frozenset({
    "'root'@'localhost'",
    "'mysql.sys'@'localhost'",
    "'mysql.infoschema'@'localhost'",
    "'mysql.session'@'localhost'",
    "'debian-sys-maint'@'localhost'",
    "'mariadb.sys'@'localhost'",
})

DEBIAN_CNF = "/etc/mysql/debian.cnf"


def find_client_cmd(ctx: BackupContext) -> str:
    """Detect mysql or mariadb client binary (local or remote).

    Returns the binary path/name, or raises RuntimeError.
    """
    if is_db_remote(ctx.target):
        r = ssh_run_raw(
            ctx,
            "PATH=$PATH:/usr/bin:/usr/local/bin command -v mysql "
            "|| PATH=$PATH:/usr/bin:/usr/local/bin command -v mariadb",
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        raise RuntimeError("MySQL/MariaDB client not found on remote host")
    else:
        import shutil
        for name in ("mysql", "mariadb"):
            path = shutil.which(name)
            if path:
                return name
        raise RuntimeError("MySQL/MariaDB client not found")


def find_dump_cmd(ctx: BackupContext) -> str:
    """Detect mysqldump or mariadb-dump binary (local or remote).

    Returns the binary path/name, or raises RuntimeError.
    """
    if is_db_remote(ctx.target):
        r = ssh_run_raw(
            ctx,
            "PATH=$PATH:/usr/bin:/usr/local/bin command -v mysqldump "
            "|| PATH=$PATH:/usr/bin:/usr/local/bin command -v mariadb-dump",
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        raise RuntimeError("mysqldump/mariadb-dump not found on remote host")
    else:
        import shutil
        for name in ("mysqldump", "mariadb-dump"):
            path = shutil.which(name)
            if path:
                return name
        raise RuntimeError("mysqldump/mariadb-dump not found")


def build_conn_args(target: Target) -> list[str]:
    """Build MySQL connection arguments from Target mysql_* fields.

    Includes --defaults-file=/etc/mysql/debian.cnf fallback when
    no user/password is configured.
    """
    args = []
    if target.mysql_user:
        args += ["-u", target.mysql_user]
    elif not target.mysql_user and not target.mysql_password:
        # No credentials — use Debian/Ubuntu defaults file fallback
        args.append("--defaults-file=%s" % DEBIAN_CNF)

    if target.mysql_host and target.mysql_host != "localhost":
        args += ["-h", target.mysql_host]

    if target.mysql_port and target.mysql_port != "3306":
        args += ["-P", target.mysql_port]

    return args


def _has_user(target: Target) -> bool:
    """Whether a MySQL user is configured (affects sudo decision)."""
    return bool(target.mysql_user)


def _needs_sudo(target: Target) -> bool:
    """Whether sudo should be used (no user and no password configured)."""
    return not target.mysql_user and not target.mysql_password


def _check_debian_cnf_remote(ctx: BackupContext) -> bool:
    """Check if debian.cnf exists on the remote host."""
    r = ssh_run_raw(ctx, "test -f %s" % DEBIAN_CNF)
    return r.returncode == 0


def list_databases(ctx: BackupContext) -> list[str]:
    """List non-system databases, applying exclude filters.

    Returns a list of database names.
    """
    client_cmd = find_client_cmd(ctx)
    target = ctx.target
    conn_args = build_conn_args(target)

    # Run SHOW DATABASES
    cmd = [client_cmd] + conn_args + ["-N", "-e", "SHOW DATABASES"]

    # Try without sudo first, fall back to sudo
    r = run_db_command(
        ctx, cmd,
        password_env="MYSQL_PWD",
        password_val=target.mysql_password or None,
        use_sudo=False,
    )
    if r.returncode != 0:
        r = run_db_command(
            ctx, cmd,
            password_env="MYSQL_PWD",
            password_val=target.mysql_password or None,
            use_sudo=_needs_sudo(target),
        )
    if r.returncode != 0:
        raise RuntimeError("Failed to list databases: %s" % (r.stderr or r.stdout or ""))

    # Build exclude set
    exclude = set(SYSTEM_DBS)
    if target.mysql_exclude:
        for ex in target.mysql_exclude.split(","):
            ex = ex.strip()
            if ex:
                exclude.add(ex)

    # Parse output
    databases = []
    for line in (r.stdout or "").splitlines():
        db = line.strip()
        if db and db not in exclude:
            databases.append(db)

    return databases


def _get_databases_to_dump(ctx: BackupContext) -> list[str]:
    """Determine the list of databases to dump based on mode."""
    target = ctx.target
    mode = target.mysql_mode or "all"

    if mode in ("specific", "select"):
        if not target.mysql_databases:
            raise RuntimeError("MySQL mode=specific but mysql_databases is empty")
        databases = []
        for db in target.mysql_databases.split(","):
            db = db.strip()
            if db:
                databases.append(db)
        return databases
    else:
        return list_databases(ctx)


def dump_databases(ctx: BackupContext, dump_dir: str) -> bool:
    """Dump all or specific databases to gzipped SQL files.

    Creates a _mysql/ subdirectory under dump_dir.
    Returns True on success, False if any dump failed.
    """
    try:
        dump_cmd = find_dump_cmd(ctx)
    except RuntimeError as e:
        logger.error("%s", e)
        return False

    target = ctx.target
    conn_args = build_conn_args(target)

    try:
        databases = _get_databases_to_dump(ctx)
    except RuntimeError as e:
        logger.error("%s", e)
        return False

    if not databases:
        logger.warning("No databases to dump")
        return True

    mysql_dir = Path(dump_dir) / "_mysql"
    mysql_dir.mkdir(parents=True, exist_ok=True)

    # Parse extra opts
    extra_opts_str = target.mysql_extra_opts or "--single-transaction --routines --triggers"
    if extra_opts_str != "--single-transaction --routines --triggers":
        if not validate_extra_opts(extra_opts_str):
            logger.error("mysql_extra_opts contains invalid characters")
            return False
    extra_opts = extra_opts_str.split()

    failed = False
    password_val = target.mysql_password or None

    for db in databases:
        if not validate_db_name(db):
            logger.error("Invalid database name, skipping: %s", db)
            failed = True
            continue

        logger.info("Dumping MySQL database: %s", db)
        outfile = mysql_dir / ("%s.sql.gz" % db)

        cmd = [dump_cmd] + conn_args + extra_opts + [db]

        if is_db_remote(target):
            # Remote: pipe through SSH, capture stdout, gzip locally
            r = run_db_command(
                ctx, cmd,
                password_env="MYSQL_PWD",
                password_val=password_val,
                use_sudo=False,
                capture_output=True,
            )
            if r.returncode != 0:
                # Retry with sudo if no user configured
                r = run_db_command(
                    ctx, cmd,
                    password_env="MYSQL_PWD",
                    password_val=password_val,
                    use_sudo=_needs_sudo(target),
                    capture_output=True,
                )
            if r.returncode == 0:
                with gzip.open(str(outfile), "wt") as f:
                    f.write(r.stdout or "")
                size = outfile.stat().st_size
                logger.debug("Dumped %s -> %s.sql.gz (%d bytes)", db, db, size)
            else:
                logger.error("Failed to dump database: %s", db)
                if r.stderr:
                    logger.error("mysqldump: %s", r.stderr.strip())
                failed = True
        else:
            # Local execution
            env = os.environ.copy()
            if password_val:
                env["MYSQL_PWD"] = password_val

            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, env=env, timeout=600,
                )
                if proc.returncode == 0:
                    with gzip.open(str(outfile), "wt") as f:
                        f.write(proc.stdout or "")
                    size = outfile.stat().st_size
                    logger.debug("Dumped %s -> %s.sql.gz (%d bytes)", db, db, size)
                else:
                    logger.error("Failed to dump database: %s", db)
                    if proc.stderr:
                        logger.error("mysqldump: %s", proc.stderr.strip())
                    failed = True
            except subprocess.TimeoutExpired:
                logger.error("Timeout dumping database: %s", db)
                failed = True

    if failed:
        logger.error("One or more MySQL dumps failed")
        return False

    logger.info("MySQL dumps completed: %d database(s) in %s", len(databases), mysql_dir)
    return True


def dump_grants(ctx: BackupContext, dump_dir: str) -> bool:
    """Dump MySQL user grants to grants.sql in the _mysql/ subdirectory.

    Returns True on success, False on failure.
    """
    try:
        client_cmd = find_client_cmd(ctx)
    except RuntimeError as e:
        logger.error("%s", e)
        return False

    target = ctx.target
    conn_args = build_conn_args(target)
    grants_file = Path(dump_dir) / "_mysql" / "grants.sql"
    password_val = target.mysql_password or None

    # Get all users
    sql_query = "SELECT CONCAT(\"'\", user, \"'@'\", host, \"'\") FROM mysql.user"
    cmd = [client_cmd] + conn_args + ["-N", "-e", sql_query]

    r = run_db_command(
        ctx, cmd,
        password_env="MYSQL_PWD",
        password_val=password_val,
        use_sudo=False,
    )
    if r.returncode != 0:
        r = run_db_command(
            ctx, cmd,
            password_env="MYSQL_PWD",
            password_val=password_val,
            use_sudo=_needs_sudo(target),
        )
    if r.returncode != 0:
        logger.error("Failed to list MySQL users: %s", r.stderr or r.stdout or "")
        return False

    from datetime import datetime
    lines = []
    lines.append("-- MySQL grants dump")
    lines.append("-- Generated: %s" % datetime.now().isoformat())
    lines.append("")

    count = 0
    for user_host in (r.stdout or "").splitlines():
        user_host = user_host.strip()
        if not user_host:
            continue
        if user_host in SYSTEM_USERS:
            continue

        # Try SHOW CREATE USER
        create_cmd = [client_cmd] + conn_args + ["-N", "-e", "SHOW CREATE USER %s" % user_host]
        cr = run_db_command(
            ctx, create_cmd,
            password_env="MYSQL_PWD",
            password_val=password_val,
            use_sudo=False,
        )
        if cr.returncode != 0:
            cr = run_db_command(
                ctx, create_cmd,
                password_env="MYSQL_PWD",
                password_val=password_val,
                use_sudo=_needs_sudo(target),
            )
        if cr.returncode == 0 and cr.stdout and cr.stdout.strip():
            lines.append("%s;" % cr.stdout.strip())

        # SHOW GRANTS
        grants_cmd = [client_cmd] + conn_args + ["-N", "-e", "SHOW GRANTS FOR %s" % user_host]
        gr = run_db_command(
            ctx, grants_cmd,
            password_env="MYSQL_PWD",
            password_val=password_val,
            use_sudo=False,
        )
        if gr.returncode != 0:
            gr = run_db_command(
                ctx, grants_cmd,
                password_env="MYSQL_PWD",
                password_val=password_val,
                use_sudo=_needs_sudo(target),
            )
        if gr.returncode != 0:
            continue

        for grant_line in (gr.stdout or "").splitlines():
            if grant_line.strip():
                lines.append("%s;" % grant_line.strip())
        lines.append("")
        count += 1

    grants_file.parent.mkdir(parents=True, exist_ok=True)
    grants_file.write_text("\n".join(lines) + "\n")
    logger.info("MySQL grants dumped: %d user(s) -> grants.sql", count)
    return True


def restore_databases(ctx: BackupContext, dump_dir: str) -> bool:
    """Restore MySQL databases from a directory of .sql.gz files.

    The directory should be the _mysql/ subdirectory containing
    *.sql.gz files and optionally grants.sql.
    Returns True on success, False if any restore failed.
    """
    mysql_dir = Path(dump_dir)
    if not mysql_dir.is_dir():
        logger.error("MySQL restore dir not found: %s", mysql_dir)
        return False

    try:
        client_cmd = find_client_cmd(ctx)
    except RuntimeError as e:
        logger.error("%s", e)
        return False

    target = ctx.target
    conn_args = build_conn_args(target)
    password_val = target.mysql_password or None
    errors = 0

    # Restore database dumps
    for f in sorted(mysql_dir.glob("*.sql.gz")):
        db_name = f.name.removesuffix(".sql.gz")

        if db_name in SYSTEM_DBS:
            continue

        if not validate_db_name(db_name):
            logger.error("Invalid database name in restore, skipping: %s", db_name)
            errors += 1
            continue

        logger.info("Restoring MySQL database: %s", db_name)

        # Create database if not exists
        create_cmd = [client_cmd] + conn_args + ["-e", "CREATE DATABASE IF NOT EXISTS `%s`" % db_name]
        cr = run_db_command(
            ctx, create_cmd,
            password_env="MYSQL_PWD",
            password_val=password_val,
            use_sudo=_needs_sudo(target),
        )
        if cr.returncode != 0:
            logger.error("Failed to create database: %s", db_name)
            errors += 1
            continue

        # Import dump
        import_cmd = [client_cmd] + conn_args + [db_name]
        try:
            with gzip.open(str(f), "rt") as gz:
                sql_data = gz.read()
        except (OSError, gzip.BadGzipFile) as e:
            logger.error("Failed to read dump file %s: %s", f.name, e)
            errors += 1
            continue

        env = os.environ.copy()
        if password_val:
            env["MYSQL_PWD"] = password_val

        proc = subprocess.run(
            import_cmd, input=sql_data, text=True,
            capture_output=True, env=env, timeout=600,
        )
        if proc.returncode == 0:
            logger.info("Restored database: %s", db_name)
        else:
            logger.error("Failed to restore database: %s", db_name)
            errors += 1

    if errors > 0:
        logger.error("MySQL restore completed with %d error(s)", errors)
        return False

    logger.info("MySQL restore completed successfully")
    return True


def restore_grants(ctx: BackupContext, dump_dir: str) -> bool:
    """Restore MySQL grants from grants.sql.

    Returns True on success, False on failure.
    """
    grants_file = Path(dump_dir) / "grants.sql"
    if not grants_file.exists():
        logger.info("No grants.sql found, skipping grant restore")
        return True

    try:
        client_cmd = find_client_cmd(ctx)
    except RuntimeError as e:
        logger.error("%s", e)
        return False

    target = ctx.target
    conn_args = build_conn_args(target)
    password_val = target.mysql_password or None

    logger.info("Restoring MySQL grants...")
    sql_data = grants_file.read_text()

    env = os.environ.copy()
    if password_val:
        env["MYSQL_PWD"] = password_val

    proc = subprocess.run(
        [client_cmd] + conn_args,
        input=sql_data, text=True, capture_output=True, env=env, timeout=120,
    )
    if proc.returncode == 0:
        logger.info("MySQL grants restored")
        # FLUSH PRIVILEGES
        subprocess.run(
            [client_cmd] + conn_args + ["-e", "FLUSH PRIVILEGES"],
            text=True, capture_output=True, env=env, timeout=30,
        )
        return True
    else:
        logger.error("Failed to restore some MySQL grants (partial restore may have occurred)")
        return False
