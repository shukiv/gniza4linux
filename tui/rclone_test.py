"""Shared rclone connection testing for S3 and Google Drive."""

import os
import subprocess
import tempfile


def test_rclone_s3(bucket, region="us-east-1", endpoint="",
                   access_key_id="", secret_access_key="", provider="AWS"):
    """Test S3 connection. Returns (ok: bool, error_msg: str|None)."""
    if not bucket:
        return False, "S3 bucket is required"
    if not access_key_id or not secret_access_key:
        return False, "S3 access key and secret are required"
    conf = _build_s3_config(bucket, region, endpoint, access_key_id, secret_access_key, provider)
    return _run_rclone_test(conf, f"remote:{bucket}")


def test_rclone_gdrive(sa_file, root_folder_id=""):
    """Test Google Drive connection. Returns (ok: bool, error_msg: str|None)."""
    if not sa_file:
        return False, "Service account file is required"
    if not os.path.isfile(sa_file):
        return False, f"Service account file not found: {sa_file}"
    conf = _build_gdrive_config(sa_file, root_folder_id)
    return _run_rclone_test(conf, "remote:")


def _build_s3_config(bucket, region, endpoint, access_key_id, secret_access_key, provider="AWS"):
    lines = [
        "[remote]",
        "type = s3",
        f"provider = {provider}",
        f"access_key_id = {access_key_id}",
        f"secret_access_key = {secret_access_key}",
        f"region = {region or 'us-east-1'}",
    ]
    if endpoint:
        lines.append(f"endpoint = {endpoint}")
    return "\n".join(lines) + "\n"


def _build_gdrive_config(sa_file, root_folder_id):
    lines = [
        "[remote]",
        "type = drive",
        "scope = drive",
        f"service_account_file = {sa_file}",
    ]
    if root_folder_id:
        lines.append(f"root_folder_id = {root_folder_id}")
    return "\n".join(lines) + "\n"


def _run_rclone_test(config_content, remote_path):
    """Write temp config, run rclone lsd, return (ok, error_msg)."""
    fd, conf_path = tempfile.mkstemp(suffix=".conf", prefix="gniza-rclone-test-")
    try:
        os.write(fd, config_content.encode())
        os.close(fd)
        os.chmod(conf_path, 0o600)
        result = subprocess.run(
            ["rclone", "lsd", "--config", conf_path, remote_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True, None
        err = result.stderr.strip()
        # Extract useful part of rclone error
        for line in err.splitlines():
            if "ERROR" in line or "Failed" in line or "error" in line.lower():
                return False, line.strip()
        return False, err or "Connection failed"
    except FileNotFoundError:
        return False, "rclone is not installed"
    except subprocess.TimeoutExpired:
        return False, "Connection timed out"
    except OSError as e:
        return False, f"Connection test failed: {e}"
    finally:
        try:
            os.unlink(conf_path)
        except OSError:
            pass
