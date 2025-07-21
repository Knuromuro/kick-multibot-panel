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
from flask_jwt_extended import verify_jwt_in_request
from flask_jwt_extended import create_access_token, create_refresh_token
from authlib.integrations.flask_client import OAuth

bp = Blueprint("panel", __name__)
oauth = OAuth()


def login_required(fn):
    """Redirect to login if the user is not authenticated."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("user"):
            return fn(*args, **kwargs)
        return redirect(url_for("panel.login"))

    return wrapper


@bp.route("/")
def index():
    return redirect(url_for("panel.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        user = data.get("username")
        password = data.get("password")
        if (user == "admin" and password == os.getenv("ADMIN_PASSWORD", "admin")) or (
            user == "operator"
            and password == os.getenv("OPERATOR_PASSWORD", "operator")
        ):
            secret = os.getenv("TOTP_SECRET")
            if secret:
                import pyotp

                totp = pyotp.TOTP(secret)
                if not totp.verify(str(data.get("totp"))):
                    flash("Invalid token", "error")
                    if request.is_json:
                        return {"msg": "invalid token"}, 401
                    return render_template("login.html"), 401
            role = "admin" if user == "admin" else "operator"
            session["user"] = user
            session["role"] = role
            claims = {"role": role}
            access = create_access_token(identity=user, additional_claims=claims)
            refresh = create_refresh_token(identity=user, additional_claims=claims)
            if request.is_json:
                return {"access_token": access, "refresh_token": refresh}
            flash("Login successful", "info")
            return redirect(url_for("panel.dashboard"))
        flash("Invalid credentials", "error")
        if request.is_json:
            return {"msg": "bad credentials"}, 401
        return render_template("login.html"), 401
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


@bp.before_app_request
def enforce_authentication():
    if current_app.config.get("LOGIN_DISABLED"):
        return
    if request.path.startswith("/static"):
        return
    if request.endpoint in (
        "panel.login",
        "panel.oauth_login",
        "panel.oauth_callback",
    ):
        return
    if request.path.startswith("/dashboard/api"):
        if session.get("user"):
            return
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify({"error": "unauthorized"}), 401
    elif request.path.startswith("/dashboard"):
        if not session.get("user"):
            return redirect(url_for("panel.login"))


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
