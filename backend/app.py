"""Backend for KickBot Manager."""

from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Dict, Optional
from functools import wraps

import psutil
import redis
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Blueprint, Flask, Response, request, current_app, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_restx import Api, Resource
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    create_refresh_token,
    get_jwt,
    jwt_required,
    verify_jwt_in_request,
)
from datetime import timedelta
from prometheus_client import Counter, Gauge, generate_latest
from rq import Queue, Retry

from app.routes import register_web
from dotenv import load_dotenv
from bots.instance import BotInstance
from shared.cache import cache, init_cache
from shared.logger import logger

ANALYTICS_LOG = Path("analytics.log")

# Global extensions ---------------------------------------------------------

db = SQLAlchemy()
socketio = SocketIO(cors_allowed_origins="*")
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
talisman = Talisman()
api = Api(doc="/docs")
jwt = JWTManager()

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
    name = db.Column(db.String(80), unique=True, nullable=False, index=True)
    target = db.Column(db.String(80), nullable=False, index=True)
    interval = db.Column(db.Integer, default=600)


class Account(db.Model):
    __tablename__ = "accounts"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), nullable=False, index=True)
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
    load_dotenv()
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
            "JWT_SECRET_KEY": os.getenv("JWT_SECRET_KEY", "jwt-secret"),
            "JWT_ACCESS_TOKEN_EXPIRES": timedelta(minutes=15),
            "JWT_REFRESH_TOKEN_EXPIRES": timedelta(days=1),
            "TOTP_SECRET": os.getenv("TOTP_SECRET"),
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
    csp = {
        "default-src": ["'self'"],
        "script-src": ["'self'", "https://cdn.jsdelivr.net"],
        "style-src": ["'self'", "https://cdn.jsdelivr.net"],
    }
    talisman.init_app(
        app,
        force_https=not app.config.get("TESTING", False),
        content_security_policy=csp,
    )
    jwt.init_app(app)
    db.init_app(app)
    socketio.init_app(app)

    @app.before_request
    def log_request() -> None:
        ua = request.headers.get("User-Agent", "")
        entry = f"{datetime.utcnow().isoformat()} {request.path} {ua}\n"
        try:
            with ANALYTICS_LOG.open("a") as fh:
                fh.write(entry)
        except Exception:
            pass

    register_web(app)
    register_api(app)

    with app.app_context():
        db.create_all()

    return app


# API blueprint ------------------------------------------------------------

api_bp = Blueprint("api", __name__)
auth_bp = Blueprint("auth", __name__)
ns = api.namespace("api", path="/dashboard/api")


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if current_app.config.get("TESTING"):
                return fn(*args, **kwargs)
            if session.get("role") and session["role"] in roles:
                return fn(*args, **kwargs)
            verify_jwt_in_request()
            claims = get_jwt()
            if claims.get("sub", {}).get("role") not in roles:
                return {"msg": "forbidden"}, 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


@auth_bp.route("/auth/token", methods=["POST"])
@limiter.limit("5/minute")
def get_token():
    data = request.get_json() or {}
    user = data.get("username")
    password = data.get("password")
    totp_code = data.get("totp")
    role = None
    if user == "admin" and password == os.getenv("ADMIN_PASSWORD", "admin"):
        role = "admin"
    elif user == "operator" and password == os.getenv("OPERATOR_PASSWORD", "operator"):
        role = "operator"
    else:
        logger.warning("invalid credentials for %s", user)
        return {"msg": "bad credentials"}, 401
    secret = os.getenv("TOTP_SECRET")
    if secret:
        import pyotp

        totp = pyotp.TOTP(secret)
        if not totp.verify(str(totp_code)):
            logger.warning("invalid totp for %s", user)
            return {"msg": "invalid token"}, 401
    access = create_access_token(identity={"user": user, "role": role})
    refresh = create_refresh_token(identity={"user": user, "role": role})
    return {"access_token": access, "refresh_token": refresh}


