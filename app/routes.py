import os
from functools import wraps
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    session,
    request,
    flash,
    current_app,
    jsonify,
)
import bcrypt
from flask_jwt_extended import verify_jwt_in_request
from authlib.integrations.flask_client import OAuth

bp = Blueprint("panel", __name__)
oauth = OAuth()


def login_required(fn):
    """Redirect to login if the user is not authenticated."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("user_id"):
            return fn(*args, **kwargs)
        return redirect(url_for("panel.login_get"))

    return wrapper


@bp.route("/")
def index():
    """Redirect to dashboard."""
    return redirect(url_for("panel.dashboard"))


@bp.get("/login")
def login_get():
    return render_template("login.html")


@bp.post("/login")
def login_post():
    data = request.form
    user = data.get("username")
    password = data.get("password")

    valid = False
    if user in {"admin", "operator"}:
        hashed = os.getenv(f"{user.upper()}_PASSWORD_HASH")
        if hashed:
            try:
                valid = bcrypt.checkpw(password.encode(), hashed.encode())
            except Exception:
                valid = False
        else:
            env_plain = os.getenv(f"{user.upper()}_PASSWORD", user)
            valid = password == env_plain

    if valid:
        secret = os.getenv("TOTP_SECRET")
        if secret:
            import pyotp

            totp = pyotp.TOTP(secret)
            if not totp.verify(str(data.get("totp"))):
                flash("Invalid token", "error")
                return render_template("login.html"), 401
        role = "admin" if user == "admin" else "operator"
        session["user_id"] = user
        session["role"] = role
        flash("Login successful", "info")
        return redirect(url_for("panel.dashboard"))
    flash("Invalid credentials", "error")
    return render_template("login.html"), 401


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
    session["user_id"] = user_info.get("email", "oauth")
    session["role"] = "viewer"
    return redirect(url_for("panel.dashboard"))


@bp.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("role", None)
    return redirect(url_for("panel.login_get"))


@bp.before_app_request
def enforce_authentication():
    if current_app.config.get("LOGIN_DISABLED"):
        return
    if request.path.startswith("/static"):
        return
    if request.endpoint in (
        "panel.login_get",
        "panel.login_post",
        "panel.oauth_login",
        "panel.oauth_callback",
    ):
        return
    if request.path.startswith("/dashboard/api"):
        if session.get("user_id"):
            return
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify({"error": "unauthorized"}), 401
    elif request.path.startswith("/dashboard"):
        if not session.get("user_id"):
            return redirect(url_for("panel.login_get"))


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


def register_web(app):
    """Register blueprint with the given Flask app."""
    oauth.init_app(app)
    app.register_blueprint(bp)
    # provide an alias so url_for('dashboard') works
    app.add_url_rule("/dashboard", "dashboard", dashboard)
