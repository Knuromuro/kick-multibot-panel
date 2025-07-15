"""Backend for KickBot Manager."""

from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Dict, Optional

import psutil
import redis
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Blueprint, Flask, Response, request, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_restx import Api, Resource
from prometheus_client import Counter, Gauge, generate_latest
from rq import Queue, Retry

from app.routes import register_web
from bots.instance import BotInstance
from shared.cache import cache, init_cache
from shared.logger import logger

# Global extensions ---------------------------------------------------------

db = SQLAlchemy()
socketio = SocketIO(cors_allowed_origins="*")
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
talisman = Talisman()
api = Api(doc="/docs")

# Prometheus metrics
runs_counter = Counter("bot_runs", "Number of bot executions")
errors_counter = Counter("bot_errors", "Number of bot errors")
running_gauge = Gauge("bots_running", "Currently running bot processes")

# Scheduler
WORKERS = int(os.getenv("WORKERS", "50"))
MAX_INSTANCES = int(os.getenv("MAX_INSTANCES", "50"))
sched = BackgroundScheduler(
    executors={"default": ThreadPoolExecutor(max_workers=WORKERS)},
    job_defaults={"max_instances": MAX_INSTANCES},
)

aio_loop = asyncio.new_event_loop()
_thread = Thread(target=lambda: aio_loop.run_forever(), daemon=True)
_thread.start()

# Redis queue
redis_conn = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
queue = Queue("bots", connection=redis_conn)

# Database models ----------------------------------------------------------

class Group(db.Model):
    __tablename__ = "groups"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    target = db.Column(db.String(80), nullable=False)
    interval = db.Column(db.Integer, default=600)


class Account(db.Model):
    __tablename__ = "accounts"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), nullable=False)
    password = db.Column(db.String(120), nullable=False)
    proxy = db.Column(db.String(200))
    messages_file = db.Column(db.String(200))
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"))


class Log(db.Model):
    __tablename__ = "logs"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    message = db.Column(db.String(200))


# Bot and process storage --------------------------------------------------

bots: Dict[int, BotInstance] = {}
processes: Dict[int, subprocess.Popen] = {}


# Application factory ------------------------------------------------------

def create_app(config: Optional[dict] = None) -> Flask:
    """Create and configure the Flask application."""

    base_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        static_folder=str(base_dir.parent / "app" / "static"),
        template_folder=str(base_dir.parent / "app" / "templates"),
    )
    db_uri = os.getenv("DATABASE_URL")
    if not db_uri:
        db_uri = f"sqlite:///{os.getenv('DB_PATH', 'bots.db')}"
    app.config.update(
        {
            "SECRET_KEY": os.getenv("SECRET_KEY", "change-me"),
            "SQLALCHEMY_DATABASE_URI": db_uri,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        }
    )
    if config:
        app.config.update(config)

    testing = app.config.get("TESTING") or os.getenv("TESTING")
    if testing:
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

    init_cache(app)
    csrf.init_app(app)
    csrf.exempt(api_bp)
    limiter.init_app(app)
    talisman.init_app(app, force_https=not app.config.get("TESTING", False))
    db.init_app(app)
    socketio.init_app(app)

    register_web(app)
    register_api(app)

    with app.app_context():
        db.create_all()

    return app


# API blueprint ------------------------------------------------------------

api_bp = Blueprint("api", __name__)
ns = api.namespace("api", path="/dashboard/api")


@ns.route("/groups", methods=["GET", "POST"], endpoint="groups")
class GroupResource(Resource):
    def get(self):
        groups = cache.get("groups")
        if groups is None:
            groups = [
                {"id": g.id, "name": g.name, "target": g.target, "interval": g.interval}
                for g in Group.query.all()
            ]
            cache.set("groups", groups, timeout=60)
        return groups

    def post(self):
        data = request.get_json(silent=True) or {}
        name = data.get("name")
        target = data.get("target")
        interval = data.get("interval", 600)
        if not name or not target:
            return {"error": "missing name or target"}, 400
        group = Group(name=name, target=target, interval=interval)
        db.session.add(group)
        try:
            db.session.commit()
        except Exception as exc:  # noqa: broad-except
            logger.warning("group creation failed: %s", exc)
            db.session.rollback()
            return {"error": "group name must be unique"}, 400
        return {"id": group.id}, 201


@ns.route("/accounts", methods=["GET", "POST"], endpoint="accounts")
class AccountResource(Resource):
    def get(self):
        accounts = cache.get("accounts")
        if accounts is None:
            accounts = [
                {"id": a.id, "username": a.username, "group_id": a.group_id}
                for a in Account.query.all()
            ]
            cache.set("accounts", accounts, timeout=60)
        return accounts

    def post(self):
        data = request.get_json(silent=True) or {}
        username = data.get("username")
        password = data.get("password")
        group_id = data.get("group_id")
        if not username or not password or not group_id:
            return {"error": "missing fields"}, 400
        account = Account(
            username=username,
            password=password,
            proxy=data.get("proxy"),
            messages_file=data.get("messages_file"),
            group_id=group_id,
        )
        db.session.add(account)
        try:
            db.session.commit()
        except Exception as exc:  # noqa: broad-except
            logger.warning("account creation failed: %s", exc)
            db.session.rollback()
            return {"error": "could not create account"}, 400
        return {"id": account.id}, 201


