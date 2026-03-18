import os
import re
from pathlib import Path

_KV_RE = re.compile(r'^([A-Z_][A-Z_0-9]*)=(.*)')
_QUOTED_RE = re.compile(r'^"(.*)"$|^\'(.*)\'$')


def _get_config_dir() -> Path:
    if os.geteuid() == 0:
        return Path("/etc/gniza")
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(xdg) / "gniza"


def _get_log_dir() -> Path:
    if os.geteuid() == 0:
        return Path("/var/log/gniza")
    xdg = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    return Path(xdg) / "gniza" / "log"


CONFIG_DIR = _get_config_dir()
LOG_DIR = _get_log_dir()


def _get_work_dir() -> Path:
    # Check gniza.conf for custom WORK_DIR
    conf_path = CONFIG_DIR / "gniza.conf"
    if conf_path.is_file():
        for line in conf_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("WORK_DIR="):
                val = line.split("=", 1)[1].strip('"').strip("'")
                if val:
                    return Path(val)
    # Default based on mode
    if os.geteuid() == 0:
        return Path("/usr/local/gniza/workdir")
    xdg = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    return Path(xdg) / "gniza" / "workdir"


WORK_DIR = _get_work_dir()


def parse_conf(filepath: Path) -> dict[str, str]:
    data = {}
    if not filepath.is_file():
        return data
    for line in filepath.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _KV_RE.match(line)
        if m:
            key = m.group(1)
            value = m.group(2)
            qm = _QUOTED_RE.match(value)
            if qm:
                value = qm.group(1) if qm.group(1) is not None else qm.group(2)
            data[key] = value
    return data


def _sanitize_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")


def write_conf(filepath: Path, data: dict[str, str]) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    # Merge: preserve existing keys not in the new data
    existing = parse_conf(filepath) if filepath.is_file() else {}
    merged = {**existing, **data}
    lines = []
    for key, value in merged.items():
        lines.append(f'{key}="{_sanitize_value(value)}"')
    filepath.write_text("\n".join(lines) + "\n")
    filepath.chmod(0o600)


def update_conf_key(filepath: Path, key: str, value: str) -> None:
    value = _sanitize_value(value)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if not filepath.is_file():
        filepath.write_text(f'{key}="{value}"\n')
        filepath.chmod(0o600)
        return
    lines = filepath.read_text().splitlines()
    found = False
    for i, line in enumerate(lines):
        m = _KV_RE.match(line.strip())
        if m and m.group(1) == key:
            lines[i] = f'{key}="{value}"'
            found = True
            break
    if not found:
        lines.append(f'{key}="{value}"')
    filepath.write_text("\n".join(lines) + "\n")
    filepath.chmod(0o600)


_conf_dir_cache: dict[str, tuple[float, list[str]]] = {}


def list_conf_dir(subdir: str) -> list[str]:
    d = CONFIG_DIR / subdir
    if not d.is_dir():
        return []
    try:
        mtime = d.stat().st_mtime
    except OSError:
        return []
    cached = _conf_dir_cache.get(subdir)
    if cached and cached[0] == mtime:
        return cached[1]
    result = sorted(p.stem for p in d.glob("*.conf") if p.is_file())
    _conf_dir_cache[subdir] = (mtime, result)
    return result


def has_targets() -> bool:
    return len(list_conf_dir("targets.d")) > 0


def has_remotes() -> bool:
    return len(list_conf_dir("remotes.d")) > 0


def get_log_retain_days() -> int:
    """Return LOG_RETAIN from gniza.conf as an int (default 90)."""
    data = parse_conf(CONFIG_DIR / "gniza.conf")
    try:
        return int(data.get("LOG_RETAIN", "90"))
    except (ValueError, TypeError):
        return 90


def get_max_concurrent_jobs() -> int:
    """Return MAX_CONCURRENT_JOBS from gniza.conf as an int (default 1, 0=unlimited)."""
    data = parse_conf(CONFIG_DIR / "gniza.conf")
    try:
        return max(0, int(data.get("MAX_CONCURRENT_JOBS", "1")))
    except (ValueError, TypeError):
        return 1


def get_daemon_interval() -> int:
    """Return DAEMON_INTERVAL from gniza.conf as an int (default 10)."""
    data = parse_conf(CONFIG_DIR / "gniza.conf")
    try:
        return max(1, int(data.get("DAEMON_INTERVAL", "10")))
    except (ValueError, TypeError):
        return 10