@auth_bp.route("/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh_token():
    identity = get_jwt()["sub"]
    access = create_access_token(identity=identity)
    return {"access_token": access}


@ns.route("/groups", methods=["GET", "POST"], endpoint="groups")
class GroupResource(Resource):
    @jwt_required(optional=True)
    def get(self):
        search = request.args.get("search", "").strip()
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        if not search and page == 1 and per_page == 50:
            groups = cache.get("groups")
            if groups is not None:
                return groups
        query = Group.query
        if search:
            query = query.filter(Group.name.ilike(f"%{search}%"))
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        groups = [
            {"id": g.id, "name": g.name, "target": g.target, "interval": g.interval}
            for g in pagination.items
        ]
        if not search and page == 1 and per_page == 50:
            cache.set("groups", groups, timeout=60)
        return {"items": groups, "total": pagination.total}

    @limiter.limit("10/minute")
    @role_required("operator", "admin")
    def post(self):
        data = request.get_json(silent=True) or {}
        name = data.get("name")
        target = data.get("target")
        interval = data.get("interval", 600)
        if not name or not target:
            return {"error": "missing name or target"}, 400
        group = Group(name=name, target=target, interval=interval)
        try:
            with db.session.begin():
                db.session.add(group)
        except Exception as exc:  # noqa: broad-except
            logger.warning("group creation failed: %s", exc)
            return {"error": "group name must be unique"}, 400
        return {"id": group.id}, 201


@ns.route("/accounts", methods=["GET", "POST"], endpoint="accounts")
class AccountResource(Resource):
    @jwt_required(optional=True)
    def get(self):
        search = request.args.get("search", "").strip()
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        if not search and page == 1 and per_page == 50:
            accounts = cache.get("accounts")
            if accounts is not None:
                return accounts
        query = Account.query
        if search:
            query = query.filter(Account.username.ilike(f"%{search}%"))
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        accounts = [
            {"id": a.id, "username": a.username, "group_id": a.group_id}
            for a in pagination.items
        ]
        if not search and page == 1 and per_page == 50:
            cache.set("accounts", accounts, timeout=60)
        return {"items": accounts, "total": pagination.total}

    @limiter.limit("10/minute")
    @role_required("operator", "admin")
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
        try:
            with db.session.begin():
                db.session.add(account)
        except Exception as exc:  # noqa: broad-except
            logger.warning("account creation failed: %s", exc)
            return {"error": "could not create account"}, 400
        return {"id": account.id}, 201


@ns.route("/scheduler/start", methods=["POST"], endpoint="scheduler_start")
class SchedulerStart(Resource):
    @limiter.limit("5/minute")
    @role_required("operator", "admin")
    def post(self):
        if not sched.running:
            sched.start()
        schedule_all()
        socketio.emit("status", {"message": "scheduler started"})
        return {"status": "started"}


@ns.route("/bots", methods=["GET"], endpoint="bot_list")
class BotList(Resource):
    @jwt_required(optional=True)
    def get(self):
        search = request.args.get("search", "").strip()
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        query = Account.query
        if search:
            query = query.filter(Account.username.ilike(f"%{search}%"))
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        result = []
        for acc in pagination.items:
            status = "offline"
            bot = bots.get(acc.id)
            if bot and bot.ws and not bot.ws.closed:
                status = "online"
            result.append({"id": acc.id, "username": acc.username, "status": status})
        return {"items": result, "total": pagination.total}


# Bot process management ---------------------------------------------------


@ns.route("/bots/<int:bot_id>/start", methods=["POST"], endpoint="bot_start")
class BotStart(Resource):
    @limiter.limit("10/minute")
    @role_required("operator", "admin")
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
        socketio.emit("bot_started", {"id": bot_id})
        socketio.emit("status", {"message": f"bot {bot_id} started"})
        return {"pid": proc.pid}


@ns.route("/bots/<int:bot_id>/stop", methods=["POST"], endpoint="bot_stop")
class BotStop(Resource):
    @limiter.limit("10/minute")
    @role_required("operator", "admin")
    def post(self, bot_id: int):
        proc = processes.get(bot_id)
        if not proc:
            return {"status": "not running"}
        ps_process = psutil.Process(proc.pid)
        ps_process.terminate()
        proc.wait(timeout=5)
        running_gauge.dec()
        socketio.emit("bot_finished", {"id": bot_id})
        socketio.emit("status", {"message": f"bot {bot_id} stopped"})
        processes.pop(bot_id, None)
        return {"status": "stopped"}


@ns.route("/bots/<int:bot_id>/status", methods=["GET"], endpoint="bot_status")
class BotStatus(Resource):
    @jwt_required(optional=True)
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
    @limiter.limit("5/minute")
    @role_required("operator", "admin")
    def post(self, bot_id: int):
        job = queue.enqueue(run_bot_task, bot_id, retry=Retry(max=3))
        return {"job_id": job.id}


@ns.route("/bots/<int:bid>/command", methods=["POST"], endpoint="bot_command")
class BotCommand(Resource):
    @limiter.limit("10/minute")
    @role_required("operator", "admin")
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
    @jwt_required(optional=True)
    def get(self, bid: int):
        path = Path("logs") / f"bot_{bid}.log"
        if not path.exists():
            return []
        lines = path.read_text().splitlines()[-50:]
        return lines


@api_bp.route("/metrics")
@jwt_required(optional=True)
def metrics():
    data = generate_latest()
    return Response(data, mimetype="text/plain")


@api_bp.route("/dashboard/api/stats")
@jwt_required(optional=True)
def stats():
    """Return simple counter stats for charts."""
    return {
        "runs": runs_counter._value.get(),
        "errors": errors_counter._value.get(),
    }


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
        socketio.emit("bot_finished", {"id": bot_id})
    except Exception as exc:  # noqa: broad-except
        errors_counter.inc()
        logger.error("bot run failed: %s", exc)
        socketio.emit("bot_error", {"id": bot_id})


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
    socketio.emit("bot_started", {"id": account_id})
    try:
        await bot.send_message(message)
        socketio.emit("bot_finished", {"id": account_id})
    except Exception as exc:  # noqa: broad-except
        errors_counter.inc()
        logger.error("send job failed: %s", exc)
        socketio.emit("bot_error", {"id": account_id})
    with current_app.app_context():
        log = Log(account_id=account_id, message=message)
        db.session.add(log)
        db.session.commit()
    socketio.emit("status", {"message": f"sent message for {account_id}"})


def register_api(app: Flask) -> None:
    api.init_app(app)
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