@ns.route("/scheduler/start", methods=["POST"], endpoint="scheduler_start")
class SchedulerStart(Resource):
    def post(self):
        if not sched.running:
            sched.start()
        schedule_all()
        socketio.emit("status", {"message": "scheduler started"})
        return {"status": "started"}


@ns.route("/bots", methods=["GET"], endpoint="bot_list")
class BotList(Resource):
    def get(self):
        result = []
        for acc in Account.query.all():
            status = "offline"
            bot = bots.get(acc.id)
            if bot and bot.ws and not bot.ws.closed:
                status = "online"
            result.append({"id": acc.id, "username": acc.username, "status": status})
        return result


# Bot process management ---------------------------------------------------

@ns.route("/bots/<int:bot_id>/start", methods=["POST"], endpoint="bot_start")
class BotStart(Resource):
    def post(self, bot_id: int):
        if bot_id in processes:
            return {"status": "already running"}

        account = Account.query.get(bot_id)
        if not account:
            return {"error": "bot not found"}, 404
        group = Group.query.get(account.group_id)
        if not group:
            return {"error": "group not found"}, 404

        msg = "Hello from KickBot"
        msg_path = Path(account.messages_file or "")
        if msg_path.is_file():
            msg = msg_path.read_text().splitlines()[0]

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
        return {"pid": proc.pid}


@ns.route("/bots/<int:bot_id>/stop", methods=["POST"], endpoint="bot_stop")
class BotStop(Resource):
    def post(self, bot_id: int):
        proc = processes.get(bot_id)
        if not proc:
            return {"status": "not running"}
        ps_process = psutil.Process(proc.pid)
        ps_process.terminate()
        proc.wait(timeout=5)
        running_gauge.dec()
        socketio.emit("status", {"message": f"bot {bot_id} stopped"})
        processes.pop(bot_id, None)
        return {"status": "stopped"}


@ns.route("/bots/<int:bot_id>/status", methods=["GET"], endpoint="bot_status")
class BotStatus(Resource):
    def get(self, bot_id: int):
        proc = processes.get(bot_id)
        if not proc:
            return {"running": False}
        ps_process = psutil.Process(proc.pid)
        info = {
            "running": ps_process.is_running(),
            "pid": proc.pid,
            "cpu": ps_process.cpu_percent(interval=0.1),
            "memory": ps_process.memory_info().rss,
        }
        return info


@ns.route("/bots/<int:bot_id>/schedule", methods=["POST"], endpoint="bot_schedule")
class BotSchedule(Resource):
    def post(self, bot_id: int):
        job = queue.enqueue(run_bot_task, bot_id, retry=Retry(max=3))
        return {"job_id": job.id}


@ns.route("/bots/<int:bid>/command", methods=["POST"], endpoint="bot_command")
class BotCommand(Resource):
    def post(self, bid: int):
        cmd = (request.json or {}).get("cmd")
        args = (request.json or {}).get("args", {})
        bot = bots.get(bid)
        if not bot:
            return {"error": "bot not running"}, 404
        async def run_command():
            if cmd == "send_message":
                await bot.send_message(args.get("message", ""))
            elif cmd == "status_check":
                return await bot.status_check()
            elif cmd == "restart":
                await bot.restart()
            elif cmd == "screenshot":
                bot.screenshot()

        fut = asyncio.run_coroutine_threadsafe(run_command(), aio_loop)
        result = fut.result()
        return result or {"status": "ok"}


@ns.route("/bots/<int:bid>/logs", methods=["GET"], endpoint="bot_logs")
class BotLogs(Resource):
    def get(self, bid: int):
        path = Path("logs") / f"bot_{bid}.log"
        if not path.exists():
            return []
        lines = path.read_text().splitlines()[-50:]
        return lines


@api_bp.route("/metrics")
def metrics():
    data = generate_latest()
    return Response(data, mimetype="text/plain")


# Utility functions --------------------------------------------------------

def run_bot_task(bot_id: int) -> None:
    """Run a bot via subprocess for the job queue."""
    account = Account.query.get(bot_id)
    if not account:
        return
    group = Group.query.get(account.group_id)
    if not group:
        return

    msg = "Hello from KickBot"
    msg_path = Path(account.messages_file or "")
    if msg_path.is_file():
        msg = msg_path.read_text().splitlines()[0]

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
    runs_counter.inc()
    try:
        subprocess.run(cmd, check=True)
    except Exception as exc:  # noqa: broad-except
        errors_counter.inc()
        logger.error("bot run failed: %s", exc)


def schedule_all() -> None:
    """Schedule message sending for all accounts."""
    sched.remove_all_jobs()
    for acc in Account.query.all():
        group = Group.query.get(acc.group_id)
        if not group:
            continue
        sched.add_job(
            lambda aid=acc.id: asyncio.run_coroutine_threadsafe(
                send_job(aid), aio_loop
            ),
            "interval",
            seconds=group.interval,
            id=str(acc.id),
            replace_existing=True,
        )


async def send_job(account_id: int) -> None:
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
    message = "Hello from KickBot"
    msg_path = Path(account.messages_file or "").expanduser()
    if msg_path.is_file():
        with open(msg_path) as fh:
            line = fh.readline().strip()
            if line:
                message = line
    await bot.send_message(message)
    with current_app.app_context():
        log = Log(account_id=account_id, message=message)
        db.session.add(log)
        db.session.commit()
    socketio.emit("status", {"message": f"sent message for {account_id}"})


def register_api(app: Flask) -> None:
    api.init_app(app)
    app.register_blueprint(api_bp)

