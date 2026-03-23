"""Shared connection testing for remotes and sources."""
import os
import subprocess
import shlex

from lib.ssh import SSHOpts


def test_remote(remote):
    """Test connectivity to a remote/destination.

    Args:
        remote: a Remote model instance (from lib.models).

    Returns:
        (True, None)  -- test passed
        (None, msg)   -- partial success (e.g. restricted shell)
        (False, msg)  -- test failed
    """
    if remote.type == "local":
        base = remote.base or "/backups"
        try:
            os.makedirs(base, exist_ok=True)
        except OSError as e:
            return False, f"Cannot create base path '{base}': {e}"
        return True, None

    if remote.type == "ssh":
        ssh = SSHOpts.for_remote(remote)
        cmd = ssh.ssh_cmd()
        env = ssh.env()
        base = remote.base or "/backups"

        # Step 1: Test SSH connection (try "echo ok", fall back to sftp for restricted shells)
        try:
            result = subprocess.run(
                cmd + ["echo", "ok"],
                capture_output=True, text=True, timeout=15, env=env,
            )
            if result.returncode != 0:
                # Restricted shell (e.g. Hetzner Storage Box) -- try sftp fallback
                sftp_result = subprocess.run(
                    ssh.sftp_cmd(), input="bye\n",
                    capture_output=True, text=True, timeout=15, env=env,
                )
                if sftp_result.returncode != 0:
                    err = result.stderr.strip() or "unknown error"
                    return False, f"SSH connection failed: {err}"
                # Connection works but shell is restricted -- skip mkdir/write tests
                return None, "Connected via SFTP (restricted shell detected)"
        except subprocess.TimeoutExpired:
            return False, "SSH connection timed out"
        except OSError as e:
            return False, f"SSH connection failed: {e}"

        # Step 2: Create base path -- if absolute path fails (read-only root),
        # try relative path automatically (e.g. /backups -> ./backups)
        try:
            result = subprocess.run(
                cmd + ["mkdir", "-p", base],
                capture_output=True, text=True, timeout=15, env=env,
            )
            if result.returncode != 0:
                if base.startswith("/"):
                    rel_base = "." + base
                    result = subprocess.run(
                        cmd + ["mkdir", "-p", rel_base],
                        capture_output=True, text=True, timeout=15, env=env,
                    )
                    if result.returncode == 0:
                        base = rel_base  # use relative path for write test
                    else:
                        # Retry original with sudo
                        result = subprocess.run(
                            cmd + ["sudo", "mkdir", "-p", base],
                            capture_output=True, text=True, timeout=15, env=env,
                        )
                        if result.returncode != 0:
                            return False, f"Failed to create base path: {result.stderr.strip()}"
                        subprocess.run(
                            cmd + ["sudo", "chown", f"{remote.user}:", base],
                            capture_output=True, text=True, timeout=15, env=env,
                        )
                else:
                    # Retry with sudo
                    result = subprocess.run(
                        cmd + ["sudo", "mkdir", "-p", base],
                        capture_output=True, text=True, timeout=15, env=env,
                    )
                    if result.returncode != 0:
                        return False, f"Failed to create base path: {result.stderr.strip()}"
                    subprocess.run(
                        cmd + ["sudo", "chown", f"{remote.user}:", base],
                        capture_output=True, text=True, timeout=15, env=env,
                    )
        except (subprocess.TimeoutExpired, OSError) as e:
            return False, f"Failed to create base path: {e}"

        # Step 3: Write test file
        test_file = f"{base}/validation_success.txt"
        quoted_test_file = shlex.quote(test_file)
        try:
            result = subprocess.run(
                cmd + ["sh", "-c", f"echo 'gniza validation' > {quoted_test_file}"],
                capture_output=True, text=True, timeout=15, env=env,
            )
            if result.returncode != 0:
                # Retry with sudo
                result = subprocess.run(
                    cmd + ["sudo", "sh", "-c", f"echo 'gniza validation' > {quoted_test_file}"],
                    capture_output=True, text=True, timeout=15, env=env,
                )
                if result.returncode != 0:
                    return False, f"Failed to write test file: {result.stderr.strip()}"
        except (subprocess.TimeoutExpired, OSError) as e:
            return False, f"Failed to write test file: {e}"
        return True, None

    if remote.type == "s3":
        from lib.rclone_test import test_rclone_s3
        return test_rclone_s3(
            bucket=remote.s3_bucket,
            region=remote.s3_region,
            endpoint=remote.s3_endpoint,
            access_key_id=remote.s3_access_key_id,
            secret_access_key=remote.s3_secret_access_key,
            provider=remote.s3_provider,
        )

    if remote.type == "gdrive":
        from lib.rclone_test import test_rclone_gdrive
        return test_rclone_gdrive(
            sa_file=remote.gdrive_sa_file,
            root_folder_id=remote.gdrive_root_folder_id,
        )

    if remote.type == "rclone":
        from lib.rclone_test import test_rclone_generic
        return test_rclone_generic(
            config_path=remote.rclone_config_path,
            remote_name=remote.rclone_remote_name,
        )

    return True, None


