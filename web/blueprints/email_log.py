from pathlib import Path

from flask import Blueprint, render_template, request

from tui.config import LOG_DIR
from web.app import login_required

bp = Blueprint("email_log", __name__, url_prefix="/email-log")

ENTRIES_PER_PAGE = 50


def _parse_email_log():
    log_file = Path(LOG_DIR) / "email.log"
    if not log_file.is_file():
        return []

    entries = []
    try:
        with open(log_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(" | ", 3)
                if len(parts) == 4:
                    entries.append({
                        "date": parts[0],
                        "status": parts[1],
                        "recipients": parts[2],
                        "subject": parts[3],
                    })
    except OSError:
        pass

    entries.reverse()
    return entries


@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    entries = _parse_email_log()
    total = len(entries)
    total_pages = max(1, (total + ENTRIES_PER_PAGE - 1) // ENTRIES_PER_PAGE)
    page = min(page, total_pages)
    start = (page - 1) * ENTRIES_PER_PAGE
    end = start + ENTRIES_PER_PAGE

    return render_template(
        "email_log/index.html",
        entries=entries[start:end],
        page=page,
        total_pages=total_pages,
        total=total,
    )
