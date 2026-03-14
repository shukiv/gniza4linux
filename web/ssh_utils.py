"""Shared SSH command builder used by web blueprints and TUI screens."""

from pathlib import Path


def ssh_cmd(host, port="22", user="root", key="", password=""):
    """Build an SSH command list."""
    ssh_opts = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        "-o", "ConnectTimeout=10",
        "-p", port or "22",
    ]
    if not password:
        ssh_opts += ["-o", "BatchMode=yes"]
    if key:
        ssh_opts += ["-i", key]
    ssh_opts.append(f"{user}@{host}")
    if password:
        return ["sshpass", "-e"] + ssh_opts
    return ssh_opts


def sftp_cmd(host, port="22", user="root", key="", password=""):
    """Build an SFTP command list."""
    opts = ["-o", f"Port={port}", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
    if key:
        opts += ["-o", f"IdentityFile={key}", "-o", "BatchMode=yes"]
    if password:
        cmd = ["sshpass", "-e", "sftp"] + opts
    else:
        cmd = ["sftp"] + opts
    cmd.append(f"{user}@{host}")
    return cmd


def ssh_cmd_from_conf(remote_conf):
    """Build SSH command prefix from remote config dict.

    Returns (cmd_list, password_or_None).
    """
    host = remote_conf.get("REMOTE_HOST", "")
    port = remote_conf.get("REMOTE_PORT", "22")
    user = remote_conf.get("REMOTE_USER", "root")
    key = remote_conf.get("REMOTE_KEY", "")
    password = remote_conf.get("REMOTE_PASSWORD", "")
    auth = remote_conf.get("REMOTE_AUTH_METHOD", "key")

    ssh_opts = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        "-o", "ConnectTimeout=10",
        "-p", port or "22",
    ]
    if auth != "password":
        ssh_opts += ["-o", "BatchMode=yes"]
    if key and auth == "key":
        ssh_opts += ["-i", key]
    ssh_opts.append(f"{user}@{host}")
    if password and auth == "password":
        return ["sshpass", "-e"] + ssh_opts, password
    return ssh_opts, None


def get_ssh_keys():
    """Find existing SSH key pairs (private + public)."""
    ssh_dir = Path.home() / ".ssh"
    keys = []
    if ssh_dir.is_dir():
        for pub in sorted(ssh_dir.glob("*.pub")):
            private = pub.with_suffix("")
            try:
                content = pub.read_text().strip()
                keys.append({
                    "name": pub.stem,
                    "private_path": str(private),
                    "pub_path": str(pub),
                    "content": content,
                })
            except OSError:
                pass
    return keys
