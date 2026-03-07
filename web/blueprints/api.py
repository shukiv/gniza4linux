import os

from flask import Blueprint, request, render_template

from web.app import login_required

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/browse")
@login_required
def browse():
    path = request.args.get("path", "/")
    target = request.args.get("target", "")

    # Must be absolute
    if not os.path.isabs(path):
        return render_template("components/folder_browser_list.html",
                               error="Path must be absolute.",
                               current_path="/", target=target, dirs=[])

    # Normalize to prevent traversal
    path = os.path.realpath(path)

    if not os.path.isdir(path):
        return render_template("components/folder_browser_list.html",
                               error="Directory does not exist.",
                               current_path="/", target=target, dirs=[])

    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return render_template("components/folder_browser_list.html",
                               error="Permission denied.",
                               current_path=path, target=target, dirs=[])

    dirs = []
    for entry in entries:
        if entry.startswith("."):
            continue
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            dirs.append(entry)

    parent = os.path.dirname(path) if path != "/" else None

    return render_template("components/folder_browser_list.html",
                           current_path=path, parent=parent,
                           target=target, dirs=dirs, error=None)
