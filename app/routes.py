from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

bp = Blueprint('panel', __name__)

def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('panel.login'))
        return func(*args, **kwargs)
    return wrapper

@bp.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('panel.dashboard'))
    return redirect(url_for('panel.login'))

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == 'admin' and request.form.get('password') == 'admin':
            session['user'] = 'admin'
            return redirect(url_for('panel.dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@bp.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('panel.login'))

@bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


def register_web(app):
    """Register blueprint with the given Flask app."""
    app.register_blueprint(bp)
    # provide an alias so url_for('dashboard') works
    app.add_url_rule('/dashboard', 'dashboard', dashboard)
