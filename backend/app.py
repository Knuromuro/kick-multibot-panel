"""KickBot Manager backend"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from threading import Thread
import subprocess
import psutil
import redis
from rq import Queue, Retry
from prometheus_client import Counter, Gauge, generate_latest
from flask import Response
from flask_socketio import SocketIO
from shared.cache import cache, init_cache

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
import websockets

from app.routes import register_web
from bots.instance import BotInstance
from shared.logger import logger

BASE_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    static_folder=str(BASE_DIR.parent / "app" / "static"),
    template_folder=str(BASE_DIR.parent / "app" / "templates"),
)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")
DB_PATH = os.getenv("DB_PATH", "bots.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
init_cache(app)
socketio = SocketIO(app, cors_allowed_origins="*")

redis_conn = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
queue = Queue("bots", connection=redis_conn)

runs_counter = Counter("bot_runs", "Number of bot executions")
errors_counter = Counter("bot_errors", "Number of bot errors")
running_gauge = Gauge("bots_running", "Currently running bot processes")

# Database

db = SQLAlchemy(app)

class Group(db.Model):
    __tablename__ = 'groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    target = db.Column(db.String(80), nullable=False)
    interval = db.Column(db.Integer, default=600)

class Account(db.Model):
    __tablename__ = 'accounts'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), nullable=False)
    password = db.Column(db.String(120), nullable=False)
    proxy = db.Column(db.String(200))
    messages_file = db.Column(db.String(200))
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"))

class Log(db.Model):
    __tablename__ = 'logs'
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    message = db.Column(db.String(200))

bots: dict[int, BotInstance] = {}
processes: dict[int, subprocess.Popen] = {}

WORKERS = int(os.getenv("WORKERS", "50"))
MAX_INSTANCES = int(os.getenv("MAX_INSTANCES", "50"))

sched = BackgroundScheduler(
    executors={"default": ThreadPoolExecutor(max_workers=WORKERS)},
    job_defaults={"max_instances": MAX_INSTANCES},
)


@app.route('/dashboard/api/groups', methods=['POST', 'GET'])
def api_groups():
    if request.method == 'POST':
        data = request.json
        g = Group(name=data['name'], target=data['target'], interval=data['interval'])
        db.session.add(g)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'group name must be unique'}), 400
        return jsonify({'id': g.id})
    @cache.cached(timeout=60)
    def _get_groups():
        return [{ 'id': g.id, 'name': g.name, 'target': g.target, 'interval': g.interval } for g in Group.query.all()]
    return jsonify(_get_groups())


@app.route('/dashboard/api/accounts', methods=['POST', 'GET'])
def api_accounts():
    if request.method == 'POST':
        data = request.json
        acc = Account(
            username=data['username'],
            password=data['password'],
            proxy=data.get('proxy'),
            messages_file=data.get('messages_file'),
            group_id=data['group_id'],
        )
        db.session.add(acc)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'could not create account'}), 400
        return jsonify({'id': acc.id})
    @cache.cached(timeout=60)
    def _get_accounts():
        return [{ 'id': a.id, 'username': a.username, 'group_id': a.group_id } for a in Account.query.all()]
    return jsonify(_get_accounts())


async def send_job(account_id: int):
    account = Account.query.get(account_id)
    if not account:
        return
    group = Group.query.get(account.group_id)
    if not group:
        return
    if account_id not in bots:
        bots[account_id] = BotInstance(account, group)
        bots[account_id].login()
    bot = bots[account_id]
    msg_path = Path(account.messages_file or "").expanduser()
    message = "Hello from KickBot"
    if msg_path.is_file():
        with open(msg_path) as fh:
            line = fh.readline().strip()
            if line:
                message = line
    await bot.send_message(message)
    with app.app_context():
        log = Log(account_id=account_id, message=message)
        db.session.add(log)
        db.session.commit()
    socketio.emit('status', {'message': f'sent message for {account_id}'})


def run_bot_task(bot_id: int):
    """Run bot via subprocess for job queue"""
    account = Account.query.get(bot_id)
    if not account:
        return
    group = Group.query.get(account.group_id)
    if not group:
        return
    msg = "Hello from KickBot"
    msg_path = Path(account.messages_file or "").expanduser()
    if msg_path.is_file():
        with open(msg_path) as fh:
            line = fh.readline().strip()
            if line:
                msg = line
    cmd = [
        'python', str(Path(__file__).resolve().parent.parent / 'scripts' / 'run_bot.py'),
        '--channel', group.target,
        '--message', msg,
        '--interval', str(group.interval),
        '--token', account.password  # placeholder
    ]
    runs_counter.inc()
    try:
        subprocess.run(cmd, check=True)
    except Exception:
        errors_counter.inc()


def start_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


aio_loop = asyncio.new_event_loop()
thread = Thread(target=start_async_loop, args=(aio_loop,))
thread.daemon = True
thread.start()


def schedule_all():
    """Schedule message sending for all accounts."""
    sched.remove_all_jobs()
    for acc in Account.query.all():
        group = Group.query.get(acc.group_id)
        if group:
            sched.add_job(
                lambda aid=acc.id: asyncio.run_coroutine_threadsafe(
                    send_job(aid), aio_loop
                ),
                "interval",
                seconds=group.interval,
                id=str(acc.id),
                replace_existing=True,
            )


@app.route("/dashboard/api/scheduler/start", methods=["POST"])
def api_start_sched():
    if not sched.running:
        sched.start()
    schedule_all()
    socketio.emit('status', {'message': 'scheduler started'})
    return jsonify({"status": "started"})


@app.route("/dashboard/api/bots", methods=["GET"])
def api_list_bots():
    data = []
    for acc in Account.query.all():
        status = "offline"
        bot = bots.get(acc.id)
        if bot and bot.ws and not bot.ws.closed:
            status = "online"
        data.append({"id": acc.id, "username": acc.username, "status": status})
    return jsonify(data)


@app.route("/bots/<int:bot_id>/start", methods=["POST"])
def start_bot(bot_id):
    if bot_id in processes:
        return jsonify({"status": "already running"})
    account = Account.query.get(bot_id)
    if not account:
        return jsonify({"error": "bot not found"}), 404
    group = Group.query.get(account.group_id)
    if not group:
        return jsonify({"error": "group not found"}), 404
    msg = "Hello from KickBot"
    mp = Path(account.messages_file or "")
    if mp.is_file():
        msg = mp.read_text().splitlines()[0]
    cmd = [
        "python",
        str(Path(__file__).resolve().parent.parent / "scripts" / "run_bot.py"),
        "--channel",
        group.target,
        "--message",
        msg,
        "--interval",
        str(group.interval),
        "--token",
        account.password,
    ]
    proc = subprocess.Popen(cmd)
    processes[bot_id] = proc
    running_gauge.inc()
    socketio.emit("status", {"message": f"bot {bot_id} started"})
    return jsonify({"pid": proc.pid})


@app.route("/bots/<int:bot_id>/stop", methods=["POST"])
def stop_bot(bot_id):
    proc = processes.get(bot_id)
    if not proc:
        return jsonify({"status": "not running"})
    ps = psutil.Process(proc.pid)
    ps.terminate()
    proc.wait(timeout=5)
    running_gauge.dec()
    socketio.emit("status", {"message": f"bot {bot_id} stopped"})
    processes.pop(bot_id, None)
    return jsonify({"status": "stopped"})


@app.route("/bots/<int:bot_id>/status", methods=["GET"])
def bot_status(bot_id):
    proc = processes.get(bot_id)
    if not proc:
        return jsonify({"running": False})
    ps = psutil.Process(proc.pid)
    info = {
        "running": ps.is_running(),
        "pid": proc.pid,
        "cpu": ps.cpu_percent(interval=0.1),
        "memory": ps.memory_info().rss,
    }
    return jsonify(info)


@app.route("/bots/<int:bot_id>/schedule", methods=["POST"])
def schedule_bot(bot_id):
    job = queue.enqueue(run_bot_task, bot_id, retry=Retry(max=3))
    return jsonify({"job_id": job.id})


@app.route("/dashboard/api/bots/<int:bid>/command", methods=["POST"])
def api_bot_cmd(bid):
    cmd = request.json.get("cmd")
    args = request.json.get("args", {})
    bot = bots.get(bid)
    if not bot:
        return jsonify({"error": "bot not running"}), 404
    async def run():
        if cmd == "send_message":
            await bot.send_message(args.get("message", ""))
        elif cmd == "status_check":
            return await bot.status_check()
        elif cmd == "restart":
            await bot.restart()
        elif cmd == "screenshot":
            bot.screenshot()
    fut = asyncio.run_coroutine_threadsafe(run(), aio_loop)
    fut.result()
    return jsonify({"status": "ok"})


@app.route("/dashboard/api/bots/<int:bid>/logs", methods=["GET"])
def api_bot_logs(bid):
    path = Path("logs") / f"bot_{bid}.log"
    if not path.exists():
        return jsonify([])
    lines = path.read_text().splitlines()[-50:]
    return jsonify(lines)


@app.route('/metrics')
def metrics():
    data = generate_latest()
    return Response(data, mimetype='text/plain')


def init_db():
    db.create_all()
    register_web(app)
    with db.engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY, name VARCHAR(80) UNIQUE, target VARCHAR(80), interval INTEGER)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY, username VARCHAR(120), password VARCHAR(120), proxy VARCHAR(200), messages_file VARCHAR(200), group_id INTEGER)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, account_id INTEGER, timestamp DATETIME, message VARCHAR(200))"))


def create_app():
    with app.app_context():
        init_db()
    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    create_app().run(host="0.0.0.0", port=port, debug=os.getenv("DEBUG", "true").lower() == "true")
