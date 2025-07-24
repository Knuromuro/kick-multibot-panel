from __future__ import annotations

from pathlib import Path
import subprocess

from flask import Blueprint, request, current_app, Response
from flask_restx import Api, Resource
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt,
)
from marshmallow import ValidationError
from prometheus_client import generate_latest

from shared.cache import cache
from shared.logger import logger
from .models import db, Group, Account, GroupSchema, AccountSchema, SyncEvent
from .utils import role_required
from . import scheduler
from .scheduler import sched, schedule_all, log_sync_event
import bcrypt

api_bp = Blueprint("api", __name__)
api = Api(api_bp, doc="/docs")
ns = api.namespace("api", path="/dashboard/api")

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/auth/token", methods=["POST"])
def get_token():
    data = request.get_json() or {}
    user = data.get("username")
    password = data.get("password")
    totp = data.get("totp")
    role = None
    if user in {"admin", "operator"}:
        hashed = current_app.config.get(f"{user.upper()}_PASSWORD_HASH")
        if hashed:
            try:
                valid = bcrypt.checkpw(password.encode(), hashed.encode())
            except Exception:
                valid = False
        else:
            env_plain = current_app.config.get(f"{user.upper()}_PASSWORD", user)
            valid = password == env_plain
        if valid:
            role = user
    if role is None:
        return {"msg": "bad credentials"}, 401
    secret = current_app.config.get("TOTP_SECRET")
    if secret:
        import pyotp

        if not pyotp.TOTP(secret).verify(str(totp)):
            return {"msg": "invalid token"}, 401
    claims = {"role": role}
    access = create_access_token(identity=user, additional_claims=claims)
    refresh = create_refresh_token(identity=user, additional_claims=claims)
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
        page = int(request.args.get("page") or 1)
        per_page = int(request.args.get("per_page") or 50)
        if not search and page == 1 and per_page == 50:
            cached = cache.get("groups")
            if cached is not None:
                return cached
        query = Group.query
        if search:
            query = query.filter(Group.name.ilike(f"%{search}%"))
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        groups = [
            {
                "id": g.id,
                "name": g.name,
                "target": g.target,
                "interval": g.interval,
                "bots": [{"id": a.id, "username": a.username} for a in g.accounts],
            }
            for g in pagination.items
        ]
        result = {"items": groups, "total": pagination.total}
        if not search and page == 1 and per_page == 50:
            cache.set("groups", result, timeout=60)
        return result

    @role_required("operator", "admin")
    def post(self):
        try:
            data = GroupSchema().load(request.get_json(silent=True) or {})
        except ValidationError as err:
            logger.warning("invalid group payload: %s", err.messages)
            return {"errors": err.messages}, 400
        if Group.query.filter_by(name=data["name"]).first():
            logger.warning("duplicate group name %s", data["name"])
            return {"error": "Group name already exists."}, 400
        group = Group(**data)
        db.session.add(group)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.error("database error creating group", exc_info=True)
            return {"error": "database error"}, 400
        logger.info("created group %s", group.name)
        log_sync_event(
            "group",
            "create",
            {
                "id": group.id,
                "name": group.name,
                "target": group.target,
                "interval": group.interval,
            },
            current_app.extensions["socketio"],
        )
        return {"id": group.id}, 201


@ns.route("/accounts", methods=["GET", "POST"], endpoint="accounts")
class AccountResource(Resource):
    @jwt_required(optional=True)
    def get(self):
        search = (request.args.get("search") or "").strip()
        page = int(request.args.get("page") or 1)
        per_page = int(request.args.get("per_page") or 50)
        query = Account.query
        if search:
            query = query.filter(Account.username.ilike(f"%{search}%"))
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        accounts = [
            {"id": a.id, "username": a.username, "group_id": a.group_id}
            for a in pagination.items
        ]
        return {"items": accounts, "total": pagination.total}

    @role_required("operator", "admin")
    def post(self):
        try:
            data = AccountSchema().load(request.get_json(silent=True) or {})
        except ValidationError as err:
            logger.warning("invalid account payload: %s", err.messages)
            return {"errors": err.messages}, 400
        group_id = data.get("group_id")
        group = Group.query.get(group_id)
        if not group:
            logger.warning(
                "invalid group_id %s for account %s", group_id, data.get("username")
            )
            return {"error": "Invalid group_id"}, 400
        if Account.query.filter_by(username=data["username"]).first():
            logger.warning("duplicate account username %s", data["username"])
            return {"error": "account already exists"}, 400
        account = Account(**data)
        db.session.add(account)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.error("database error creating account", exc_info=True)
            return {"error": "database error"}, 400
        logger.info("created account %s in group %s", account.username, group_id)
        log_sync_event(
            "account",
            "create",
            {
                "id": account.id,
                "username": account.username,
                "group_id": account.group_id,
            },
            current_app.extensions["socketio"],
        )
        return {"id": account.id, "group_id": account.group_id}, 201


