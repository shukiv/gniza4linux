"""Shared input validation for gniza."""
import re

# Entity names: targets, remotes, schedules
VALID_NAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$')


def validate_name(name: str) -> bool:
    return bool(VALID_NAME_RE.match(name))


def validate_port(port: str) -> bool:
    try:
        p = int(port)
        return 1 <= p <= 65535
    except (ValueError, TypeError):
        return False


def validate_host(host: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9._:-]+$', host)) and len(host) <= 255
