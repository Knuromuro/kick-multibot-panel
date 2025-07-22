"""Backend for KickBot Manager."""

from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime
from pathlib import Path
from threading import Thread, Timer
import json
from typing import Dict, Optional
from uuid import uuid4
from functools import wraps

import psutil
import redis
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.exc import IntegrityError
from flask import Blueprint, Flask, Response, request, current_app, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_restx import Api, Resource
from marshmallow import Schema, fields, ValidationError
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    create_refresh_token,
    get_jwt,
    jwt_required,
    verify_jwt_in_request,
)
from datetime import timedelta
from prometheus_client import Counter, Gauge, CollectorRegistry, generate_latest
from rq import Queue, Retry
from redis.exceptions import ConnectionError as RedisConnError

from app.routes import register_web
from shared.config import load_config
from bots.instance import BotInstance
from shared.cache import cache, init_cache
from shared.logger import logger, init_logging, notify_webhook

ANALYTICS_LOG = Path("analytics.log")
SYNC_FALLBACK = Path("sync_fallback.jsonl")

# Global extensions ---------------------------------------------------------

db = SQLAlchemy()
socketio = SocketIO(cors_allowed_origins="*")
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
talisman = Talisman()
api = Api(doc="/docs")
jwt = JWTManager()

# Prometheus metrics
registry = CollectorRegistry()
runs_counter = Counter(
    "bot_runs",
    "Number of bot executions",
    registry=registry,
)
errors_counter = Counter(
    "bot_errors",
    "Number of bot errors",
    registry=registry,
)
running_gauge = Gauge(
    "bots_running",
    "Currently running bot processes",
    registry=registry,
)

# Scheduler
cfg = load_config()
WORKERS = cfg.WORKERS
MAX_INSTANCES = cfg.MAX_INSTANCES
sched = BackgroundScheduler(
    executors={"default": ThreadPoolExecutor(max_workers=WORKERS)},
    job_defaults={"max_instances": MAX_INSTANCES},
)

aio_loop = asyncio.new_event_loop()
_thread = Thread(target=lambda: aio_loop.run_forever(), daemon=True)
_thread.start()

# Redis queue
redis_conn = None
queue = None
redis_online = True
APP: Optional[Flask] = None

# Database models ----------------------------------------------------------


class Group(db.Model):
    __tablename__ = "groups"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False, index=True)
    target = db.Column(db.String(80), nullable=False, index=True)
    interval = db.Column(db.Integer, default=600)
    accounts = db.relationship("Account", backref="group", lazy=True)


class Account(db.Model):
    __tablename__ = "accounts"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(120), nullable=False)
    proxy = db.Column(db.String(200))
    messages_file = db.Column(db.String(200))
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False)


class Log(db.Model):
    __tablename__ = "logs"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    message = db.Column(db.String(200))


class SyncEvent(db.Model):
    """Event used for synchronizing state between clients."""

    __tablename__ = "sync_events"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    entity = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    payload = db.Column(db.JSON)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    synced = db.Column(db.Boolean, default=False)


class GroupSchema(Schema):
    name = fields.Str(required=True)
    target = fields.Str(required=True)
    interval = fields.Int(load_default=600)


class AccountSchema(Schema):
    username = fields.Str(required=True)
    password = fields.Str(required=True)
    proxy = fields.Str(load_default=None)
    messages_file = fields.Str(load_default=None)
    group_id = fields.Int(required=True)


# Bot and process storage --------------------------------------------------

bots: Dict[int, BotInstance] = {}
processes: Dict[int, subprocess.Popen] = {}


def log_sync_event(entity: str, action: str, payload: dict) -> None:
    """Store a sync event and emit it over WebSocket."""
    evt = SyncEvent(
        event_id=str(uuid4()),
        entity=entity,
        action=action,
        payload=payload,
    )
    db.session.add(evt)
    db.session.commit()
    socketio.emit(
        "sync_event",
        {
            "event_id": evt.event_id,
            "entity": evt.entity,
            "action": evt.action,
            "payload": evt.payload,
            "timestamp": evt.timestamp.isoformat(),
        },
    )


