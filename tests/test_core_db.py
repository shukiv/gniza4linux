"""Tests for lib.core.db — database backup modules."""
import gzip
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from lib.models import Target, Remote, AppSettings
from lib.core.context import BackupContext
from lib.core.db.common import (
    is_db_remote,
    run_db_command,
    ssh_run_raw,
    validate_db_name,
    validate_extra_opts,
    validate_username,
)
from lib.core.db import mysql, postgresql, crontab


# ── Fixtures ─────────────────────────────────────────────────────

def _make_ctx(source_type="local", **target_kw):
    """Helper to build a BackupContext for testing."""
    target_kw.setdefault("name", "test")
    target_kw["source_type"] = source_type
    if source_type == "ssh":
        target_kw.setdefault("source_host", "10.0.0.1")
        target_kw.setdefault("source_user", "root")
        target_kw.setdefault("source_port", "22")
        target_kw.setdefault("source_auth_method", "key")
    target = Target(**target_kw)
    remote = Remote(name="r", type="local", base="/backups")
    settings = AppSettings()
    return BackupContext(
        target=target, remote=remote, settings=settings,
        hostname="testhost", timestamp="2026-03-24T120000",
        work_dir=Path("/tmp"), log_dir=Path("/tmp"),
    )


def _completed(rc=0, stdout="", stderr=""):
    """Build a CompletedProcess mock."""
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


# ═══════════════════════════════════════════════════════════════════
# common module
# ═══════════════════════════════════════════════════════════════════

class TestIsDbRemote:
    def test_local(self):
        t = Target(name="t", source_type="local")
        assert is_db_remote(t) is False

    def test_ssh(self):
        t = Target(name="t", source_type="ssh", source_host="10.0.0.1")
        assert is_db_remote(t) is True


class TestValidateDbName:
    def test_valid(self):
        assert validate_db_name("mydb") is True
        assert validate_db_name("my_db-2.0") is True

    def test_invalid(self):
        assert validate_db_name("") is False
        assert validate_db_name("../etc") is False
        assert validate_db_name("db;drop") is False
        assert validate_db_name("db name") is False


class TestValidateExtraOpts:
    def test_valid(self):
        assert validate_extra_opts("--single-transaction --routines") is True

    def test_invalid(self):
        assert validate_extra_opts("--opt; rm -rf /") is False


class TestValidateUsername:
    def test_valid(self):
        assert validate_username("root") is True
        assert validate_username("www-data") is True
        assert validate_username("user.name") is True

    def test_invalid(self):
        assert validate_username("") is False
        assert validate_username("user name") is False
        assert validate_username("user;evil") is False


class TestRunDbCommandLocal:
    @patch("lib.core.db.common.subprocess.run")
    def test_local_no_password(self, mock_run):
        mock_run.return_value = _completed(stdout="ok")
        ctx = _make_ctx(source_type="local")
        result = run_db_command(ctx, ["mysql", "-e", "SELECT 1"])
        assert result.stdout == "ok"
        # Should not have MYSQL_PWD in env
        call_args = mock_run.call_args
        assert call_args[0][0] == ["mysql", "-e", "SELECT 1"]

    @patch("lib.core.db.common.subprocess.run")
    def test_local_with_password(self, mock_run):
        mock_run.return_value = _completed(stdout="ok")
        ctx = _make_ctx(source_type="local")
        result = run_db_command(
            ctx, ["mysql", "-e", "SELECT 1"],
            password_env="MYSQL_PWD", password_val="secret",
        )
        assert result.stdout == "ok"
        call_args = mock_run.call_args
        env = call_args[1]["env"]
        assert env["MYSQL_PWD"] == "secret"

    @patch("lib.core.db.common.subprocess.run")
    def test_local_with_sudo(self, mock_run):
        mock_run.return_value = _completed(stdout="ok")
        ctx = _make_ctx(source_type="local")
        run_db_command(ctx, ["mysql", "-e", "SELECT 1"], use_sudo=True)
        call_args = mock_run.call_args
        assert call_args[0][0][0] == "sudo"
        assert call_args[0][0][1:] == ["mysql", "-e", "SELECT 1"]