def test_source(target):
    """Test connectivity to a source.

    Args:
        target: a Target model instance (from lib.models).

    Returns:
        (True, None)  -- test passed
        (None, msg)   -- partial success / warning
        (False, msg)  -- test failed
    """
    if target.source_type == "local":
        if target.folders:
            folder_list = [f.strip() for f in target.folders.split(",") if f.strip()]
            missing = [f for f in folder_list if not os.path.isdir(f)]
            if missing:
                return None, f"Warning: folders not found: {', '.join(missing)}"
        return True, None

    if target.source_type == "ssh":
        ssh = SSHOpts.for_target_source(target)
        cmd = ssh.ssh_cmd()
        env = ssh.env()

        # Step 1: Test SSH connection (try "echo ok", fall back to sftp for restricted shells)
        try:
            result = subprocess.run(
                cmd + ["echo", "ok"],
                capture_output=True, text=True, timeout=15, env=env,
            )
            if result.returncode != 0:
                sftp_result = subprocess.run(
                    ssh.sftp_cmd(), input="bye\n",
                    capture_output=True, text=True, timeout=15, env=env,
                )
                if sftp_result.returncode != 0:
                    return False, f"SSH connection failed: {result.stderr.strip() or 'unknown error'}"
                return None, "Connected via SFTP (restricted shell detected — normal commands not available)"
        except subprocess.TimeoutExpired:
            return False, "SSH connection timed out"
        except OSError as e:
            return False, f"SSH connection failed: {e}"

        # Step 2: Check first folder if specified
        if target.folders:
            folder_list = [f.strip() for f in target.folders.split(",") if f.strip()]
            try:
                result = subprocess.run(
                    cmd + ["test", "-d", folder_list[0]],
                    capture_output=True, text=True, timeout=15, env=env,
                )
                if result.returncode != 0:
                    return None, f"Warning: folder '{folder_list[0]}' not accessible on remote"
            except (subprocess.TimeoutExpired, OSError):
                pass
        return True, None

    if target.source_type == "s3":
        from lib.rclone_test import test_rclone_s3
        return test_rclone_s3(
            bucket=target.source_s3_bucket,
            region=target.source_s3_region,
            endpoint=target.source_s3_endpoint,
            access_key_id=target.source_s3_access_key_id,
            secret_access_key=target.source_s3_secret_access_key,
            provider=target.source_s3_provider,
        )

    if target.source_type == "gdrive":
        from lib.rclone_test import test_rclone_gdrive
        return test_rclone_gdrive(
            sa_file=target.source_gdrive_sa_file,
            root_folder_id=target.source_gdrive_root_folder_id,
        )

    if target.source_type == "rclone":
        from lib.rclone_test import test_rclone_generic
        return test_rclone_generic(
            config_path=target.source_rclone_config_path,
            remote_name=target.source_rclone_remote_name,
        )

    return True, None
