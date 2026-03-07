import secrets

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, current_app,
)

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        token = request.form.get("token", "")
        stored_key = current_app.config["API_KEY"]
        if token and secrets.compare_digest(token, stored_key):
            session.clear()
            session["logged_in"] = True
            return redirect(url_for("dashboard.index"))
        flash("Invalid API key.", "error")
    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
