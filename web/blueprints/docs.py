from functools import lru_cache
from pathlib import Path

from flask import Blueprint, render_template
from web.app import login_required

bp = Blueprint("docs", __name__, url_prefix="/docs")

DOC_PATH = Path(__file__).resolve().parent.parent.parent / "DOCUMENTATION.md"


@lru_cache(maxsize=1)
def _render_docs():
    import re
    import markdown
    text = DOC_PATH.read_text(encoding="utf-8")
    # Strip the h1 title, description, and manual TOC section
    text = re.sub(
        r'^#\s+[^\n]+\n+.*?\n+---\n+##\s+Table of Contents\n+.*?\n+---',
        '', text, count=1, flags=re.DOTALL
    ).strip()
    md = markdown.Markdown(extensions=["toc", "fenced_code", "tables"],
                           extension_configs={"toc": {"toc_class": ""}})
    html = md.convert(text)
    toc_html = md.toc
    return html, toc_html


@bp.route("/")
@login_required
def index():
    try:
        doc_html, toc_html = _render_docs()
    except FileNotFoundError:
        doc_html = "<p>Documentation file not found.</p>"
        toc_html = ""
    return render_template("docs/index.html", doc_html=doc_html, toc_html=toc_html)
