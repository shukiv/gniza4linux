import json
import re

from flask import Blueprint, render_template

from web.app import login_required
from web.backend import run_cli_sync
from web.helpers import load_remotes

bp = Blueprint("health", __name__, url_prefix="/health")

_VALID_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')


@bp.route("/")
@login_required
def index():
    try:
        remotes = load_remotes()
    except Exception:
        remotes = []
    return render_template("health/index.html", remotes=remotes)


@bp.route("/<name>/check")
@login_required
def check(name):
    """HTMX endpoint: returns health status for one destination."""
    if not _VALID_NAME_RE.match(name):
        return _error_partial("Invalid name")
    try:
        rc, stdout, stderr = run_cli_sync(
            "health", f"--destination={name}", "--json",
            timeout=120,
        )
        if rc == 0 and stdout.strip():
            data = json.loads(stdout.strip())
            return render_template("health/check_partial.html", data=data, error="")
        return _error_partial(stderr.strip() or "Health check failed")
    except json.JSONDecodeError:
        return _error_partial("Invalid response from health check")
    except Exception as e:
        return _error_partial(str(e))


def _error_partial(msg):
    return render_template("health/check_partial.html", data=None, error=msg)