class TestRunDbCommandRemote:
    @patch("lib.core.db.common.subprocess.run")
    def test_remote_builds_ssh_cmd(self, mock_run):
        mock_run.return_value = _completed(stdout="ok")
        ctx = _make_ctx(source_type="ssh")
        run_db_command(ctx, ["mysql", "-e", "SELECT 1"])
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        # Should be an SSH command wrapping the mysql command
        assert cmd[0] == "ssh"
        # The remote command should be the last arg(s)
        remote_part = cmd[-1]
        assert "mysql" in remote_part
        assert "SELECT 1" in remote_part

    @patch("lib.core.db.common.subprocess.run")
    def test_remote_with_password_env(self, mock_run):
        mock_run.return_value = _completed(stdout="ok")
        ctx = _make_ctx(source_type="ssh")
        run_db_command(
            ctx, ["mysql", "-e", "SELECT 1"],
            password_env="MYSQL_PWD", password_val="secret",
        )
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        remote_part = cmd[-1]
        # Password should be passed as env var in remote command
        assert "MYSQL_PWD=" in remote_part

    @patch("lib.core.db.common.subprocess.run")
    def test_remote_with_sudo(self, mock_run):
        mock_run.return_value = _completed(stdout="ok")
        ctx = _make_ctx(source_type="ssh")
        run_db_command(ctx, ["mysql", "-e", "SELECT 1"], use_sudo=True)
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        remote_part = cmd[-1]
        assert remote_part.startswith("sudo ")


class TestSshRunRaw:
    @patch("lib.core.db.common.subprocess.run")
    def test_calls_ssh(self, mock_run):
        mock_run.return_value = _completed(stdout="/usr/bin/mysql")
        ctx = _make_ctx(source_type="ssh")
        result = ssh_run_raw(ctx, "command -v mysql")
        assert result.stdout == "/usr/bin/mysql"


# ═══════════════════════════════════════════════════════════════════
# mysql module
# ═══════════════════════════════════════════════════════════════════

class TestMysqlFindClientCmd:
    @patch("shutil.which")
    def test_local_mysql(self, mock_which):
        mock_which.side_effect = lambda name: "/usr/bin/mysql" if name == "mysql" else None
        ctx = _make_ctx(source_type="local")
        assert mysql.find_client_cmd(ctx) == "mysql"

    @patch("shutil.which")
    def test_local_mariadb(self, mock_which):
        mock_which.side_effect = lambda name: "/usr/bin/mariadb" if name == "mariadb" else None
        ctx = _make_ctx(source_type="local")
        assert mysql.find_client_cmd(ctx) == "mariadb"

    @patch("shutil.which")
    def test_local_not_found(self, mock_which):
        mock_which.return_value = None
        ctx = _make_ctx(source_type="local")
        with pytest.raises(RuntimeError, match="client not found"):
            mysql.find_client_cmd(ctx)

    @patch("lib.core.db.common.subprocess.run")
    def test_remote_found(self, mock_run):
        mock_run.return_value = _completed(stdout="/usr/bin/mysql\n")
        ctx = _make_ctx(source_type="ssh")
        result = mysql.find_client_cmd(ctx)
        assert result == "/usr/bin/mysql"

    @patch("lib.core.db.common.subprocess.run")
    def test_remote_not_found(self, mock_run):
        mock_run.return_value = _completed(rc=1, stdout="")
        ctx = _make_ctx(source_type="ssh")
        with pytest.raises(RuntimeError, match="not found"):
            mysql.find_client_cmd(ctx)


