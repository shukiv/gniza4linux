import os
import re
import shlex
import socket
import subprocess

from flask import (
    Blueprint, Response, abort, render_template, request, send_file,
)

from tui.config import CONFIG_DIR, list_conf_dir, parse_conf
from web.app import login_required
from web.backend import run_cli_sync
from web.ssh_utils import ssh_cmd_from_conf

bp = Blueprint("snapshots", __name__, url_prefix="/snapshots")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_VALID_SNAPSHOT_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')
# Block path traversal
_VALID_SUBPATH_RE = re.compile(r'^[A-Za-z0-9_./ -]*$')


def _get_hostname():
    """Get FQDN matching bash 'hostname -f' (used by backup scripts)."""
    try:
        result = subprocess.run(
            ["hostname", "-f"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return socket.getfqdn()


def _get_remote_conf(remote_name):
    """Load remote config dict."""
    conf = CONFIG_DIR / "remotes.d" / f"{remote_name}.conf"
    if not conf.is_file():
        return None
    return parse_conf(conf)


def _snapshot_base(remote_conf, target, snapshot):
    """Build the snapshot base path on the destination."""
    base = remote_conf.get("REMOTE_BASE", "/backups").rstrip("/")
    hostname = _get_hostname()
    return f"{base}/{hostname}/targets/{target}/snapshots/{snapshot}"


def _list_dir_local(path):
    """List dirs and files at a local path. Returns (dirs, files) or (None, error)."""
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        return None, "Directory not found"
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return None, "Permission denied"
    dirs = []
    files = []
    for e in entries:
        full = os.path.join(path, e)
        if os.path.isdir(full):
            dirs.append(e)
        elif os.path.isfile(full):
            files.append(e)
    return (dirs, files), None


def _list_dir_ssh(remote_conf, path):
    """List dirs and files at a path on an SSH remote. Returns (dirs, files) or (None, error)."""
    sq = shlex.quote(path)
    # List dirs and files separately with markers
    cmd_str = (
        f"if [ -d {sq} ]; then "
        f"  for f in {sq}/*; do "
        f"    [ -e \"$f\" ] || continue; "
        f"    if [ -d \"$f\" ]; then echo \"D:$(basename \"$f\")\"; "
        f"    else echo \"F:$(basename \"$f\")\"; fi; "
        f"  done | sort; "
        f"else echo 'ERROR:not_found'; fi"
    )
    cmd, sshpass_pw = ssh_cmd_from_conf(remote_conf)
    cmd = cmd + [cmd_str]
    env = None
    if sshpass_pw:
        env = os.environ.copy()
        env["SSHPASS"] = sshpass_pw
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=env)
        if result.returncode != 0:
            return None, result.stderr.strip() or "SSH connection failed"
        dirs = []
        files = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line == "ERROR:not_found":
                return None, "Directory not found"
            if line.startswith("D:"):
                dirs.append(line[2:])
            elif line.startswith("F:"):
                files.append(line[2:])
        return (dirs, files), None
    except subprocess.TimeoutExpired:
        return None, "Connection timed out"
    except OSError as e:
        return None, str(e)


def _build_rclone_conf(remote_conf):
    """Build a temporary rclone config file from remote config dict."""
    import tempfile
    rtype = remote_conf.get("REMOTE_TYPE", "ssh")
    fd, path = tempfile.mkstemp(suffix=".conf", prefix="gniza-rclone-")
    os.fchmod(fd, 0o600)
    try:
        if rtype == "s3":
            content = (
                "[remote]\n"
                "type = s3\n"
                f"provider = {remote_conf.get('S3_PROVIDER', 'AWS')}\n"
                f"access_key_id = {remote_conf.get('S3_ACCESS_KEY_ID', '')}\n"
                f"secret_access_key = {remote_conf.get('S3_SECRET_ACCESS_KEY', '')}\n"
                f"region = {remote_conf.get('S3_REGION', 'us-east-1')}\n"
            )
            endpoint = remote_conf.get("S3_ENDPOINT", "")
            if endpoint:
                content += f"endpoint = {endpoint}\n"
        elif rtype == "gdrive":
            content = (
                "[remote]\n"
                "type = drive\n"
                "scope = drive\n"
                f"service_account_file = {remote_conf.get('GDRIVE_SERVICE_ACCOUNT_FILE', '')}\n"
            )
            root_folder = remote_conf.get("GDRIVE_ROOT_FOLDER_ID", "")
            if root_folder:
                content += f"root_folder_id = {root_folder}\n"
        elif rtype == "rclone":
            # Read the user's rclone config and extract the named remote section
            rclone_remote_name = remote_conf.get("RCLONE_REMOTE_NAME", "")
            rclone_config_path = remote_conf.get("RCLONE_CONFIG_PATH", "")
            if not rclone_remote_name:
                os.close(fd)
                os.unlink(path)
                return None
            # Find the rclone config file
            if not rclone_config_path:
                try:
                    result = subprocess.run(
                        ["rclone", "config", "file"],
                        capture_output=True, text=True, timeout=10,
                    )
                    if result.returncode == 0:
                        for line in result.stdout.strip().splitlines():
                            line = line.strip()
                            if line and not line.startswith("Configuration"):
                                rclone_config_path = line
                                break
                except Exception:
                    pass
            if not rclone_config_path or not os.path.isfile(rclone_config_path):
                os.close(fd)
                os.unlink(path)
                return None
            # Parse the named remote section and rewrite as [remote]
            import configparser
            cfg = configparser.ConfigParser()
            cfg.read(rclone_config_path)
            if rclone_remote_name not in cfg:
                os.close(fd)
                os.unlink(path)
                return None
            content = "[remote]\n"
            for key, val in cfg[rclone_remote_name].items():
                content += f"{key} = {val}\n"
        else:
            os.close(fd)
            os.unlink(path)
            return None
        os.write(fd, content.encode())
        os.close(fd)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        return None
    return path


def _rclone_remote_path(remote_conf, subpath=""):
    """Build the rclone remote path including hostname prefix."""
    rtype = remote_conf.get("REMOTE_TYPE", "ssh")
    base = remote_conf.get("REMOTE_BASE", "/backups").rstrip("/")
    hostname = _get_hostname()
    if rtype == "s3":
        bucket = remote_conf.get("S3_BUCKET", "")
        return f"remote:{bucket}{base}/{hostname}" + (f"/{subpath}" if subpath else "")
    elif rtype == "gdrive":
        return f"remote:{base}/{hostname}" + (f"/{subpath}" if subpath else "")
    elif rtype == "rclone":
        return f"remote:{base}/{hostname}" + (f"/{subpath}" if subpath else "")
    return ""


def _list_dir_rclone(remote_conf, target, snapshot, subpath=""):
    """List dirs and files at a path on an S3/gdrive remote. Returns ((dirs, files), None) or (None, error)."""
    conf_path = _build_rclone_conf(remote_conf)
    if not conf_path:
        return None, "Failed to build rclone configuration"

    snap_subpath = f"targets/{target}/snapshots/{snapshot}"
    if subpath:
        snap_subpath += f"/{subpath.strip('/')}"

    rpath = _rclone_remote_path(remote_conf, snap_subpath)

    try:
        # List directories
        dir_result = subprocess.run(
            ["rclone", "lsf", "--config", conf_path, "--dirs-only", rpath],
            capture_output=True, text=True, timeout=30,
        )
        dirs = []
        if dir_result.returncode == 0:
            dirs = [d.rstrip("/") for d in dir_result.stdout.strip().splitlines() if d.strip()]
            # Filter out the .complete marker directory if present
            dirs = [d for d in dirs if d != ".complete"]

        # List files
        file_result = subprocess.run(
            ["rclone", "lsf", "--config", conf_path, "--files-only", rpath],
            capture_output=True, text=True, timeout=30,
        )
        files = []
        if file_result.returncode == 0:
            files = [f.strip() for f in file_result.stdout.strip().splitlines() if f.strip()]
            # Filter out internal markers
            files = [f for f in files if f not in (".complete",)]

        if dir_result.returncode != 0 and file_result.returncode != 0:
            err = dir_result.stderr.strip() or "Failed to list remote path"
            return None, err

        return (sorted(dirs), sorted(files)), None
    except FileNotFoundError:
        return None, "rclone is not installed"
    except subprocess.TimeoutExpired:
        return None, "Connection timed out"
    except OSError as e:
        return None, str(e)
    finally:
        try:
            os.unlink(conf_path)
        except OSError:
            pass


def _list_snapshot_dir(remote_conf, target, snapshot, subpath=""):
    """List dirs and files at a subpath within a snapshot."""
    rtype = remote_conf.get("REMOTE_TYPE", "ssh")

    if rtype in ("s3", "gdrive", "rclone"):
        return _list_dir_rclone(remote_conf, target, snapshot, subpath)

    base = _snapshot_base(remote_conf, target, snapshot)
    full_path = base if not subpath else f"{base}/{subpath.strip('/')}"

    if rtype == "local":
        return _list_dir_local(full_path)
    elif rtype == "ssh":
        return _list_dir_ssh(remote_conf, full_path)
    else:
        return None, f"Unsupported destination type: {rtype}"


@bp.route("/")
@login_required
def index():
    targets = list_conf_dir("targets.d")
    remotes = list_conf_dir("remotes.d")
    return render_template("snapshots/index.html", targets=targets, remotes=remotes)


@bp.route("/list/<target>/<remote>")
@login_required
def list_snapshots(target, remote):
    if not _VALID_NAME_RE.match(target) or not _VALID_NAME_RE.match(remote):
        return render_template("snapshots/list_partial.html", snapshots=[], error="Invalid name.", target=target, remote=remote)
    snapshot_list = []
    error = ""
    try:
        rc, stdout, stderr = run_cli_sync(
            "snapshots", "list", f"--source={target}", f"--destination={remote}",
            timeout=30,
        )
        if rc == 0 and stdout.strip():
            snapshot_list = [s.strip() for s in stdout.strip().splitlines() if s.strip()]
        elif rc != 0:
            error = stderr.strip() or "Failed to list snapshots."
    except Exception:
        error = "Timed out listing snapshots."
    return render_template("snapshots/list_partial.html", snapshots=snapshot_list, error=error, target=target, remote=remote)


@bp.route("/browse/<target>/<remote>/<snapshot>")
@login_required
def browse(target, remote, snapshot):
    """Browse the top-level of a snapshot as a file manager."""
    if not _VALID_NAME_RE.match(target) or not _VALID_NAME_RE.match(remote) or not _VALID_SNAPSHOT_RE.match(snapshot):
        return render_template("snapshots/browse_partial.html", dirs=[], files=[], error="Invalid input.",
                               target=target, remote=remote, snapshot=snapshot, subpath="")
    subpath = request.args.get("path", "").strip("/")
    if subpath and not _VALID_SUBPATH_RE.match(subpath):
        return render_template("snapshots/browse_partial.html", dirs=[], files=[], error="Invalid path.",
                               target=target, remote=remote, snapshot=snapshot, subpath="")
    # Block traversal
    if ".." in subpath:
        return render_template("snapshots/browse_partial.html", dirs=[], files=[], error="Invalid path.",
                               target=target, remote=remote, snapshot=snapshot, subpath="")

    remote_conf = _get_remote_conf(remote)
    if not remote_conf:
        return render_template("snapshots/browse_partial.html", dirs=[], files=[], error="Destination not found.",
                               target=target, remote=remote, snapshot=snapshot, subpath=subpath)

    result, error = _list_snapshot_dir(remote_conf, target, snapshot, subpath)
    dirs, files = result if result else ([], [])
    return render_template("snapshots/browse_partial.html",
                           dirs=dirs, files=files, error=error or "",
                           target=target, remote=remote, snapshot=snapshot, subpath=subpath)


@bp.route("/browse_children/<target>/<remote>/<snapshot>")
@login_required
def browse_children(target, remote, snapshot):
    """Lazy-load children of a directory within a snapshot."""
    if not _VALID_NAME_RE.match(target) or not _VALID_NAME_RE.match(remote) or not _VALID_SNAPSHOT_RE.match(snapshot):
        return ""
    subpath = request.args.get("path", "").strip("/")
    if (subpath and not _VALID_SUBPATH_RE.match(subpath)) or ".." in subpath:
        return ""

    remote_conf = _get_remote_conf(remote)
    if not remote_conf:
        return ""

    result, error = _list_snapshot_dir(remote_conf, target, snapshot, subpath)
    if error or not result:
        return '<li><span class="text-base-content/40 italic text-xs px-2 py-1">Cannot read directory</span></li>'
    dirs, files = result
    return render_template("snapshots/browse_children.html",
                           dirs=dirs, files=files,
                           target=target, remote=remote, snapshot=snapshot, parent_path=subpath)


def _stream_process(proc):
    """Yield chunks from a subprocess stdout, then wait and close."""
    try:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            yield chunk
    finally:
        proc.stdout.close()
        proc.wait()


@bp.route("/download/<target>/<remote>/<snapshot>")
@login_required
def download(target, remote, snapshot):
    """Download a file or folder from a snapshot."""
    if not _VALID_NAME_RE.match(target) or not _VALID_NAME_RE.match(remote) or not _VALID_SNAPSHOT_RE.match(snapshot):
        abort(400, "Invalid input.")

    subpath = request.args.get("path", "").strip("/")
    if subpath and not _VALID_SUBPATH_RE.match(subpath):
        abort(400, "Invalid path.")
    if ".." in subpath:
        abort(400, "Invalid path.")
    if not subpath:
        abort(400, "No path specified.")

    item_type = request.args.get("type", "file")  # "file" or "folder"
    if item_type not in ("file", "folder"):
        abort(400, "Invalid type.")

    remote_conf = _get_remote_conf(remote)
    if not remote_conf:
        abort(404, "Destination not found.")

    rtype = remote_conf.get("REMOTE_TYPE", "ssh")
    base = _snapshot_base(remote_conf, target, snapshot)
    full_path = f"{base}/{subpath}"

    filename = os.path.basename(subpath)

    if rtype == "local":
        real_path = os.path.realpath(full_path)
        # Ensure resolved path stays under the snapshot base
        real_base = os.path.realpath(base)
        if not real_path.startswith(real_base + "/") and real_path != real_base:
            abort(400, "Invalid path.")
        if item_type == "file":
            if not os.path.isfile(real_path):
                abort(404, "File not found.")
            return send_file(real_path, as_attachment=True, download_name=filename)
        else:
            if not os.path.isdir(real_path):
                abort(404, "Directory not found.")
            proc = subprocess.Popen(
                ["tar", "czf", "-", "-C", os.path.dirname(real_path), os.path.basename(real_path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            return Response(
                _stream_process(proc),
                mimetype="application/gzip",
                headers={"Content-Disposition": f'attachment; filename="{filename}.tar.gz"'},
            )

    elif rtype == "ssh":
        cmd, sshpass_pw = ssh_cmd_from_conf(remote_conf)
        env = None
        if sshpass_pw:
            env = os.environ.copy()
            env["SSHPASS"] = sshpass_pw

        sq = shlex.quote(full_path)
        if item_type == "file":
            remote_cmd = f"cat {sq}"
            content_type = "application/octet-stream"
            disp = f'attachment; filename="{filename}"'
        else:
            parent = os.path.dirname(full_path)
            basename = os.path.basename(full_path)
            remote_cmd = f"tar czf - -C {shlex.quote(parent)} {shlex.quote(basename)}"
            content_type = "application/gzip"
            disp = f'attachment; filename="{filename}.tar.gz"'

        proc = subprocess.Popen(
            cmd + [remote_cmd],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        return Response(
            _stream_process(proc),
            mimetype=content_type,
            headers={"Content-Disposition": disp},
        )

    elif rtype in ("s3", "gdrive", "rclone"):
        if item_type == "folder":
            abort(400, "Folder download is not supported for S3/GDrive/rclone destinations.")

        snap_subpath = f"targets/{target}/snapshots/{snapshot}/{subpath}"
        rpath = _rclone_remote_path(remote_conf, snap_subpath)
        conf_path = _build_rclone_conf(remote_conf)
        if not conf_path:
            abort(500, "Failed to build rclone configuration.")

        proc = subprocess.Popen(
            ["rclone", "cat", "--config", conf_path, rpath],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        def stream_and_cleanup():
            try:
                yield from _stream_process(proc)
            finally:
                try:
                    os.unlink(conf_path)
                except OSError:
                    pass

        return Response(
            stream_and_cleanup(),
            mimetype="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    else:
        abort(400, f"Unsupported destination type: {rtype}")
