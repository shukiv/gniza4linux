"""Tests for lib.job_utils — job status detection."""
from lib.job_utils import detect_return_code, is_skipped_job


def test_detect_success(tmp_path):
    log = tmp_path / "job.log"
    log.write_text("Starting backup\nBackup completed for mysite\n")
    assert detect_return_code(str(log)) == 0


def test_detect_failure(tmp_path):
    log = tmp_path / "job.log"
    log.write_text("[ERROR] Failed to connect\nBackup Summary\nFailed:      1\n")
    assert detect_return_code(str(log)) == 1


def test_detect_empty_log(tmp_path):
    log = tmp_path / "job.log"
    log.write_text("")
    assert detect_return_code(str(log)) is None


def test_detect_nonexistent():
    assert detect_return_code("/nonexistent/path.log") is None


def test_detect_none_input():
    assert detect_return_code(None) is None


def test_detect_error_line(tmp_path):
    log = tmp_path / "job.log"
    log.write_text("[FATAL] something went wrong\n")
    assert detect_return_code(str(log)) == 1


def test_detect_summary_no_failures(tmp_path):
    log = tmp_path / "job.log"
    log.write_text("Backup Summary\nFailed:      0\nSucceeded:   3\n")
    assert detect_return_code(str(log)) == 0


def test_is_skipped_with_disabled():
    lines = ["[INFO] Target 'mysite' is disabled, skipping"]
    assert is_skipped_job(lines) is True


def test_is_not_skipped_with_backup():
    lines = ["[INFO] Backup completed for mysite"]
    assert is_skipped_job(lines) is False


def test_is_skipped_empty():
    assert is_skipped_job([]) is False


def test_is_skipped_disabled_but_also_active():
    lines = [
        "[INFO] Target 'site1' is disabled, skipping",
        "[INFO] Backup completed for site2",
    ]
    assert is_skipped_job(lines) is False
