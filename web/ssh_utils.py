"""Shared SSH command builder used by web blueprints and TUI screens."""


def ssh_cmd(host, port="22", user="root", key="", password=""):
    """Build an SSH command list."""
    ssh_opts = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",
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
        "-o", "StrictHostKeyChecking=accept-new",
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
