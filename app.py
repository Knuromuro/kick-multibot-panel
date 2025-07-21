import os
import json
import subprocess
from flask import Flask, request, jsonify, redirect, url_for, session, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit
from flask_caching import Cache
from prometheus_client import Counter, generate_latest

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///db.sqlite3')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['CACHE_TYPE'] = 'RedisCache'
app.config['CACHE_REDIS_URL'] = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

cache = Cache(app)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
socketio = SocketIO(app)

bot_runs = Counter('bot_runs', 'Number of bot runs')
bot_errors = Counter('bot_errors', 'Number of bot errors')

BOTS = {}

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)

class Bot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.form
        user = User.query.filter_by(username=data.get('username')).first()
        if user and user.password == data.get('password'):
            login_user(user)
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    groups = cache.get('groups')
    bots = cache.get('bots')
    if groups is None:
        groups = Group.query.all()
        cache.set('groups', groups)
    if bots is None:
        bots = Bot.query.all()
        cache.set('bots', bots)
    return render_template('dashboard.html', groups=groups, bots=bots)

@app.route('/dashboard/api/groups', methods=['POST'])
@login_required
def create_group():
    data = request.get_json() or {}
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name required'}), 400
    g = Group(name=name)
    db.session.add(g)
    db.session.commit()
    cache.delete('groups')
    return jsonify({'id': g.id, 'name': g.name}), 201

@app.route('/dashboard/api/bots', methods=['POST'])
@login_required
def create_bot():
    data = request.get_json() or {}
    name = data.get('name')
    group_id = data.get('group_id')
    if not name or not group_id:
        return jsonify({'error': 'name and group_id required'}), 400
    b = Bot(name=name, group_id=group_id)
    db.session.add(b)
    db.session.commit()
    cache.delete('bots')
    return jsonify({'id': b.id, 'name': b.name, 'group_id': b.group_id}), 201

@app.route('/dashboard/api/bots/<int:bot_id>/start', methods=['POST'])
@login_required
def start_bot(bot_id):
    try:
        proc = subprocess.Popen(['sleep', '2'])
        BOTS[bot_id] = proc
        bot_runs.inc()
        socketio.emit('bot_started', {'id': bot_id, 'pid': proc.pid})
        return jsonify({'status': 'started', 'pid': proc.pid})
    except Exception as e:
        bot_errors.inc()
        socketio.emit('bot_error', {'id': bot_id, 'error': str(e)})
        return jsonify({'error': str(e)}), 500

@app.route('/dashboard/api/bots/<int:bot_id>/stop', methods=['POST'])
@login_required
def stop_bot(bot_id):
    proc = BOTS.get(bot_id)
    if proc and proc.poll() is None:
        proc.terminate()
        socketio.emit('bot_stopped', {'id': bot_id})
        return jsonify({'status': 'stopped'})
    return jsonify({'error': 'not running'}), 400

@app.route('/dashboard/api/bots/<int:bot_id>/status')
@login_required
def status_bot(bot_id):
    proc = BOTS.get(bot_id)
    if proc is None:
        return jsonify({'status': 'not running'})
    running = proc.poll() is None
    return jsonify({'status': 'running' if running else 'stopped', 'pid': proc.pid})

@app.route('/metrics')
def metrics():
    return generate_latest(), 200, {'Content-Type': 'text/plain; charset=utf-8'}

if __name__ == '__main__':
    db.create_all()
    if not User.query.first():
        u = User(username='admin', password='admin')
        db.session.add(u)
        db.session.commit()
    socketio.run(app, host='0.0.0.0', port=5000)
