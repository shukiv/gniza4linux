import os

from flask import Blueprint, request, render_template

from web.app import login_required

bp = Blueprint("api", __name__, url_prefix="/api")

_FOLDER_SVG = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" /></svg>'


def _list_dirs(path):
    """List subdirectories of path, skipping hidden dirs."""
    path = os.path.realpath(path)
    if not os.path.isabs(path) or not os.path.isdir(path):
        return []
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return []
    dirs = []
    for entry in entries:
        if entry.startswith("."):
            continue
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            dirs.append(entry)
    return dirs


@bp.route("/browse")
@login_required
def browse():
    """Return the full folder browser tree starting at a path."""
    path = request.args.get("path", "/")
    target = request.args.get("target", "")

    if not os.path.isabs(path):
        path = "/"
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        path = "/"

    dirs = _list_dirs(path)
    return render_template("components/folder_browser.html",
                           current_path=path, target=target, dirs=dirs)


@bp.route("/browse/children")
@login_required
def browse_children():
    """Return child folder list items for lazy loading inside a <details>."""
    path = request.args.get("path", "/")
    target = request.args.get("target", "")

    if not os.path.isabs(path):
        return ""
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        return ""

    dirs = _list_dirs(path)
    return render_template("components/folder_browser_children.html",
                           parent_path=path, target=target, dirs=dirs)
