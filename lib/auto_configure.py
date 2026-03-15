import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from tui.config import CONFIG_DIR, write_conf
from tui.models import Remote

_CROC_CODE_RE = re.compile(r'^[a-zA-Z0-9-]+$')
_DEST_NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_USERNAME_RE = re.compile(r'^[a-z_][a-z0-9_-]*$')
_HOST_RE = re.compile(r'^[a-zA-Z0-9._-]+$')


def receive_and_configure(code: str, dest_name: str, timeout: int = 120) -> tuple[Remote | None, str | None]:
    """
    Receive remote config via croc, save SSH key, return (Remote, None) or (None, error_msg).
    """
    if not _CROC_CODE_RE.match(code):
        return None, "Invalid croc code format. Use only letters, numbers, and hyphens."

    if not _DEST_NAME_RE.match(dest_name):
        return None, "Invalid destination name. Use only letters, numbers, hyphens, and underscores."

    conf_path = CONFIG_DIR / "remotes.d" / f"{dest_name}.conf"
    if conf_path.exists():
        return None, f"Destination '{dest_name}' already exists."

    tmpdir = tempfile.mkdtemp(prefix="gniza-autoconf-")
    try:
        # Receive file via croc (CROC_SECRET for v10+, code as arg for older)
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
            return None, f"croc receive failed: {stderr or 'unknown error'}"

        # Find the received file
        received = [f for f in os.listdir(tmpdir) if os.path.isfile(os.path.join(tmpdir, f))]
        if not received:
            return None, "No file received from croc."

        json_path = os.path.join(tmpdir, received[0])
        with open(json_path, "r") as f:
            data = json.load(f)

        # Validate payload
        if data.get("type") != "gniza-remote-setup":
            return None, "Invalid payload: not a gniza remote setup file."
        if data.get("version") != 1:
            return None, f"Unsupported payload version: {data.get('version')}"

        # Validate payload fields
        host = data.get("host", "")
        if not host or not _HOST_RE.match(host):
            return None, f"Invalid host in payload: {host!r}"
        port = data.get("port", "22")
        try:
            port_int = int(port)
            if not (1 <= port_int <= 65535):
                raise ValueError
        except (ValueError, TypeError):
            return None, f"Invalid port in payload: {port!r}"
        user = data.get("user", "gniza")
        if not _USERNAME_RE.match(user):
            return None, f"Invalid user in payload: {user!r}"
        base = data.get("base", "/backups")
        if ".." in base:
            return None, f"Invalid base path in payload (contains '..'): {base!r}"

        # Save private key
        ssh_dir = Path.home() / ".ssh"
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        ssh_key_path = ssh_dir / f"gniza_{dest_name}"

        if ssh_key_path.exists():
            return None, f"SSH key file already exists: {ssh_key_path}. Remove it first or use a different name."

        private_key = data.get("private_key", "")
        # Unescape \\n to actual newlines
        private_key = private_key.replace("\\n", "\n")
        if not private_key.endswith("\n"):
            private_key += "\n"

        ssh_key_path.write_text(private_key)
        ssh_key_path.chmod(0o600)

        # Build Remote object
        sudo = data.get("sudo", "yes")
        if sudo not in ("yes", "no"):
            sudo = "yes"
        remote = Remote(
            name=dest_name,
            type="ssh",
            host=host,
            port=str(port_int),
            user=user,
            auth_method="key",
            key=str(ssh_key_path),
            base=base,
            sudo=sudo,
        )

        return remote, None

    except subprocess.TimeoutExpired:
        return None, f"croc receive timed out after {timeout} seconds."
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON in received file: {e}"
    except OSError as e:
        return None, f"File error: {e}"
    finally:
        # Clean up temp dir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