@ns.route("/bots", methods=["GET", "POST"], endpoint="bots")
class BotListResource(Resource):
    @jwt_required(optional=True)
    def get(self):
        search = (request.args.get("search") or "").strip()
        page = int(request.args.get("page") or 1)
        per_page = int(request.args.get("per_page") or 50)
        query = Account.query
        if search:
            query = query.filter(Account.username.ilike(f"%{search}%"))
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        bots = []
        for acc in pagination.items:
            status = (
                "online" if (Path("logs") / f"bot_{acc.id}.log").exists() else "offline"
            )
            bots.append(
                {
                    "id": acc.id,
                    "username": acc.username,
                    "group_id": acc.group_id,
                    "status": status,
                }
            )
        return {"items": bots, "total": pagination.total}

    @role_required("operator", "admin")
    def post(self):
        # same as account creation for convenience
        try:
            data = AccountSchema().load(request.get_json(silent=True) or {})
        except ValidationError as err:
            return {"errors": err.messages}, 400
        if not Group.query.get(data["group_id"]):
            return {"error": "Invalid group_id"}, 400
        if Account.query.filter_by(username=data["username"]).first():
            return {"error": "account already exists"}, 400
        account = Account(**data)
        db.session.add(account)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return {"error": "database error"}, 400
        log_sync_event(
            "account",
            "create",
            {
                "id": account.id,
                "username": account.username,
                "group_id": account.group_id,
            },
            current_app.extensions["socketio"],
        )
        return {"id": account.id, "group_id": account.group_id}, 201


@ns.route("/scheduler/start", methods=["POST"], endpoint="scheduler_start")
class SchedulerStart(Resource):
    @role_required("operator", "admin")
    def post(self):
        if not sched.running:
            sched.start()
        schedule_all(current_app.extensions["socketio"])
        return {"status": "started"}


@ns.route("/bots/<int:bot_id>/start", methods=["POST"], endpoint="bot_start")
class BotStart(Resource):
    @role_required("operator", "admin")
    def post(self, bot_id: int):
        group = Group.query.join(Account).filter(Account.id == bot_id).first()
        if not group:
            return {"error": "bot not found"}, 404
        msg_path = Path(Account.query.get(bot_id).messages_file or "")
        msg = "Hello from KickBot"
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
            Account.query.get(bot_id).password,
        ]
        proc = subprocess.Popen(cmd)
        scheduler.processes[bot_id] = proc
        scheduler.running_gauge.inc()
        current_app.extensions["socketio"].emit("bot_started", {"id": bot_id})
        return {"pid": proc.pid}


@ns.route("/bots/<int:bot_id>/stop", methods=["POST"], endpoint="bot_stop")
class BotStop(Resource):
    @role_required("operator", "admin")
    def post(self, bot_id: int):
        proc = scheduler.processes.get(bot_id)
        if proc and proc.poll() is None:
            proc.terminate()
            scheduler.running_gauge.dec()
            current_app.extensions["socketio"].emit("bot_stopped", {"id": bot_id})
            return {"stopped": True}
        return {"stopped": False}


@ns.route("/bots/<int:bot_id>/status", methods=["GET"], endpoint="bot_status")
class BotStatus(Resource):
    @jwt_required(optional=True)
    def get(self, bot_id: int):
        proc = scheduler.processes.get(bot_id)
        running = proc is not None and proc.poll() is None
        return {"running": running}


@ns.route("/bots/<int:bot_id>/logs", methods=["GET"], endpoint="bot_logs")
class BotLogs(Resource):
    """Return last 50 log lines for a bot."""

    @jwt_required(optional=True)
    def get(self, bot_id: int):
        log_path = Path("logs") / f"bot_{bot_id}.log"
        if not log_path.exists():
            return []
        lines = log_path.read_text(errors="ignore").splitlines()[-50:]
        return lines


@ns.route("/stats", methods=["GET"], endpoint="stats")
class Stats(Resource):
    @jwt_required(optional=True)
    def get(self):
        return {
            "runs": int(scheduler.runs_counter._value.get()),
            "errors": int(scheduler.errors_counter._value.get()),
        }


@api_bp.route("/sync/pull")
@jwt_required(optional=True)
def sync_pull():
    events = SyncEvent.query.filter_by(synced=False).all()
    data = []
    for e in events:
        data.append(
            {
                "event_id": e.event_id,
                "entity": e.entity,
                "action": e.action,
                "payload": e.payload,
                "timestamp": e.timestamp.isoformat(),
            }
        )
        e.synced = True
    db.session.commit()
    return {"events": data}


@api_bp.route("/sync/push", methods=["POST"])
@jwt_required(optional=True)
def sync_push():
    payload = request.get_json(silent=True) or []
    if not isinstance(payload, list):
        return {"error": "invalid payload"}, 400
    for item in payload:
        if (
            not item.get("event_id")
            or SyncEvent.query.filter_by(event_id=item["event_id"]).first()
        ):
            continue
        se = SyncEvent(
            event_id=item["event_id"],
            entity=item.get("entity", ""),
            action=item.get("action", ""),
            payload=item.get("payload"),
            synced=True,
        )
        db.session.add(se)
        if se.entity == "group" and se.action == "create":
            if not Group.query.filter_by(name=se.payload.get("name")).first():
                db.session.add(
                    Group(
                        name=se.payload.get("name"),
                        target=se.payload.get("target"),
                        interval=se.payload.get("interval", 600),
                    )
                )
        elif se.entity == "account" and se.action == "create":
            if not Account.query.filter_by(
                username=se.payload.get("username")
            ).first() and Group.query.get(se.payload.get("group_id")):
                db.session.add(
                    Account(
                        username=se.payload.get("username"),
                        password=se.payload.get("password", ""),
                        proxy=se.payload.get("proxy"),
                        messages_file=se.payload.get("messages_file"),
                        group_id=se.payload.get("group_id"),
                    )
                )
    db.session.commit()
    return {"status": "ok"}


@api_bp.route("/metrics")
@jwt_required(optional=True)
def metrics():
    from .scheduler import registry

    data = generate_latest(registry)
    return Response(data, mimetype="text/plain")