# Application factory ------------------------------------------------------


def create_app(config: Optional[dict] = None) -> Flask:
    """Create and configure the Flask application."""

    base_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        static_folder=str(base_dir.parent / "app" / "static"),
        template_folder=str(base_dir.parent / "app" / "templates"),
    )
    global APP
    APP = app
    db_uri = os.getenv("DATABASE_URL") or f"sqlite:///{cfg.DB_PATH}"
    app.config.update(
        {
            "SECRET_KEY": cfg.SECRET_KEY,
            "SQLALCHEMY_DATABASE_URI": db_uri,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "JWT_SECRET_KEY": cfg.JWT_SECRET_KEY,
            "JWT_ACCESS_TOKEN_EXPIRES": timedelta(minutes=15),
            "JWT_REFRESH_TOKEN_EXPIRES": timedelta(days=1),
            "TOTP_SECRET": cfg.TOTP_SECRET,
            "SENTRY_DSN": cfg.SENTRY_DSN,
            "SLACK_WEBHOOK": cfg.SLACK_WEBHOOK,
            "TELEGRAM_TOKEN": cfg.TELEGRAM_TOKEN,
            "TELEGRAM_CHAT_ID": cfg.TELEGRAM_CHAT_ID,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "SESSION_COOKIE_SECURE": not os.getenv("DEBUG", "true").lower() == "true",
        }
    )
    if config:
        app.config.update(config)

    testing = app.config.get("TESTING") or os.getenv("TESTING")
    if testing:
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
    app.config.setdefault("LOGIN_DISABLED", bool(testing))
    init_cache(app)
    init_logging(app.config.get("SENTRY_DSN"))
    global redis_conn, queue, redis_online
    redis_conn = redis.from_url(cfg.REDIS_URL or "redis://localhost:6379/0")
    queue = Queue("bots", connection=redis_conn)
    try:
        redis_conn.ping()
        redis_online = True
        logger.info("Connected to Redis")
    except Exception:  # noqa: broad-except
        redis_online = False
        logger.warning("Redis unavailable, tasks will run inline")
    app.redis_online = redis_online
    app.config.setdefault("SYNC_FALLBACK_FILE", str(SYNC_FALLBACK))
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

    if not sched.running:

        def enqueue_sync():
            try:
                redis_conn.ping()
                fb = Path(app.config.get("SYNC_FALLBACK_FILE", SYNC_FALLBACK))
                if fb.exists():
                    fb.unlink()
                queue.enqueue(process_unsent_events)
                if not getattr(app, "redis_online", True):
                    socketio.emit("redis_status", {"online": True})
                app.redis_online = True
            except RedisConnError:
                logger.warning("Redis unavailable, deferring sync")
                if getattr(app, "redis_online", True):
                    socketio.emit("redis_status", {"online": False})
                app.redis_online = False
                with app.app_context():
                    events = SyncEvent.query.filter_by(synced=False).all()
                fb = Path(app.config.get("SYNC_FALLBACK_FILE", SYNC_FALLBACK))
                with fb.open("a") as fh:
                    for e in events:
                        fh.write(json.dumps({"event_id": e.event_id}) + "\n")

                def retry():
                    try:
                        redis_conn.ping()
                        queue.enqueue(process_unsent_events)
                        fb = Path(app.config.get("SYNC_FALLBACK_FILE", SYNC_FALLBACK))
                        if fb.exists():
                            fb.unlink()
                        socketio.emit("redis_status", {"online": True})
                        app.redis_online = True
                    except RedisConnError:
                        with app.app_context():
                            events = SyncEvent.query.filter_by(synced=False).all()
                        fb = Path(app.config.get("SYNC_FALLBACK_FILE", SYNC_FALLBACK))
                        with fb.open("a") as fh:
                            for e in events:
                                fh.write(json.dumps({"event_id": e.event_id}) + "\n")

                Timer(10, retry).start()

        sched.add_job(
            enqueue_sync,
            "interval",
            minutes=1,
            id="sync_sender",
            replace_existing=True,
        )
        sched.start()

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
            if claims.get("role") not in roles:
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
    claims = {"role": role}
    access = create_access_token(identity=user, additional_claims=claims)
    refresh = create_refresh_token(identity=user, additional_claims=claims)
    session["user"] = user
    session["role"] = role
    return {"access_token": access, "refresh_token": refresh}


