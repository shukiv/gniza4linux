"""SSH-based remote auto-configure -- upload and run setup-remote.sh via SSH."""

import json
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

from lib.ssh import SSHOpts
from lib.validation import VALID_NAME_RE

_tasks = {}  # task_id -> {status, logs, result, error, started_at}

_HOST_RE = re.compile(r'^[a-zA-Z0-9._\-\[\]:]+$')
_USER_RE = re.compile(r'^[a-z_][a-z0-9_.\-]*$')


def validate_inputs(name, ssh_host, ssh_port, ssh_user, backup_user, base_dir, folders):
    """Validate all inputs at the boundary. Returns error string or None."""
    if not name or not VALID_NAME_RE.match(name):
        return "Invalid name."
    if not ssh_host or not _HOST_RE.match(ssh_host):
        return "Invalid SSH host."
    try:
        p = int(ssh_port or "22")
        if not 1 <= p <= 65535:
            return "Port must be 1-65535."
    except ValueError:
        return "Invalid port number."
    if not ssh_user or not _USER_RE.match(ssh_user):
        return "Invalid SSH user."
    if backup_user and not _USER_RE.match(backup_user):
        return "Invalid backup user name."
    if base_dir and (".." in base_dir or not base_dir.startswith("/")):
        return "Base directory must be an absolute path."
    if folders:
        for f in folders.split(","):
            f = f.strip()
            if f and (".." in f or not f.startswith("/")):
                return f"Invalid folder path: {f}"
    return None


def start_ssh_setup(task_id, name, mode, ssh_host, ssh_port, ssh_user,
                    ssh_password, ssh_key, backup_user, base_dir, folders):
    """Start SSH setup in a background thread."""
    # Clean stale tasks (older than 10 minutes)
    now = time.time()
    stale = [k for k, v in _tasks.items() if now - v.get("started_at", 0) > 600]
    for k in stale:
        _tasks.pop(k, None)

    _tasks[task_id] = {
        "status": "running", "logs": [], "result": None,
        "error": None, "started_at": time.time(),
    }
    t = threading.Thread(
        target=_run_ssh_setup,
        args=(task_id, name, mode, ssh_host, ssh_port, ssh_user,
              ssh_password, ssh_key, backup_user, base_dir, folders),
        daemon=True,
    )
    t.start()


def get_task(task_id):
    return _tasks.get(task_id)


def pop_task(task_id):
    return _tasks.pop(task_id, None)


def _log(task_id, msg):
    task = _tasks.get(task_id)
    if task:
        task["logs"].append(msg)


def _run_ssh_setup(task_id, name, mode, ssh_host, ssh_port, ssh_user,
                   ssh_password, ssh_key, backup_user, base_dir, folders):
    """Background worker."""
    task = _tasks[task_id]
    try:
        ssh = SSHOpts.adhoc(ssh_host, ssh_port, ssh_user, key=ssh_key, password=ssh_password)

        # 1. Test SSH
        _log(task_id, "Testing SSH connection...")
        r = ssh.run("echo ok", timeout=15)
        if r.returncode != 0:
            task.update(status="error", error=f"SSH connection failed: {r.stderr.strip()}")
            return
        _log(task_id, "SSH connection OK.")

        # 2. Check root/sudo
        _log(task_id, "Checking root access...")
        r = ssh.run("id -u", timeout=10)
        is_root = r.stdout.strip() == "0"
        if not is_root:
            r = ssh.run("sudo -n id -u", timeout=10)
            if r.stdout.strip() != "0":
                task.update(status="error", error="User must be root or have passwordless sudo.")
                return
        _log(task_id, "Root access confirmed.")

        # 3. Upload setup-remote.sh
        _log(task_id, "Uploading setup script...")
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "setup-remote.sh"
        script_content = script_path.read_text()
        remote_script = "/tmp/gniza-setup-remote.sh"

        r = ssh.run(f"cat > {remote_script} && chmod +x {remote_script}",
                     timeout=30, input=script_content)
        if r.returncode != 0:
            task.update(status="error", error=f"Failed to upload script: {r.stderr.strip()}")
            return
        _log(task_id, "Script uploaded.")

        # 4. Execute
        _log(task_id, "Running setup on remote server (this may take a minute)...")
        run_args = [f"--{mode}", "--non-interactive", "--json-stdout",
                    f"--user={shlex.quote(backup_user)}"]
        if mode == "destination" and base_dir:
            run_args.append(f"--base={shlex.quote(base_dir)}")
        if mode == "source" and folders:
            run_args.append(f"--folders={shlex.quote(folders)}")

        prefix = "sudo " if not is_root else ""
        remote_cmd = f"{prefix}{shlex.quote(remote_script)} {' '.join(run_args)}"

        r = ssh.run(remote_cmd, timeout=180)

        # Parse stderr for progress lines
        for line in (r.stderr or "").splitlines():
            line = line.strip()
            if line and "[INFO]" in line:
                # Strip ANSI color codes
                clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                _log(task_id, clean)

        # Cleanup remote script
        ssh.run(f"rm -f {remote_script}", timeout=10)

        if r.returncode != 0:
            stderr_clean = re.sub(r'\x1b\[[0-9;]*m', '', r.stderr.strip()) if r.stderr else ""
            task.update(status="error", error=f"Remote setup failed: {stderr_clean[-500:]}")
            return

        # 5. Parse JSON
        _log(task_id, "Parsing configuration...")
        stdout = r.stdout.strip()
        if not stdout:
            task.update(status="error", error="No configuration received from remote server.")
            return

        # JSON might have leading non-JSON lines, find the JSON object
        json_start = stdout.find('{')
        if json_start < 0:
            task.update(status="error", error="Invalid setup output (no JSON found).")
            return
        data = json.loads(stdout[json_start:])

        # 6. Save SSH key
        _log(task_id, "Saving SSH key...")
        ssh_dir = Path.home() / ".ssh"
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        key_path = ssh_dir / f"gniza_{name}"

        private_key = data.get("private_key", "").replace("\\n", "\n")
        if not private_key.endswith("\n"):
            private_key += "\n"
        key_path.write_text(private_key)
        key_path.chmod(0o600)

        _log(task_id, "Setup complete!")
        task.update(status="done", result=data, key_path=str(key_path))

    except subprocess.TimeoutExpired:
        task.update(status="error", error="SSH operation timed out (3 minutes).")
    except json.JSONDecodeError as e:
        task.update(status="error", error=f"Failed to parse setup output: {e}")
    except Exception as e:
        task.update(status="error", error=str(e))
