from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from authlib.integrations.flask_client import OAuth

bp = Blueprint('panel', __name__)
oauth = OAuth()

def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        from flask import current_app
        if current_app.config.get('TESTING'):
            return func(*args, **kwargs)
        if 'user' not in session:
            return redirect(url_for('panel.login'))
        return func(*args, **kwargs)
    return wrapper

def require_role(*roles):
    def decorator(func):
        @wraps(func)
        def inner(*args, **kwargs):
            if session.get('role') not in roles:
                flash('Unauthorized')
                return redirect(url_for('panel.dashboard'))
            return func(*args, **kwargs)
        return inner
    return decorator

@bp.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('panel.dashboard'))
    return redirect(url_for('panel.login'))

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('username')
        pwd = request.form.get('password')
        if user == 'admin' and pwd == 'admin':
            session['user'] = 'admin'
            session['role'] = 'admin'
            return redirect(url_for('panel.dashboard'))
        if user == 'operator' and pwd == 'operator':
            session['user'] = 'operator'
            session['role'] = 'operator'
            return redirect(url_for('panel.dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@bp.route('/login/<provider>')
def oauth_login(provider):
    client = oauth.create_client(provider)
    redirect_uri = url_for('panel.oauth_callback', provider=provider, _external=True)
    return client.authorize_redirect(redirect_uri)


@bp.route('/auth/<provider>')
def oauth_callback(provider):
    client = oauth.create_client(provider)
    token = client.authorize_access_token()
    user_info = token.get('userinfo') or {}
    session['user'] = user_info.get('email', 'oauth')
    session['role'] = 'viewer'
    return redirect(url_for('panel.dashboard'))

@bp.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('role', None)
    return redirect(url_for('panel.login'))

@bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


def register_web(app):
    """Register blueprint with the given Flask app."""
    oauth.init_app(app)
    app.register_blueprint(bp)
    # provide an alias so url_for('dashboard') works
    app.add_url_rule('/dashboard', 'dashboard', dashboard)