@auth_bp.route("/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh_token():
    claims = get_jwt()
    identity = claims["sub"]
    access = create_access_token(
        identity=identity, additional_claims={"role": claims.get("role")}
    )
    return {"access_token": access}


@ns.route("/groups", methods=["GET", "POST"], endpoint="groups")
class GroupResource(Resource):
    @jwt_required(optional=True)
    def get(self):
        search = (request.args.get("search") or "").strip()
        try:
            page = int(request.args.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        try:
            per_page = int(request.args.get("per_page", 50))
        except (TypeError, ValueError):
            per_page = 50
        if not search and page == 1 and per_page == 50:
            groups = cache.get("groups")
            if groups is not None:
                return groups
        query = Group.query
        if search:
            query = query.filter(Group.name.ilike(f"%{search}%"))
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        groups = []
        for g in pagination.items:
            groups.append(
                {
                    "id": g.id,
                    "name": g.name,
                    "target": g.target,
                    "interval": g.interval,
                    "bots": [{"id": a.id, "username": a.username} for a in g.accounts],
                }
            )
        if not search and page == 1 and per_page == 50:
            cache.set("groups", groups, timeout=60)
        logger.info("fetched groups list")
        return {"items": groups, "total": pagination.total}

    @limiter.limit("10/minute")
    @role_required("operator", "admin")
    def post(self):
        try:
            data = GroupSchema().load(request.get_json(silent=True) or {})
        except ValidationError as err:
            return {"errors": err.messages}, 400
        if Group.query.filter_by(name=data["name"]).first():
            logger.warning("duplicate group name %s", data["name"])
            return {"error": "Group name already exists."}, 400
        group = Group(**data)
        try:
            db.session.add(group)
            db.session.commit()
            log_sync_event(
                "group",
                "create",
                {
                    "id": group.id,
                    "name": group.name,
                    "target": group.target,
                    "interval": group.interval,
                },
            )
        except IntegrityError:
            db.session.rollback()
            logger.warning("duplicate group name %s", group.name)
            return {"error": "Group name already exists."}, 400
        except Exception as exc:  # noqa: broad-except
            logger.warning("group creation failed: %s", exc)
            return {"error": "could not create group"}, 400
        logger.info("created group %s", group.name)
        return {"id": group.id}, 201


@ns.route("/accounts", methods=["GET", "POST"], endpoint="accounts")
class AccountResource(Resource):
    @jwt_required(optional=True)
    def get(self):
        search = (request.args.get("search") or "").strip()
        try:
            page = int(request.args.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        try:
            per_page = int(request.args.get("per_page", 50))
        except (TypeError, ValueError):
            per_page = 50
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
        logger.info("fetched accounts list")
        return {"items": accounts, "total": pagination.total}

    @limiter.limit("10/minute")
    @role_required("operator", "admin")
    def post(self):
        try:
            data = AccountSchema().load(request.get_json(silent=True) or {})
        except ValidationError as err:
            return {"errors": err.messages}, 400
        group = Group.query.get(data["group_id"])
        if not group:
            logger.warning("invalid group id %s", data["group_id"])
            return {"error": "Invalid group_id"}, 400
        if Account.query.filter_by(username=data["username"]).first():
            return {"error": "account already exists"}, 400
        account = Account(**data)
        try:
            db.session.add(account)
            db.session.commit()
            log_sync_event(
                "account",
                "create",
                {
                    "id": account.id,
                    "username": account.username,
                    "group_id": account.group_id,
                },
            )
        except Exception as exc:  # noqa: broad-except
            logger.warning("account creation failed: %s", exc)
            db.session.rollback()
            return {"error": "could not create account"}, 400
        logger.info("created account %s in group %s", account.username, group.name)
        return {"id": account.id, "group_id": account.group_id}, 201


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


@ns.route("/bots", methods=["GET", "POST"], endpoint="bot_list")
class BotList(Resource):
    @jwt_required(optional=True)
    def get(self):
        search = (request.args.get("search") or "").strip()
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        query = Account.query
        if search:
            query = query.filter(Account.username.ilike(f"%{search}%"))
        if request.args.get("group_id"):
            try:
                gid = int(request.args.get("group_id"))
                query = query.filter_by(group_id=gid)
            except ValueError:
                pass
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        result = []
        for acc in pagination.items:
            status = "offline"
            bot = bots.get(acc.id)
            if bot and bot.ws and not bot.ws.closed:
                status = "online"
            result.append(
                {
                    "id": acc.id,
                    "username": acc.username,
                    "group_id": acc.group_id,
                    "group": acc.group.name if acc.group else None,
                    "status": status,
                }
            )
        logger.info("fetched bots list")
        return {"items": result, "total": pagination.total}

    @limiter.limit("10/minute")
    @role_required("operator", "admin")
    def post(self):
        try:
            data = AccountSchema().load(request.get_json(silent=True) or {})
        except ValidationError as err:
            return {"errors": err.messages}, 400
        group = Group.query.get(data["group_id"])
        if not group:
            logger.warning("invalid group id %s", data["group_id"])
            return {"error": "group not found"}, 400
        if Account.query.filter_by(username=data["username"]).first():
            return {"error": "account already exists"}, 400
        account = Account(**data)
        try:
            db.session.add(account)
            db.session.commit()
            log_sync_event(
                "account",
                "create",
                {
                    "id": account.id,
                    "username": account.username,
                    "group_id": account.group_id,
                },
            )
        except Exception as exc:  # noqa: broad-except
            logger.warning("account creation failed: %s", exc)
            db.session.rollback()
            return {"error": "could not create account"}, 400
        logger.info("created account %s in group %s", account.username, group.name)
        return {
            "id": account.id,
            "username": account.username,
            "group_id": account.group_id,
        }, 201


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
        log_sync_event("bot", "start", {"id": bot_id})
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
        socketio.emit("bot_stopped", {"id": bot_id})
        socketio.emit("status", {"message": f"bot {bot_id} stopped"})
        log_sync_event("bot", "stop", {"id": bot_id})
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
        try:
            job = queue.enqueue(run_bot_task, bot_id, retry=Retry(max=3))
            return {"job_id": job.id, "queued": True}
        except RedisConnError:
            logger.warning("Redis unavailable, running task inline")
            run_bot_task(bot_id)
            return {"job_id": None, "queued": False}


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
    data = generate_latest(registry)
    return Response(data, mimetype="text/plain")


@api_bp.route("/dashboard/api/stats")
@jwt_required(optional=True)
def stats():
    """Return simple counter stats for charts."""
    return {
        "runs": runs_counter._value.get(),
        "errors": errors_counter._value.get(),
    }


@api_bp.route("/dashboard/api/status")
@jwt_required(optional=True)
def app_status():
    """Return simple status information for the UI."""
    return {"redis_online": getattr(current_app, "redis_online", True)}


@api_bp.route("/sync/pull", methods=["GET"])
@jwt_required(optional=True)
def sync_pull():
    events = SyncEvent.query.filter_by(synced=False).all()
    data = [
        {
            "event_id": e.event_id,
            "entity": e.entity,
            "action": e.action,
            "payload": e.payload,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in events
    ]
    for e in events:
        e.synced = True
    db.session.commit()
    return {"events": data}


@api_bp.route("/sync/push", methods=["POST"])
@jwt_required(optional=True)
def sync_push():
    items = request.get_json(silent=True) or []
    processed = []
    for item in items:
        event_id = item.get("event_id") or str(uuid4())
        if SyncEvent.query.filter_by(event_id=event_id).first():
            continue
        evt = SyncEvent(
            event_id=event_id,
            entity=item.get("entity", ""),
            action=item.get("action", ""),
            payload=item.get("payload"),
            timestamp=(
                datetime.fromisoformat(item.get("timestamp"))
                if item.get("timestamp")
                else datetime.utcnow()
            ),
            synced=True,
        )
        db.session.add(evt)
        processed.append(event_id)
        # apply simple changes
        if evt.entity == "group" and evt.action == "create":
            name = evt.payload.get("name")
            if name and not Group.query.filter_by(name=name).first():
                db.session.add(
                    Group(
                        name=name,
                        target=evt.payload.get("target", ""),
                        interval=evt.payload.get("interval", 600),
                    )
                )
        elif evt.entity == "bot" and evt.action == "start":
            # only log event; actual starting handled elsewhere
            pass
    db.session.commit()
    return {"processed": processed}


# Utility functions --------------------------------------------------------


def run_bot_task(bot_id: int) -> None:
    """Run a bot via subprocess for the job queue."""
    logger.info("starting bot task %s", bot_id)
    app = APP if APP else create_app()
    with app.app_context():
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
        socketio.emit("bot_stopped", {"id": bot_id})
    except Exception as exc:  # noqa: broad-except
        errors_counter.inc()
        logger.error("bot run failed: %s", exc)
        webhook = cfg.SLACK_WEBHOOK
        if webhook:
            notify_webhook(webhook, f"Bot {bot_id} failed: {exc}")
        if cfg.TELEGRAM_TOKEN and cfg.TELEGRAM_CHAT_ID:
            url = f"https://api.telegram.org/bot{cfg.TELEGRAM_TOKEN}/sendMessage"
            notify_webhook(
                url,
                "",
                params={
                    "chat_id": cfg.TELEGRAM_CHAT_ID,
                    "text": f"Bot {bot_id} failed: {exc}",
                },
            )
        socketio.emit("bot_error", {"id": bot_id})


def schedule_all() -> None:
    """Schedule message sending for all accounts."""
    sched.remove_all_jobs()
    for acc in Account.query.all():
        group = Group.query.get(acc.group_id)
        if not group:
            continue
        try:
            sched.add_job(
                lambda aid=acc.id: asyncio.run_coroutine_threadsafe(
                    send_job(aid), aio_loop
                ),
                "interval",
                seconds=group.interval,
                id=str(acc.id),
                replace_existing=True,
            )
        except Exception as exc:  # noqa: broad-except
            logger.error("could not schedule job %s: %s", acc.id, exc)


async def send_job(account_id: int) -> None:
    app = APP if APP else current_app
    with app.app_context():
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
        socketio.emit("bot_stopped", {"id": account_id})
    except Exception as exc:  # noqa: broad-except
        errors_counter.inc()
        logger.error("send job failed: %s", exc)
        socketio.emit("bot_error", {"id": account_id})
    with current_app.app_context():
        log = Log(account_id=account_id, message=message)
        db.session.add(log)
        db.session.commit()
    socketio.emit("status", {"message": f"sent message for {account_id}"})


def process_unsent_events() -> None:
    """Emit unsent sync events via WebSocket and mark them synced."""
    app = create_app()
    with app.app_context():
        events = SyncEvent.query.filter_by(synced=False).all()
        for evt in events:
            socketio.emit(
                "sync_event",
                {
                    "event_id": evt.event_id,
                    "entity": evt.entity,
                    "action": evt.action,
                    "payload": evt.payload,
                    "timestamp": evt.timestamp.isoformat(),
                },
            )
            evt.synced = True
        db.session.commit()


def register_api(app: Flask) -> None:
    api.init_app(app)
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
