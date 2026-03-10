from flask import Blueprint, render_template
from web.app import login_required

bp = Blueprint("guide", __name__, url_prefix="/guide")


@bp.route("/")
@login_required
def index():
    return render_template("guide/index.html", active_page="guide")
