from flask import Blueprint, render_template, redirect, url_for, session
from authlib.integrations.flask_client import OAuth

bp = Blueprint("panel", __name__)
oauth = OAuth()


@bp.route("/")
def index():
    return redirect(url_for("panel.login"))


@bp.route("/login")
def login():
    return render_template("login.html")


@bp.route("/login/<provider>")
def oauth_login(provider):
    client = oauth.create_client(provider)
    redirect_uri = url_for("panel.oauth_callback", provider=provider, _external=True)
    return client.authorize_redirect(redirect_uri)


@bp.route("/auth/<provider>")
def oauth_callback(provider):
    client = oauth.create_client(provider)
    token = client.authorize_access_token()
    user_info = token.get("userinfo") or {}
    session["user"] = user_info.get("email", "oauth")
    session["role"] = "viewer"
    return redirect(url_for("panel.dashboard"))


@bp.route("/logout")
def logout():
    session.pop("user", None)
    session.pop("role", None)
    return redirect(url_for("panel.login"))


@bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


def register_web(app):
    """Register blueprint with the given Flask app."""
    oauth.init_app(app)
    app.register_blueprint(bp)
    # provide an alias so url_for('dashboard') works
    app.add_url_rule("/dashboard", "dashboard", dashboard)
