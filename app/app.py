from functools import wraps
import json
import subprocess
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, session, flash

DATA_FILE = Path(__file__).resolve().parent.parent / 'data.json'
SECRET_KEY = 'change-me'

app = Flask(__name__)
app.secret_key = SECRET_KEY

processes: dict[str, subprocess.Popen] = {}


def load_config():
    with open(DATA_FILE) as f:
        return json.load(f)


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == 'admin':
            session['user'] = 'admin'
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    cfg = load_config()
    return render_template('dashboard.html', groups=cfg['groups'])


def _start_group(name: str):
    proc = subprocess.Popen(['python', '-m', 'bots.bot_runner', '--group', name])
    processes[name] = proc


@app.route('/start_all', methods=['POST'])
@login_required
def start_all():
    cfg = load_config()
    for g in cfg['groups']:
        _start_group(g['name'])
    flash('All groups started')
    return redirect(url_for('dashboard'))


@app.route('/start_group/<name>', methods=['POST'])
@login_required
def start_group(name):
    _start_group(name)
    flash(f'Started group {name}')
    return redirect(url_for('dashboard'))


if __name__ == '__main__':
    app.run(debug=True)
