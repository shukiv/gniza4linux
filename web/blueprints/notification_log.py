from pathlib import Path

from flask import Blueprint, render_template, request

from tui.config import LOG_DIR
from web.app import login_required
from web.helpers import paginate

bp = Blueprint("notification_log", __name__, url_prefix="/notification-log")

ENTRIES_PER_PAGE = 50


def _parse_notification_log():
    """Parse notification log. Handles both old 4-col and new 5-col format."""
    entries = []

    # Read new notification.log
    for log_name in ("notification.log", "email.log"):
        log_file = Path(LOG_DIR) / log_name
        if not log_file.is_file():
            continue
        try:
            with open(log_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(" | ")
                    if len(parts) == 5:
                        # New format: timestamp | channel | status | dest | subject
                        entries.append({
                            "date": parts[0],
                            "channel": parts[1],
                            "status": parts[2],
                            "recipients": parts[3],
                            "subject": parts[4],
                        })
                    elif len(parts) == 4:
                        # Old format: timestamp | status | recipients | subject
                        entries.append({
                            "date": parts[0],
                            "channel": "email",
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

    entries = _parse_notification_log()
    total = len(entries)
    page_entries, page, total_pages = paginate(entries, page, ENTRIES_PER_PAGE)

    return render_template(
        "notification_log/index.html",
        entries=page_entries,
        page=page,
        total_pages=total_pages,
        total=total,
    )