class TestMysqlBuildConnArgs:
    def test_with_user(self):
        t = Target(name="t", mysql_user="admin")
        args = mysql.build_conn_args(t)
        assert args == ["-u", "admin"]

    def test_debian_cnf_fallback(self):
        t = Target(name="t", mysql_user="", mysql_password="")
        args = mysql.build_conn_args(t)
        assert "--defaults-file=/etc/mysql/debian.cnf" in args

    def test_with_host_and_port(self):
        t = Target(name="t", mysql_user="root", mysql_host="dbhost", mysql_port="3307")
        args = mysql.build_conn_args(t)
        assert ["-u", "root"] == args[:2]
        assert "-h" in args
        assert "dbhost" in args
        assert "-P" in args
        assert "3307" in args

    def test_localhost_skipped(self):
        t = Target(name="t", mysql_user="root", mysql_host="localhost", mysql_port="3306")
        args = mysql.build_conn_args(t)
        assert args == ["-u", "root"]

    def test_no_user_with_password(self):
        """When password is set but no user, no debian.cnf fallback."""
        t = Target(name="t", mysql_user="", mysql_password="secret")
        args = mysql.build_conn_args(t)
        assert "--defaults-file=/etc/mysql/debian.cnf" not in args


class TestMysqlListDatabases:
    @patch("shutil.which", return_value="/usr/bin/mysql")
    @patch("lib.core.db.common.subprocess.run")
    def test_filters_system_dbs(self, mock_run, mock_which):
        mock_run.return_value = _completed(
            stdout="information_schema\nperformance_schema\nsys\nmyapp\nother_db\n"
        )
        ctx = _make_ctx(source_type="local")
        dbs = mysql.list_databases(ctx)
        assert "myapp" in dbs
        assert "other_db" in dbs
        assert "information_schema" not in dbs
        assert "sys" not in dbs

    @patch("shutil.which", return_value="/usr/bin/mysql")
    @patch("lib.core.db.common.subprocess.run")
    def test_applies_user_excludes(self, mock_run, mock_which):
        mock_run.return_value = _completed(stdout="myapp\nexclude_me\nkeep_me\n")
        ctx = _make_ctx(source_type="local", mysql_exclude="exclude_me")
        dbs = mysql.list_databases(ctx)
        assert "myapp" in dbs
        assert "keep_me" in dbs
        assert "exclude_me" not in dbs


