"""Deprecated -- use lib.ssh.SSHOpts instead.

Thin backward-compat shims that delegate to lib.ssh.
"""
from lib.ssh import SSHOpts, get_ssh_keys  # noqa: F401


def ssh_cmd(host, port="22", user="gniza", key="", password=""):
    """Build an SSH command list (compat shim)."""
    return SSHOpts.adhoc(host, port, user, key=key, password=password).ssh_cmd()


def sftp_cmd(host, port="22", user="root", key="", password=""):
    """Build an SFTP command list (compat shim)."""
    return SSHOpts.adhoc(host, port, user, key=key, password=password).sftp_cmd()


def ssh_cmd_from_conf(remote_conf):
    """Build SSH command prefix from remote config dict (compat shim).

    Returns (cmd_list, password_or_None).
    """
    ssh = SSHOpts.for_remote_conf(remote_conf)
    return ssh.ssh_cmd(), ssh.password if ssh.auth_method == "password" else None
