"""KickBot Manager backend"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from threading import Thread

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
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
        db.session.commit()
        return jsonify({'id': g.id})
    return jsonify([{ 'id': g.id, 'name': g.name, 'target': g.target, 'interval': g.interval } for g in Group.query.all()])


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
        db.session.commit()
        return jsonify({'id': acc.id})
    return jsonify([{ 'id': a.id, 'username': a.username, 'group_id': a.group_id } for a in Account.query.all()])


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
