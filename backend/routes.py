from __future__ import annotations

from pathlib import Path

from flask import Blueprint, request, current_app, Response
from flask_restx import Api, Resource
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt,
)
from marshmallow import ValidationError
from redis.exceptions import ConnectionError as RedisConnError
from rq import Retry
from prometheus_client import generate_latest

from shared.cache import cache
from .models import db, Group, Account, GroupSchema, AccountSchema
from .utils import role_required
from .scheduler import sched, queue, run_bot_task, schedule_all, log_sync_event

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
    if user == "admin" and password == current_app.config.get(
        "ADMIN_PASSWORD", "admin"
    ):
        role = "admin"
    elif user == "operator" and password == current_app.config.get(
        "OPERATOR_PASSWORD", "operator"
    ):
        role = "operator"
    else:
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
            {
                "id": g.id,
                "name": g.name,
                "target": g.target,
                "interval": g.interval,
                "bots": [{"id": a.id, "username": a.username} for a in g.accounts],
            }
            for g in pagination.items
        ]
        if not search and page == 1 and per_page == 50:
            cache.set("groups", groups, timeout=60)
        return {"items": groups, "total": pagination.total}

    @role_required("operator", "admin")
    def post(self):
        try:
            data = GroupSchema().load(request.get_json(silent=True) or {})
        except ValidationError as err:
            return {"errors": err.messages}, 400
        if Group.query.filter_by(name=data["name"]).first():
            return {"error": "Group name already exists."}, 400
        group = Group(**data)
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
            current_app.extensions["socketio"],
        )
        return {"id": group.id}, 201


@ns.route("/accounts", methods=["GET", "POST"], endpoint="accounts")
class AccountResource(Resource):
    @jwt_required(optional=True)
    def get(self):
        search = (request.args.get("search") or "").strip()
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
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
            return {"errors": err.messages}, 400
        if not Group.query.get(data["group_id"]):
            return {"error": "Invalid group_id"}, 400
        if Account.query.filter_by(username=data["username"]).first():
            return {"error": "account already exists"}, 400
        account = Account(**data)
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
        try:
            job = queue.enqueue(
                run_bot_task,
                bot_id,
                current_app.extensions["socketio"],
                retry=Retry(max=3),
            )
            return {"job_id": job.id, "queued": True}
        except RedisConnError:
            run_bot_task(bot_id, current_app.extensions["socketio"])
            return {"job_id": None, "queued": False}


@ns.route("/bots/<int:bot_id>/status", methods=["GET"], endpoint="bot_status")
class BotStatus(Resource):
    @jwt_required(optional=True)
    def get(self, bot_id: int):
        path = Path("logs") / f"bot_{bot_id}.log"
        running = path.exists()
        return {"running": running}


@api_bp.route("/metrics")
@jwt_required(optional=True)
def metrics():
    from .scheduler import registry

    data = generate_latest(registry)
    return Response(data, mimetype="text/plain")
