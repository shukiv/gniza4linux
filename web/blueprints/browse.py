import configparser
import json
import os
import re
import shlex
import subprocess
import tempfile

from flask import Blueprint, render_template, request
from tui.config import CONFIG_DIR, list_conf_dir, parse_conf
from web.app import login_required
from web.ssh_utils import ssh_cmd_from_conf

bp = Blueprint("browse", __name__, url_prefix="/browse")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_VALID_SUBPATH_RE = re.compile(r'^[A-Za-z0-9_./ -]*$')


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/")
@login_required
def index():
    sources = list_conf_dir("targets.d")
    destinations = list_conf_dir("remotes.d")
    rclone_remotes = []
    try:
        result = subprocess.run(
            ["rclone", "config", "dump"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            rclone_remotes = [
                {"name": k, "type": v.get("type", "unknown")}
                for k, v in data.items()
            ]
    except Exception:
        pass
    # Support deep-linking: ?type=destinations&name=rasp
    preselect_type = request.args.get("type", "")
    preselect_name = request.args.get("name", "")
    return render_template(
        "browse/index.html",
        sources=sources,
        destinations=destinations,
        rclone_remotes=rclone_remotes,
        preselect_type=preselect_type,
        preselect_name=preselect_name,
    )


# -- Destination routes -----------------------------------------------------

@bp.route("/destination/<name>")
@login_required
def destination(name):
    if not _VALID_NAME_RE.match(name):
        return _error_partial("Invalid name.")
    subpath = request.args.get("path", "").strip("/")
    if _bad_path(subpath):
        return _error_partial("Invalid path.")
    conf = _get_remote_conf(name)
    if not conf:
        return _error_partial("Destination not found.")

    rtype = conf.get("REMOTE_TYPE", "ssh")
    base = conf.get("REMOTE_BASE", "/backups").rstrip("/")
    full_path = f"{base}/{subpath}" if subpath else base

    if rtype == "local":
        result, error = _list_dir_local(full_path)
    elif rtype == "ssh":
        result, error = _list_dir_ssh(conf, full_path)
    elif rtype in ("s3", "gdrive", "rclone"):
        result, error = _list_dir_rclone_generic(conf, subpath, base_prefix=base)
    else:
        result, error = None, f"Unsupported type: {rtype}"

    dirs, files = result if result else ([], [])
    return render_template(
        "browse/browse_partial.html",
        dirs=dirs, files=files, error=error or "",
        browse_type="destination", browse_name=name, subpath=subpath,
    )


@bp.route("/destination/<name>/children")
@login_required
def destination_children(name):
    if not _VALID_NAME_RE.match(name):
        return _error_partial("Invalid name.")
    subpath = request.args.get("path", "").strip("/")
    if _bad_path(subpath):
        return _error_partial("Invalid path.")
    conf = _get_remote_conf(name)
    if not conf:
        return _error_partial("Destination not found.")

    rtype = conf.get("REMOTE_TYPE", "ssh")
    base = conf.get("REMOTE_BASE", "/backups").rstrip("/")
    full_path = f"{base}/{subpath}" if subpath else base

    if rtype == "local":
        result, error = _list_dir_local(full_path)
    elif rtype == "ssh":
        result, error = _list_dir_ssh(conf, full_path)
    elif rtype in ("s3", "gdrive", "rclone"):
        result, error = _list_dir_rclone_generic(conf, subpath, base_prefix=base)
    else:
        result, error = None, f"Unsupported type: {rtype}"

    dirs, files = result if result else ([], [])
    return render_template(
        "browse/browse_children.html",
        dirs=dirs, files=files,
        browse_type="destination", browse_name=name, parent_path=subpath,
    )


# -- Source routes ----------------------------------------------------------

@bp.route("/source/<name>")
@login_required
def source(name):
    if not _VALID_NAME_RE.match(name):
        return _error_partial("Invalid name.")
    subpath = request.args.get("path", "").strip("/")
    if _bad_path(subpath):
        return _error_partial("Invalid path.")
    conf = _get_target_conf(name)
    if not conf:
        return _error_partial("Source not found.")

    source_type = conf.get("TARGET_SOURCE_TYPE", "local")

    if source_type == "local":
        if not subpath:
            folders = [f.strip() for f in conf.get("TARGET_FOLDERS", "").split(",") if f.strip()]
            return render_template(
                "browse/browse_partial.html",
                dirs=folders, files=[], error="",
                browse_type="source", browse_name=name, subpath="",
                is_root_folders=True,
            )
        result, error = _list_dir_local(subpath)
    elif source_type == "ssh":
        if not subpath:
            folders = [f.strip() for f in conf.get("TARGET_FOLDERS", "").split(",") if f.strip()]
            return render_template(
                "browse/browse_partial.html",
                dirs=folders, files=[], error="",
                browse_type="source", browse_name=name, subpath="",
                is_root_folders=True,
            )
        ssh_conf = {
            "REMOTE_HOST": conf.get("TARGET_SOURCE_HOST", ""),
            "REMOTE_PORT": conf.get("TARGET_SOURCE_PORT", "22"),
            "REMOTE_USER": conf.get("TARGET_SOURCE_USER", "root"),
            "REMOTE_KEY": conf.get("TARGET_SOURCE_KEY", ""),
            "REMOTE_PASSWORD": conf.get("TARGET_SOURCE_PASSWORD", ""),
            "REMOTE_AUTH_METHOD": conf.get("TARGET_SOURCE_AUTH_METHOD", "key"),
        }
        result, error = _list_dir_ssh(ssh_conf, subpath)
    elif source_type in ("s3", "gdrive"):
        result, error = None, "S3/GDrive source browsing not yet supported"
    else:
        result, error = None, f"Unsupported source type: {source_type}"

    dirs, files = result if result else ([], [])
    return render_template(
        "browse/browse_partial.html",
        dirs=dirs, files=files, error=error or "",
        browse_type="source", browse_name=name, subpath=subpath,
    )


@bp.route("/source/<name>/children")
@login_required
def source_children(name):
    if not _VALID_NAME_RE.match(name):
        return _error_partial("Invalid name.")
    subpath = request.args.get("path", "").strip("/")
    if _bad_path(subpath):
        return _error_partial("Invalid path.")
    conf = _get_target_conf(name)
    if not conf:
        return _error_partial("Source not found.")

    source_type = conf.get("TARGET_SOURCE_TYPE", "local")

    if source_type == "local":
        result, error = _list_dir_local(subpath)
    elif source_type == "ssh":
        ssh_conf = {
            "REMOTE_HOST": conf.get("TARGET_SOURCE_HOST", ""),
            "REMOTE_PORT": conf.get("TARGET_SOURCE_PORT", "22"),
            "REMOTE_USER": conf.get("TARGET_SOURCE_USER", "root"),
            "REMOTE_KEY": conf.get("TARGET_SOURCE_KEY", ""),
            "REMOTE_PASSWORD": conf.get("TARGET_SOURCE_PASSWORD", ""),
            "REMOTE_AUTH_METHOD": conf.get("TARGET_SOURCE_AUTH_METHOD", "key"),
        }
        result, error = _list_dir_ssh(ssh_conf, subpath)
    elif source_type in ("s3", "gdrive"):
        result, error = None, "S3/GDrive source browsing not yet supported"
    else:
        result, error = None, f"Unsupported source type: {source_type}"

    dirs, files = result if result else ([], [])
    return render_template(
        "browse/browse_children.html",
        dirs=dirs, files=files,
        browse_type="source", browse_name=name, parent_path=subpath,
    )


# -- Rclone remote routes --------------------------------------------------

@bp.route("/rclone/<name>")
@login_required
def rclone_remote(name):
    if not _VALID_NAME_RE.match(name):
        return _error_partial("Invalid name.")
    subpath = request.args.get("path", "").strip("/")
    if _bad_path(subpath):
        return _error_partial("Invalid path.")

    result, error = _list_dir_rclone_remote(name, subpath)
    dirs, files = result if result else ([], [])
    return render_template(
        "browse/browse_partial.html",
        dirs=dirs, files=files, error=error or "",
        browse_type="rclone_remote", browse_name=name, subpath=subpath,
    )


@bp.route("/rclone/<name>/children")
@login_required
def rclone_remote_children(name):
    if not _VALID_NAME_RE.match(name):
        return _error_partial("Invalid name.")
    subpath = request.args.get("path", "").strip("/")
    if _bad_path(subpath):
        return _error_partial("Invalid path.")

    result, error = _list_dir_rclone_remote(name, subpath)
    dirs, files = result if result else ([], [])
    return render_template(
        "browse/browse_children.html",
        dirs=dirs, files=files,
        browse_type="rclone_remote", browse_name=name, parent_path=subpath,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bad_path(subpath):
    return (subpath and not _VALID_SUBPATH_RE.match(subpath)) or ".." in subpath


def _error_partial(msg):
    return f'<div class="alert alert-error"><span>{msg}</span></div>'


def _get_remote_conf(name):
    conf = CONFIG_DIR / "remotes.d" / f"{name}.conf"
    if not conf.is_file():
        return None
    return parse_conf(conf)


def _get_target_conf(name):
    conf = CONFIG_DIR / "targets.d" / f"{name}.conf"
    if not conf.is_file():
        return None
    return parse_conf(conf)


def _list_dir_local(path):
    """List dirs and files at a local path. Returns ((dirs, files), None) or (None, error)."""
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        return None, "Directory not found"
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return None, "Permission denied"
    dirs, files = [], []
    for e in entries:
        full = os.path.join(path, e)
        if os.path.isdir(full):
            dirs.append(e)
        elif os.path.isfile(full):
            files.append(e)
    return (dirs, files), None


def _list_dir_ssh(remote_conf, path):
    """List dirs and files via SSH."""
    sq = shlex.quote(path)
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
        dirs, files = [], []
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
            rclone_remote_name = remote_conf.get("RCLONE_REMOTE_NAME", "")
            rclone_config_path = remote_conf.get("RCLONE_CONFIG_PATH", "")
            if not rclone_remote_name:
                os.close(fd)
                os.unlink(path)
                return None
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


def _list_dir_rclone_generic(remote_conf, subpath="", base_prefix=""):
    """List dirs and files on an rclone-backed destination."""
    conf_path = _build_rclone_conf(remote_conf)
    if not conf_path:
        return None, "Failed to build rclone configuration"
    rtype = remote_conf.get("REMOTE_TYPE", "ssh")
    if rtype == "s3":
        bucket = remote_conf.get("S3_BUCKET", "")
        rpath = f"remote:{bucket}{base_prefix}" + (f"/{subpath}" if subpath else "")
    else:
        rpath = f"remote:{base_prefix}" + (f"/{subpath}" if subpath else "")
    try:
        return _rclone_lsf(conf_path, rpath)
    finally:
        try:
            os.unlink(conf_path)
        except OSError:
            pass


def _list_dir_rclone_remote(name, subpath=""):
    """List dirs and files on a standalone rclone remote (from system rclone config)."""
    rpath = f"{name}:{subpath}" if subpath else f"{name}:"
    try:
        return _rclone_lsf(None, rpath)
    except Exception as e:
        return None, str(e)


def _rclone_lsf(conf_path, rpath):
    """Run rclone lsf for dirs and files."""
    base_cmd = ["rclone", "lsf"]
    if conf_path:
        base_cmd += ["--config", conf_path]
    try:
        dir_result = subprocess.run(
            base_cmd + ["--dirs-only", rpath],
            capture_output=True, text=True, timeout=30,
        )
        dirs = []
        if dir_result.returncode == 0:
            dirs = sorted([d.rstrip("/") for d in dir_result.stdout.strip().splitlines() if d.strip()])
        file_result = subprocess.run(
            base_cmd + ["--files-only", rpath],
            capture_output=True, text=True, timeout=30,
        )
        files = []
        if file_result.returncode == 0:
            files = sorted([f.strip() for f in file_result.stdout.strip().splitlines() if f.strip()])
        if dir_result.returncode != 0 and file_result.returncode != 0:
            return None, dir_result.stderr.strip() or "Failed to list remote path"
        return (dirs, files), None
    except FileNotFoundError:
        return None, "rclone is not installed"
    except subprocess.TimeoutExpired:
        return None, "Connection timed out"
    except OSError as e:
        return None, str(e)