class TestMysqlDumpDatabases:
    @patch("shutil.which", return_value="/usr/bin/mysqldump")
    @patch("subprocess.run")
    def test_dump_local_success(self, mock_run, mock_which, tmp_path):
        call_count = {"n": 0}
        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                # list_databases -> SHOW DATABASES
                return _completed(stdout="mydb\n")
            else:
                # mysqldump
                return _completed(stdout="-- SQL dump content\n")
        mock_run.side_effect = side_effect
        ctx = _make_ctx(source_type="local")
        result = mysql.dump_databases(ctx, str(tmp_path))
        assert result is True
        outfile = tmp_path / "_mysql" / "mydb.sql.gz"
        assert outfile.exists()
        with gzip.open(str(outfile), "rt") as f:
            content = f.read()
        assert "SQL dump content" in content

    @patch("shutil.which", return_value=None)
    def test_dump_no_binary(self, mock_which, tmp_path):
        ctx = _make_ctx(source_type="local")
        result = mysql.dump_databases(ctx, str(tmp_path))
        assert result is False

    @patch("shutil.which", return_value="/usr/bin/mysqldump")
    @patch("subprocess.run")
    def test_dump_invalid_db_name(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = _completed(stdout="../evil\n")
        ctx = _make_ctx(source_type="local")
        result = mysql.dump_databases(ctx, str(tmp_path))
        assert result is False


class TestMysqlDumpGrants:
    @patch("shutil.which", return_value="/usr/bin/mysql")
    @patch("lib.core.db.common.subprocess.run")
    def test_dump_grants_success(self, mock_run, mock_which, tmp_path):
        (tmp_path / "_mysql").mkdir()
        mock_run.side_effect = [
            # list users
            _completed(stdout="'admin'@'localhost'\n'root'@'localhost'\n"),
            # SHOW CREATE USER for admin
            _completed(stdout="CREATE USER 'admin'@'localhost'"),
            # SHOW GRANTS for admin
            _completed(stdout="GRANT ALL ON *.* TO 'admin'@'localhost'"),
        ]
        ctx = _make_ctx(source_type="local")
        result = mysql.dump_grants(ctx, str(tmp_path))
        assert result is True
        grants_file = tmp_path / "_mysql" / "grants.sql"
        assert grants_file.exists()
        content = grants_file.read_text()
        assert "admin" in content
        assert "MySQL grants dump" in content


class TestMysqlRestoreDatabases:
    @patch("shutil.which", return_value="/usr/bin/mysql")
    @patch("subprocess.run")
    def test_restore_success(self, mock_run, mock_which, tmp_path):
        mysql_dir = tmp_path / "_mysql"
        mysql_dir.mkdir()
        with gzip.open(str(mysql_dir / "mydb.sql.gz"), "wt") as f:
            f.write("CREATE TABLE t1 (id INT);")

        mock_run.return_value = _completed()
        ctx = _make_ctx(source_type="local")
        result = mysql.restore_databases(ctx, str(mysql_dir))
        assert result is True

    @patch("shutil.which", return_value="/usr/bin/mysql")
    @patch("subprocess.run")
    def test_restore_skips_system_dbs(self, mock_run, mock_which, tmp_path):
        mysql_dir = tmp_path
        with gzip.open(str(mysql_dir / "sys.sql.gz"), "wt") as f:
            f.write("-- sys dump")
        ctx = _make_ctx(source_type="local")
        result = mysql.restore_databases(ctx, str(mysql_dir))
        # Should succeed without trying to restore sys
        assert result is True
        mock_run.assert_not_called()


class TestMysqlRestoreGrants:
    @patch("shutil.which", return_value="/usr/bin/mysql")
    @patch("lib.core.db.mysql.subprocess.run")
    def test_restore_grants_success(self, mock_run, mock_which, tmp_path):
        grants_file = tmp_path / "grants.sql"
        grants_file.write_text("GRANT ALL ON *.* TO 'admin'@'localhost';")
        mock_run.return_value = _completed()
        ctx = _make_ctx(source_type="local")
        result = mysql.restore_grants(ctx, str(tmp_path))
        assert result is True

    def test_no_grants_file(self, tmp_path):
        ctx = _make_ctx(source_type="local")
        result = mysql.restore_grants(ctx, str(tmp_path))
        assert result is True


# ═══════════════════════════════════════════════════════════════════
# postgresql module
# ═══════════════════════════════════════════════════════════════════

class TestPgsqlFindClientCmd:
    @patch("shutil.which")
    def test_local_psql(self, mock_which):
        mock_which.return_value = "/usr/bin/psql"
        ctx = _make_ctx(source_type="local")
        assert postgresql.find_client_cmd(ctx) == "psql"

    @patch("shutil.which")
    def test_local_not_found(self, mock_which):
        mock_which.return_value = None
        ctx = _make_ctx(source_type="local")
        with pytest.raises(RuntimeError, match="not found"):
            postgresql.find_client_cmd(ctx)

    @patch("lib.core.db.common.subprocess.run")
    def test_remote_found(self, mock_run):
        mock_run.return_value = _completed(stdout="/usr/bin/psql\n")
        ctx = _make_ctx(source_type="ssh")
        assert postgresql.find_client_cmd(ctx) == "/usr/bin/psql"


class TestPgsqlBuildConnArgs:
    def test_with_user(self):
        t = Target(name="t", postgresql_user="admin")
        args = postgresql.build_conn_args(t)
        assert args == ["-U", "admin"]

    def test_remote_defaults_to_postgres(self):
        t = Target(name="t", source_type="ssh", source_host="10.0.0.1",
                   postgresql_user="")
        args = postgresql.build_conn_args(t)
        assert ["-U", "postgres"] == args

    def test_local_no_user(self):
        t = Target(name="t", source_type="local", postgresql_user="")
        args = postgresql.build_conn_args(t)
        assert args == []

    def test_with_host_and_port(self):
        t = Target(name="t", postgresql_user="pg", postgresql_host="dbhost",
                   postgresql_port="5433")
        args = postgresql.build_conn_args(t)
        assert "-U" in args
        assert "-h" in args
        assert "dbhost" in args
        assert "-p" in args
        assert "5433" in args

    def test_localhost_skipped(self):
        t = Target(name="t", postgresql_user="pg", postgresql_host="localhost",
                   postgresql_port="5432")
        args = postgresql.build_conn_args(t)
        assert args == ["-U", "pg"]


class TestPgsqlListDatabases:
    @patch("shutil.which", return_value="/usr/bin/psql")
    @patch("lib.core.db.common.subprocess.run")
    def test_filters_system_dbs(self, mock_run, mock_which):
        mock_run.return_value = _completed(
            stdout="myapp\ntemplate0\ntemplate1\npostgres\n"
        )
        ctx = _make_ctx(source_type="local")
        dbs = postgresql.list_databases(ctx)
        assert "myapp" in dbs
        assert "template0" not in dbs
        assert "postgres" not in dbs

    @patch("shutil.which", return_value="/usr/bin/psql")
    @patch("lib.core.db.common.subprocess.run")
    def test_applies_user_excludes(self, mock_run, mock_which):
        mock_run.return_value = _completed(stdout="myapp\nexclude_me\nkeep\n")
        ctx = _make_ctx(source_type="local", postgresql_exclude="exclude_me")
        dbs = postgresql.list_databases(ctx)
        assert "myapp" in dbs
        assert "keep" in dbs
        assert "exclude_me" not in dbs


class TestPgsqlDumpDatabases:
    @patch("shutil.which", return_value="/usr/bin/pg_dump")
    @patch("subprocess.run")
    def test_dump_local_success(self, mock_run, mock_which, tmp_path):
        call_count = {"n": 0}
        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return _completed(stdout="mydb\n")
            else:
                return _completed(stdout="-- PG dump\n")
        mock_run.side_effect = side_effect
        ctx = _make_ctx(source_type="local")
        result = postgresql.dump_databases(ctx, str(tmp_path))
        assert result is True
        outfile = tmp_path / "_postgresql" / "mydb.sql.gz"
        assert outfile.exists()

    @patch("shutil.which", return_value=None)
    def test_dump_no_binary(self, mock_which, tmp_path):
        ctx = _make_ctx(source_type="local")
        result = postgresql.dump_databases(ctx, str(tmp_path))
        assert result is False


class TestPgsqlDumpRoles:
    @patch("shutil.which", return_value="/usr/bin/pg_dumpall")
    @patch("subprocess.run")
    def test_dump_roles_local(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = _completed(stdout="-- Roles\nCREATE ROLE admin;\n")
        ctx = _make_ctx(source_type="local")
        result = postgresql.dump_roles(ctx, str(tmp_path))
        assert result is True
        roles_file = tmp_path / "_postgresql" / "roles.sql"
        assert roles_file.exists()
        assert "CREATE ROLE admin" in roles_file.read_text()


class TestPgsqlRestoreDatabases:
    @patch("shutil.which", return_value="/usr/bin/psql")
    @patch("subprocess.run")
    def test_restore_success(self, mock_run, mock_which, tmp_path):
        pg_dir = tmp_path
        with gzip.open(str(pg_dir / "mydb.sql.gz"), "wt") as f:
            f.write("CREATE TABLE t1 (id INT);")
        mock_run.return_value = _completed()
        ctx = _make_ctx(source_type="local")
        result = postgresql.restore_databases(ctx, str(pg_dir))
        assert result is True

    @patch("shutil.which", return_value="/usr/bin/psql")
    @patch("subprocess.run")
    def test_restore_skips_system_dbs(self, mock_run, mock_which, tmp_path):
        pg_dir = tmp_path
        with gzip.open(str(pg_dir / "template0.sql.gz"), "wt") as f:
            f.write("-- template0")
        mock_run.return_value = _completed()
        ctx = _make_ctx(source_type="local")
        result = postgresql.restore_databases(ctx, str(pg_dir))
        assert result is True
        mock_run.assert_not_called()


class TestPgsqlRestoreRoles:
    @patch("shutil.which", return_value="/usr/bin/psql")
    @patch("subprocess.run")
    def test_restore_roles_success(self, mock_run, mock_which, tmp_path):
        roles_file = tmp_path / "roles.sql"
        roles_file.write_text("CREATE ROLE admin;")
        mock_run.return_value = _completed()
        ctx = _make_ctx(source_type="local")
        result = postgresql.restore_roles(ctx, str(tmp_path))
        assert result is True

    def test_no_roles_file(self, tmp_path):
        ctx = _make_ctx(source_type="local")
        result = postgresql.restore_roles(ctx, str(tmp_path))
        assert result is True


# ═══════════════════════════════════════════════════════════════════
# crontab module
# ═══════════════════════════════════════════════════════════════════

class TestCrontabDump:
    @patch("lib.core.db.common.subprocess.run")
    def test_dump_local_success(self, mock_run, tmp_path):
        mock_run.side_effect = [
            # crontab -l -u root
            _completed(stdout="0 * * * * /usr/bin/backup\n"),
            # cat /etc/crontab
            _completed(stdout="# /etc/crontab content\n"),
            # ls /etc/cron.d/
            _completed(stdout="php\nlogrotate\n"),
            # cat /etc/cron.d/php
            _completed(stdout="*/5 * * * * www-data /usr/bin/php\n"),
            # cat /etc/cron.d/logrotate
            _completed(stdout="0 0 * * * root /usr/sbin/logrotate\n"),
        ]
        ctx = _make_ctx(source_type="local", crontab_users="root")
        result = crontab.dump_crontabs(ctx, str(tmp_path))
        assert result is True
        assert (tmp_path / "_crontab" / "root.crontab").exists()
        assert (tmp_path / "_crontab" / "etc-crontab").exists()
        assert (tmp_path / "_crontab" / "cron.d-php").exists()
        assert (tmp_path / "_crontab" / "cron.d-logrotate").exists()

    @patch("lib.core.db.common.subprocess.run")
    def test_dump_no_crontab(self, mock_run, tmp_path):
        mock_run.side_effect = [
            # crontab -l -u root => exit code 1 (no crontab)
            _completed(rc=1, stderr="no crontab for root"),
            # cat /etc/crontab
            _completed(stdout="# etc crontab\n"),
            # ls /etc/cron.d/
            _completed(rc=1, stdout=""),
        ]
        ctx = _make_ctx(source_type="local", crontab_users="root")
        result = crontab.dump_crontabs(ctx, str(tmp_path))
        assert result is True
        assert not (tmp_path / "_crontab" / "root.crontab").exists()

    @patch("lib.core.db.common.subprocess.run")
    def test_dump_invalid_username(self, mock_run, tmp_path):
        mock_run.side_effect = [
            # cat /etc/crontab
            _completed(stdout="# etc\n"),
            # ls /etc/cron.d/
            _completed(rc=1, stdout=""),
        ]
        ctx = _make_ctx(source_type="local", crontab_users="root;evil")
        result = crontab.dump_crontabs(ctx, str(tmp_path))
        assert result is False

    @patch("lib.core.db.common.subprocess.run")
    def test_dump_multiple_users(self, mock_run, tmp_path):
        mock_run.side_effect = [
            _completed(stdout="# root crontab\n"),
            _completed(stdout="# www crontab\n"),
            _completed(stdout="# etc\n"),
            _completed(rc=1, stdout=""),
        ]
        ctx = _make_ctx(source_type="local", crontab_users="root,www-data")
        result = crontab.dump_crontabs(ctx, str(tmp_path))
        assert result is True
        assert (tmp_path / "_crontab" / "root.crontab").exists()
        assert (tmp_path / "_crontab" / "www-data.crontab").exists()


class TestCrontabRestore:
    def test_restore_logs_guidance(self, tmp_path):
        ctx = _make_ctx(source_type="local")
        result = crontab.restore_crontabs(ctx, str(tmp_path))
        assert result is True
