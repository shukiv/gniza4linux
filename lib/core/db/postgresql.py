"""PostgreSQL database dump and restore — port of lib/postgresql.sh.

All passwords are passed via the PGPASSWORD environment variable,
never on the command line.
"""
from __future__ import annotations

import gzip
import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Optional

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
SYSTEM_DBS = frozenset({"template0", "template1", "postgres"})


def find_client_cmd(ctx: BackupContext) -> str:
    """Detect psql client binary (local or remote).

    Returns the binary path/name, or raises RuntimeError.
    """
    if is_db_remote(ctx.target):
        r = ssh_run_raw(
            ctx,
            "PATH=$PATH:/usr/bin:/usr/local/bin command -v psql",
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        raise RuntimeError("PostgreSQL client (psql) not found on remote host")
    else:
        import shutil
        path = shutil.which("psql")
        if path:
            return "psql"
        raise RuntimeError("PostgreSQL client (psql) not found")


def find_dump_cmd(ctx: BackupContext) -> str:
    """Detect pg_dump binary (local or remote).

    Returns the binary path/name, or raises RuntimeError.
    """
    if is_db_remote(ctx.target):
        r = ssh_run_raw(
            ctx,
            "PATH=$PATH:/usr/bin:/usr/local/bin command -v pg_dump",
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        raise RuntimeError("pg_dump not found on remote host")
    else:
        import shutil
        path = shutil.which("pg_dump")
        if path:
            return "pg_dump"
        raise RuntimeError("pg_dump not found")


def _find_dumpall_cmd(ctx: BackupContext) -> str:
    """Detect pg_dumpall binary (local or remote)."""
    if is_db_remote(ctx.target):
        r = ssh_run_raw(
            ctx,
            "PATH=$PATH:/usr/bin:/usr/local/bin command -v pg_dumpall",
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        raise RuntimeError("pg_dumpall not found on remote host")
    else:
        import shutil
        path = shutil.which("pg_dumpall")
        if path:
            return "pg_dumpall"
        raise RuntimeError("pg_dumpall not found")


def build_conn_args(target: Target) -> list[str]:
    """Build PostgreSQL connection arguments from Target postgresql_* fields.

    When remote and no user is specified, defaults to 'postgres' user
    (peer auth won't work remotely).
    """
    args = []
    if target.postgresql_user:
        args += ["-U", target.postgresql_user]
    elif is_db_remote(target):
        # Remote: default to postgres user (peer auth won't work remotely)
        args += ["-U", "postgres"]

    if target.postgresql_host and target.postgresql_host != "localhost":
        args += ["-h", target.postgresql_host]

    if target.postgresql_port and target.postgresql_port != "5432":
        args += ["-p", target.postgresql_port]

    return args


def _needs_sudo(target: Target) -> bool:
    """Whether sudo should be used (no user and no password configured)."""
    return not target.postgresql_user and not target.postgresql_password


def list_databases(ctx: BackupContext) -> list[str]:
    """List non-system databases, applying exclude filters.

    Returns a list of database names.
    """
    client_cmd = find_client_cmd(ctx)
    target = ctx.target
    conn_args = build_conn_args(target)

    sql_query = "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres'"
    cmd = [client_cmd] + conn_args + ["-At", "-c", sql_query]

    # Try without sudo first, fall back to sudo
    r = run_db_command(
        ctx, cmd,
        password_env="PGPASSWORD",
        password_val=target.postgresql_password or None,
        use_sudo=False,
    )
    if r.returncode != 0:
        r = run_db_command(
            ctx, cmd,
            password_env="PGPASSWORD",
            password_val=target.postgresql_password or None,
            use_sudo=_needs_sudo(target),
        )
    if r.returncode != 0:
        raise RuntimeError("Failed to list databases: %s" % (r.stderr or r.stdout or ""))

    # Build exclude set
    exclude = set(SYSTEM_DBS)
    if target.postgresql_exclude:
        for ex in target.postgresql_exclude.split(","):
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
    mode = target.postgresql_mode or "all"

    if mode in ("specific", "select"):
        if not target.postgresql_databases:
            raise RuntimeError("PostgreSQL mode=specific but postgresql_databases is empty")
        databases = []
        for db in target.postgresql_databases.split(","):
            db = db.strip()
            if db:
                databases.append(db)
        return databases
    else:
        return list_databases(ctx)


def dump_databases(ctx: BackupContext, dump_dir: str) -> bool:
    """Dump all or specific databases to gzipped SQL files.

    Creates a _postgresql/ subdirectory under dump_dir.
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

    pg_dir = Path(dump_dir) / "_postgresql"
    pg_dir.mkdir(parents=True, exist_ok=True)

    # Parse extra opts
    extra_opts_str = target.postgresql_extra_opts or "--no-owner --no-privileges"
    if extra_opts_str != "--no-owner --no-privileges":
        if not validate_extra_opts(extra_opts_str):
            logger.error("postgresql_extra_opts contains invalid characters")
            return False
    extra_opts = extra_opts_str.split()

    failed = False
    password_val = target.postgresql_password or None

    for db in databases:
        if not validate_db_name(db):
            logger.error("Invalid database name, skipping: %s", db)
            failed = True
            continue

        logger.info("Dumping PostgreSQL database: %s", db)
        outfile = pg_dir / ("%s.sql.gz" % db)

        cmd = [dump_cmd] + conn_args + ["-Fp"] + extra_opts + [db]

        if is_db_remote(target):
            r = run_db_command(
                ctx, cmd,
                password_env="PGPASSWORD",
                password_val=password_val,
                use_sudo=False,
                capture_output=True,
            )
            if r.returncode != 0:
                r = run_db_command(
                    ctx, cmd,
                    password_env="PGPASSWORD",
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
                    logger.error("pg_dump: %s", r.stderr.strip())
                failed = True
        else:
            env = os.environ.copy()
            if password_val:
                env["PGPASSWORD"] = password_val

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
                        logger.error("pg_dump: %s", proc.stderr.strip())
                    failed = True
            except subprocess.TimeoutExpired:
                logger.error("Timeout dumping database: %s", db)
                failed = True

    if failed:
        logger.error("One or more PostgreSQL dumps failed")
        return False

    logger.info("PostgreSQL dumps completed: %d database(s) in %s", len(databases), pg_dir)
    return True


def dump_roles(ctx: BackupContext, dump_dir: str) -> bool:
    """Dump PostgreSQL roles to roles.sql in the _postgresql/ subdirectory.

    Returns True on success, False on failure.
    """
    try:
        dumpall_cmd = _find_dumpall_cmd(ctx)
    except RuntimeError as e:
        logger.error("%s", e)
        return False

    target = ctx.target
    conn_args = build_conn_args(target)
    pg_dir = Path(dump_dir) / "_postgresql"
    pg_dir.mkdir(parents=True, exist_ok=True)
    roles_file = pg_dir / "roles.sql"
    password_val = target.postgresql_password or None

    logger.info("Dumping PostgreSQL roles...")

    cmd = [dumpall_cmd] + conn_args + ["--roles-only"]

    if is_db_remote(target):
        r = run_db_command(
            ctx, cmd,
            password_env="PGPASSWORD",
            password_val=password_val,
            use_sudo=_needs_sudo(target),
            capture_output=True,
        )
    else:
        env = os.environ.copy()
        if password_val:
            env["PGPASSWORD"] = password_val
        r = subprocess.run(
            cmd, capture_output=True, text=True, env=env, timeout=120,
        )

    if r.returncode == 0:
        roles_file.write_text(r.stdout or "")
        logger.info("PostgreSQL roles dumped -> roles.sql")
        return True
    else:
        logger.error("Failed to dump PostgreSQL roles")
        if r.stderr:
            logger.error("pg_dumpall: %s", r.stderr.strip())
        return False


def restore_databases(ctx: BackupContext, dump_dir: str) -> bool:
    """Restore PostgreSQL databases from a directory of .sql.gz files.

    The directory should be the _postgresql/ subdirectory containing
    *.sql.gz files and optionally roles.sql.
    Returns True on success, False if any restore failed.
    """
    pg_dir = Path(dump_dir)
    if not pg_dir.is_dir():
        logger.error("PostgreSQL restore dir not found: %s", pg_dir)
        return False

    try:
        client_cmd = find_client_cmd(ctx)
    except RuntimeError as e:
        logger.error("%s", e)
        return False

    target = ctx.target
    conn_args = build_conn_args(target)
    password_val = target.postgresql_password or None
    errors = 0

    # Restore database dumps
    for f in sorted(pg_dir.glob("*.sql.gz")):
        db_name = f.name.removesuffix(".sql.gz")

        if db_name in SYSTEM_DBS:
            continue

        if not validate_db_name(db_name):
            logger.error("Invalid database name in restore, skipping: %s", db_name)
            errors += 1
            continue

        logger.info("Restoring PostgreSQL database: %s", db_name)

        env = os.environ.copy()
        if password_val:
            env["PGPASSWORD"] = password_val

        # Create database if not exists (suppress "already exists" error)
        import shutil
        if shutil.which("createdb"):
            subprocess.run(
                ["createdb"] + conn_args + [db_name],
                text=True, capture_output=True, env=env, timeout=30,
            )
        else:
            subprocess.run(
                [client_cmd] + conn_args + ["-c", 'CREATE DATABASE "%s"' % db_name],
                text=True, capture_output=True, env=env, timeout=30,
            )

        # Import dump
        try:
            with gzip.open(str(f), "rt") as gz:
                sql_data = gz.read()
        except (OSError, gzip.BadGzipFile) as e:
            logger.error("Failed to read dump file %s: %s", f.name, e)
            errors += 1
            continue

        proc = subprocess.run(
            [client_cmd] + conn_args + ["-d", db_name],
            input=sql_data, text=True, capture_output=True, env=env, timeout=600,
        )
        if proc.returncode == 0:
            logger.info("Restored database: %s", db_name)
        else:
            logger.error("Failed to restore database: %s", db_name)
            errors += 1

    if errors > 0:
        logger.error("PostgreSQL restore completed with %d error(s)", errors)
        return False

    logger.info("PostgreSQL restore completed successfully")
    return True


def restore_roles(ctx: BackupContext, dump_dir: str) -> bool:
    """Restore PostgreSQL roles from roles.sql.

    Returns True on success, False on failure.
    """
    roles_file = Path(dump_dir) / "roles.sql"
    if not roles_file.exists():
        logger.info("No roles.sql found, skipping role restore")
        return True

    try:
        client_cmd = find_client_cmd(ctx)
    except RuntimeError as e:
        logger.error("%s", e)
        return False

    target = ctx.target
    conn_args = build_conn_args(target)
    password_val = target.postgresql_password or None

    logger.info("Restoring PostgreSQL roles...")

    env = os.environ.copy()
    if password_val:
        env["PGPASSWORD"] = password_val
    env["PGOPTIONS"] = "--client-min-messages=warning"

    proc = subprocess.run(
        [client_cmd] + conn_args + ["-v", "ON_ERROR_STOP=off", "-f", str(roles_file)],
        text=True, capture_output=True, env=env, timeout=120,
    )
    if proc.returncode == 0:
        logger.info("PostgreSQL roles restored")
        return True
    else:
        logger.error("Failed to restore some PostgreSQL roles (partial restore may have occurred)")
        return False
