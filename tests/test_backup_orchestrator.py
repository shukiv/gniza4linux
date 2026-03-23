"""Tests for BackupOrchestrator command building."""
import pytest
from lib.backup_orchestrator import BackupOrchestrator


class TestBuildBackupCommand:
    def test_all_targets(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_backup_command(all_targets=True)
        assert cmd == ["/usr/local/bin/gniza", "backup", "--all"]

    def test_single_target(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_backup_command(target="myserver")
        assert cmd == ["/usr/local/bin/gniza", "backup", "--source=myserver"]

    def test_target_with_remote(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_backup_command(target="myserver", remote="nas")
        assert cmd == ["/usr/local/bin/gniza", "backup", "--source=myserver", "--destination=nas"]

    def test_no_args(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_backup_command()
        assert cmd == ["/usr/local/bin/gniza", "backup"]

    def test_remote_without_target_ignored(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_backup_command(remote="nas")
        assert cmd == ["/usr/local/bin/gniza", "backup"]


class TestBuildRestoreCommand:
    def test_basic_restore(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_restore_command("myserver", "nas", "2026-03-23T120000")
        assert "--source=myserver" in cmd
        assert "--destination=nas" in cmd
        assert "--snapshot=2026-03-23T120000" in cmd

    def test_folder_restore(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_restore_command("myserver", "nas", "2026-03-23T120000", folder="/etc")
        assert "--folder=/etc" in cmd

    def test_dest_restore(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_restore_command("myserver", "nas", "2026-03-23T120000", dest="/tmp/restore")
        assert "--dest=/tmp/restore" in cmd

    def test_skip_flags(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_restore_command("myserver", "nas", "2026-03-23T120000",
                                       skip_mysql=True, skip_postgresql=True)
        assert "--skip-mysql" in cmd
        assert "--skip-postgresql" in cmd

    def test_no_skip_flags_by_default(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_restore_command("myserver", "nas", "2026-03-23T120000")
        assert "--skip-mysql" not in cmd
        assert "--skip-postgresql" not in cmd


class TestBuildScheduledCommand:
    def test_scheduled_run(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_scheduled_run_command("nightly")
        assert cmd == ["/usr/local/bin/gniza", "scheduled-run", "--schedule=nightly"]


class TestCliArgs:
    def test_strips_binary(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_backup_command(target="web", remote="nas")
        cli_args = o.cli_args(cmd)
        assert cli_args == ("backup", "--source=web", "--destination=nas")

    def test_returns_tuple(self):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        cmd = o.build_backup_command(all_targets=True)
        cli_args = o.cli_args(cmd)
        assert isinstance(cli_args, tuple)


class TestValidateTarget:
    def test_target_not_found(self, tmp_config):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        ok, msg = o.validate_target("nonexistent")
        assert not ok
        assert "not found" in msg

    def test_target_disabled(self, tmp_config):
        conf = tmp_config / "targets.d" / "disabled.conf"
        conf.write_text('TARGET_NAME="disabled"\nTARGET_ENABLED="no"\nTARGET_FOLDERS="/var/www"\n')
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        ok, msg = o.validate_target("disabled")
        assert not ok
        assert "disabled" in msg

    def test_target_no_folders(self, tmp_config):
        conf = tmp_config / "targets.d" / "empty.conf"
        conf.write_text('TARGET_NAME="empty"\nTARGET_ENABLED="yes"\nTARGET_FOLDERS=""\n')
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        ok, msg = o.validate_target("empty")
        assert not ok
        assert "no folders" in msg

    def test_target_valid(self, tmp_config):
        conf = tmp_config / "targets.d" / "web.conf"
        conf.write_text('TARGET_NAME="web"\nTARGET_ENABLED="yes"\nTARGET_FOLDERS="/var/www"\n')
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        ok, msg = o.validate_target("web")
        assert ok
        assert msg == "OK"


class TestValidateRemote:
    def test_remote_not_found(self, tmp_config):
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        ok, msg = o.validate_remote("nonexistent")
        assert not ok
        assert "not found" in msg

    def test_remote_valid(self, tmp_config):
        conf = tmp_config / "remotes.d" / "nas.conf"
        conf.write_text('REMOTE_TYPE="ssh"\nREMOTE_HOST="nas.local"\n')
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        ok, msg = o.validate_remote("nas")
        assert ok
        assert msg == "OK"


class TestListConfigs:
    def test_list_targets(self, tmp_config):
        (tmp_config / "targets.d" / "alpha.conf").write_text('TARGET_NAME="alpha"\n')
        (tmp_config / "targets.d" / "beta.conf").write_text('TARGET_NAME="beta"\n')
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        targets = o.list_targets()
        assert "alpha" in targets
        assert "beta" in targets

    def test_list_remotes(self, tmp_config):
        (tmp_config / "remotes.d" / "nas.conf").write_text('REMOTE_TYPE="local"\n')
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        remotes = o.list_remotes()
        assert "nas" in remotes

    def test_list_schedules(self, tmp_config):
        (tmp_config / "schedules.d" / "nightly.conf").write_text('SCHEDULE="daily"\n')
        o = BackupOrchestrator(gniza_bin="/usr/local/bin/gniza")
        schedules = o.list_schedules()
        assert "nightly" in schedules
