from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from tui.config import CONFIG_DIR, write_conf
from tui.models import Remote, Target

_CROC_CODE_RE = re.compile(r'^[a-zA-Z0-9-]+$')
_NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_USERNAME_RE = re.compile(r'^[a-z_][a-z0-9_-]*$')
_HOST_RE = re.compile(r'^[a-zA-Z0-9._-]+$')


def _receive_and_validate(code: str, name: str, config_subdir: str, label: str, timeout: int = 120):
    """
    Shared: receive via croc, validate JSON, save SSH key.
    Returns (data_dict, ssh_key_path, error_msg). On error, data and key are None.
    """
    if not _CROC_CODE_RE.match(code):
        return None, None, "Invalid croc code format. Use only letters, numbers, and hyphens."

    if not _NAME_RE.match(name):
        return None, None, f"Invalid {label} name. Use only letters, numbers, hyphens, and underscores."

    conf_path = CONFIG_DIR / config_subdir / f"{name}.conf"
    if conf_path.exists():
        return None, None, f"{label.capitalize()} '{name}' already exists."

    json_path = None
    tmpdir = tempfile.mkdtemp(prefix="gniza-autoconf-")
    try:
        env = os.environ.copy()
        env["CROC_SECRET"] = code
        result = subprocess.run(
            ["croc", "--yes", "--overwrite"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            return None, None, f"croc receive failed: {stderr or 'unknown error'}"

        received = [f for f in os.listdir(tmpdir) if os.path.isfile(os.path.join(tmpdir, f))]
        if not received:
            return None, None, "No file received from croc."

        json_path = os.path.join(tmpdir, received[0])
        with open(json_path, "r") as f:
            data = json.load(f)

        if data.get("type") != "gniza-remote-setup":
            return None, None, "Invalid payload: not a gniza remote setup file."
        if data.get("version") != 1:
            return None, None, f"Unsupported payload version: {data.get('version')}"

        # Validate fields
        host = data.get("host", "")
        if not host or not _HOST_RE.match(host):
            return None, None, f"Invalid host in payload: {host!r}"
        port = data.get("port", "22")
        try:
            port_int = int(port)
            if not (1 <= port_int <= 65535):
                raise ValueError
        except (ValueError, TypeError):
            return None, None, f"Invalid port in payload: {port!r}"
        user = data.get("user", "gniza")
        if not _USERNAME_RE.match(user):
            return None, None, f"Invalid user in payload: {user!r}"
        base = data.get("base", "/backups")
        if ".." in base:
            return None, None, f"Invalid base path in payload (contains '..'): {base!r}"

        # Normalize validated fields back into data
        data["host"] = host
        data["port"] = str(port_int)
        data["user"] = user
        data["base"] = base
        sudo = data.get("sudo", "yes")
        data["sudo"] = sudo if sudo in ("yes", "no") else "yes"

        # Save private key
        ssh_dir = Path.home() / ".ssh"
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        ssh_key_path = ssh_dir / f"gniza_{name}"

        private_key = data.get("private_key", "")
        private_key = private_key.replace("\\n", "\n")
        if not private_key.endswith("\n"):
            private_key += "\n"

        ssh_key_path.write_text(private_key)
        ssh_key_path.chmod(0o600)

        return data, ssh_key_path, None

    except subprocess.TimeoutExpired:
        return None, None, f"croc receive timed out after {timeout} seconds."
    except json.JSONDecodeError as e:
        try:
            preview = Path(json_path).read_text()[:200] if json_path else "(no file)"
        except Exception:
            preview = "(could not read)"
        return None, None, f"Invalid JSON in received file: {e}\nFile content: {preview!r}"
    except OSError as e:
        return None, None, f"File error: {e}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def receive_and_configure(code: str, dest_name: str, timeout: int = 120) -> tuple[Remote | None, str | None]:
    """Receive remote config via croc, return (Remote, None) or (None, error_msg)."""
    data, ssh_key_path, error = _receive_and_validate(code, dest_name, "remotes.d", "destination", timeout)
    if error:
        return None, error

    remote = Remote(
        name=dest_name,
        type="ssh",
        host=data["host"],
        port=data["port"],
        user=data["user"],
        auth_method="key",
        key=str(ssh_key_path),
        base=data["base"],
        sudo=data["sudo"],
    )
    return remote, None


def receive_and_configure_source(code: str, source_name: str, folders: str = "", timeout: int = 120) -> tuple[Target | None, str | None]:
    """Receive remote config via croc, return (Target, None) or (None, error_msg)."""
    data, ssh_key_path, error = _receive_and_validate(code, source_name, "targets.d", "source", timeout)
    if error:
        return None, error

    # Use folders from form, fall back to payload
    if not folders:
        folders = data.get("folders", "")

    mysql_enabled = data.get("mysql_enabled", "no")
    postgresql_enabled = data.get("postgresql_enabled", "no")

    target = Target(
        name=source_name,
        folders=folders,
        source_type="ssh",
        source_host=data["host"],
        source_port=data["port"],
        source_user=data["user"],
        source_auth_method="key",
        source_key=str(ssh_key_path),
        source_sudo=data["sudo"],
        mysql_enabled=mysql_enabled if mysql_enabled in ("yes", "no") else "no",
        postgresql_enabled=postgresql_enabled if postgresql_enabled in ("yes", "no") else "no",
    )
    return target, None
