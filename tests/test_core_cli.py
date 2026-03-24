"""Tests for lib.core.cli — Python CLI entry point."""
from unittest.mock import patch, MagicMock

import pytest

from lib.core.cli import main, _run_scheduled


class TestMainDispatch:

    def test_no_command_prints_help_returns_1(self, capsys):
        rc = main([])
        assert rc == 1
        out = capsys.readouterr().out
        assert "GNIZA Backup Core" in out

    @patch("lib.core.cli._run_backup")
    def test_backup_dispatches(self, mock_run):
        mock_run.return_value = 0
        rc = main(["backup", "--source=test", "--destination=nas"])
        assert rc == 0
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args.source == "test"
        assert args.destination == "nas"

    @patch("lib.core.cli._run_restore")
    def test_restore_dispatches(self, mock_run):
        mock_run.return_value = 0
        rc = main(["restore", "--source=test", "--destination=nas",
                    "--snapshot=2026-03-24T120000"])
        assert rc == 0
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args.source == "test"
        assert args.destination == "nas"
        assert args.snapshot == "2026-03-24T120000"


class TestBackupCLI:

    @patch("lib.core.logging.setup_backup_logger")
    @patch("lib.core.backup.backup_target", return_value=0)
    def test_source_calls_backup_target(self, mock_bt, mock_log):
        rc = main(["backup", "--source=test", "--destination=nas"])
        assert rc == 0
        mock_bt.assert_called_once_with("test", "nas")

    @patch("lib.core.logging.setup_backup_logger")
    @patch("lib.core.backup.backup_all_targets", return_value=0)
    def test_all_calls_backup_all(self, mock_ba, mock_log):
        rc = main(["backup", "--all"])
        assert rc == 0
        mock_ba.assert_called_once_with(None)

    @patch("lib.core.logging.setup_backup_logger")
    @patch("lib.core.backup.backup_all_targets", return_value=0)
    def test_all_with_destination(self, mock_ba, mock_log):
        rc = main(["backup", "--all", "--destination=nas"])
        assert rc == 0
        mock_ba.assert_called_once_with("nas")

    @patch("lib.core.logging.setup_backup_logger")
    def test_no_source_no_all_returns_1(self, mock_log, capsys):
        rc = main(["backup"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "--source or --all required" in err

    @patch("lib.core.logging.setup_backup_logger")
    @patch("lib.core.cli._run_scheduled", return_value=0)
    def test_schedule_dispatches(self, mock_sched, mock_log):
        rc = main(["backup", "--schedule=nightly"])
        assert rc == 0
        mock_sched.assert_called_once_with("nightly")


class TestScheduledRun:

    def test_missing_schedule_returns_1(self, tmp_path):
        import lib.config
        orig = lib.config.CONFIG_DIR
        lib.config.CONFIG_DIR = tmp_path
        (tmp_path / "schedules.d").mkdir()
        try:
            rc = _run_scheduled("nonexistent")
            assert rc == 1
        finally:
            lib.config.CONFIG_DIR = orig

    @patch("lib.core.backup.backup_target", return_value=0)
    def test_scheduled_runs_targets_and_remotes(self, mock_bt, tmp_path):
        import lib.config
        orig = lib.config.CONFIG_DIR
        lib.config.CONFIG_DIR = tmp_path
        (tmp_path / "schedules.d").mkdir()
        (tmp_path / "schedules.d" / "nightly.conf").write_text(
            'TARGETS="web,db"\n'
            'REMOTES="nas"\n'
            'SCHEDULE_ACTIVE="yes"\n'
        )
        try:
            rc = _run_scheduled("nightly")
            assert rc == 0
            assert mock_bt.call_count == 2
            mock_bt.assert_any_call("web", "nas", schedule_retention_count=None)
            mock_bt.assert_any_call("db", "nas", schedule_retention_count=None)
        finally:
            lib.config.CONFIG_DIR = orig

    @patch("lib.core.backup.backup_target", return_value=0)
    def test_scheduled_passes_retention_count(self, mock_bt, tmp_path):
        import lib.config
        orig = lib.config.CONFIG_DIR
        lib.config.CONFIG_DIR = tmp_path
        (tmp_path / "schedules.d").mkdir()
        (tmp_path / "schedules.d" / "nightly.conf").write_text(
            'TARGETS="web"\n'
            'REMOTES="nas"\n'
            'RETENTION_COUNT="7"\n'
        )
        try:
            rc = _run_scheduled("nightly")
            assert rc == 0
            mock_bt.assert_called_once_with("web", "nas", schedule_retention_count=7)
        finally:
            lib.config.CONFIG_DIR = orig

    def test_schedule_no_targets_returns_1(self, tmp_path):
        import lib.config
        orig = lib.config.CONFIG_DIR
        lib.config.CONFIG_DIR = tmp_path
        (tmp_path / "schedules.d").mkdir()
        (tmp_path / "schedules.d" / "empty.conf").write_text(
            'TARGETS=""\nREMOTES=""\n'
        )
        try:
            rc = _run_scheduled("empty")
            assert rc == 1
        finally:
            lib.config.CONFIG_DIR = orig

    @patch("lib.core.backup.backup_target")
    def test_scheduled_failure_returns_1(self, mock_bt, tmp_path):
        mock_bt.return_value = 1
        import lib.config
        orig = lib.config.CONFIG_DIR
        lib.config.CONFIG_DIR = tmp_path
        (tmp_path / "schedules.d").mkdir()
        (tmp_path / "schedules.d" / "nightly.conf").write_text(
            'TARGETS="web"\nREMOTES="nas"\n'
        )
        try:
            rc = _run_scheduled("nightly")
            assert rc == 1
        finally:
            lib.config.CONFIG_DIR = orig


class TestRestoreCLI:

    @patch("lib.core.logging.setup_backup_logger")
    @patch("lib.core.restore.restore_target", return_value=0)
    def test_restore_target(self, mock_rt, mock_log):
        rc = main(["restore", "--source=test", "--destination=nas",
                    "--snapshot=2026-03-24T120000"])
        assert rc == 0
        mock_rt.assert_called_once_with(
            "test", "2026-03-24T120000", "nas",
            dest_dir="", skip_mysql=False, skip_postgresql=False,
        )

    @patch("lib.core.logging.setup_backup_logger")
    @patch("lib.core.restore.restore_folder", return_value=0)
    def test_restore_folder(self, mock_rf, mock_log):
        rc = main(["restore", "--source=test", "--destination=nas",
                    "--snapshot=latest", "--folder=/etc"])
        assert rc == 0
        mock_rf.assert_called_once_with(
            "test", "/etc", "latest", "nas", dest_dir="",
        )

    @patch("lib.core.logging.setup_backup_logger")
    @patch("lib.core.restore.restore_target", return_value=0)
    def test_restore_with_dest(self, mock_rt, mock_log):
        rc = main(["restore", "--source=test", "--destination=nas",
                    "--snapshot=latest", "--dest=/tmp/restore"])
        assert rc == 0
        mock_rt.assert_called_once_with(
            "test", "latest", "nas",
            dest_dir="/tmp/restore", skip_mysql=False, skip_postgresql=False,
        )

    @patch("lib.core.logging.setup_backup_logger")
    @patch("lib.core.restore.restore_target", return_value=0)
    def test_restore_skip_flags(self, mock_rt, mock_log):
        rc = main(["restore", "--source=test", "--destination=nas",
                    "--snapshot=latest", "--skip-mysql", "--skip-postgresql"])
        assert rc == 0
        mock_rt.assert_called_once_with(
            "test", "latest", "nas",
            dest_dir="", skip_mysql=True, skip_postgresql=True,
        )


class TestBackupOrchestrator:

    def test_run_backup_target(self):
        from lib.backup_orchestrator import BackupOrchestrator
        orch = BackupOrchestrator()
        with patch("lib.core.backup.backup_target", return_value=0) as mock_bt:
            rc = orch.run_backup(target="web", remote="nas")
            assert rc == 0
            mock_bt.assert_called_once_with("web", "nas")

    def test_run_backup_all(self):
        from lib.backup_orchestrator import BackupOrchestrator
        orch = BackupOrchestrator()
        with patch("lib.core.backup.backup_all_targets", return_value=0) as mock_ba:
            rc = orch.run_backup(all_targets=True, remote="nas")
            assert rc == 0
            mock_ba.assert_called_once_with("nas")

    def test_run_backup_no_args_returns_1(self):
        from lib.backup_orchestrator import BackupOrchestrator
        orch = BackupOrchestrator()
        rc = orch.run_backup()
        assert rc == 1

    def test_run_restore_target(self):
        from lib.backup_orchestrator import BackupOrchestrator
        orch = BackupOrchestrator()
        with patch("lib.core.restore.restore_target", return_value=0) as mock_rt:
            rc = orch.run_restore("web", "nas", "latest")
            assert rc == 0
            mock_rt.assert_called_once_with(
                "web", "latest", "nas",
                dest_dir="", skip_mysql=False, skip_postgresql=False,
            )

    def test_run_restore_folder(self):
        from lib.backup_orchestrator import BackupOrchestrator
        orch = BackupOrchestrator()
        with patch("lib.core.restore.restore_folder", return_value=0) as mock_rf:
            rc = orch.run_restore("web", "nas", "latest", folder="/etc")
            assert rc == 0
            mock_rf.assert_called_once_with(
                "web", "/etc", "latest", "nas", dest_dir="",
            )
