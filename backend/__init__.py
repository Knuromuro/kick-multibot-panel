from __future__ import annotations

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from threading import Timer
from typing import Optional

from flask import Flask, request
from flask_socketio import SocketIO
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_jwt_extended import JWTManager
from flask_restx import Api
from redis.exceptions import ConnectionError as RedisConnError

from shared.config import load_config
from shared.cache import init_cache
from shared.logger import logger, init_logging
from .models import db, SyncEvent
from . import scheduler
from .scheduler import sched, enqueue_sync_job
from .routes import api_bp, auth_bp
from app.routes import register_web

api = Api(doc="/docs")
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
talisman = Talisman()
jwt = JWTManager()
socketio = SocketIO(cors_allowed_origins="*")

cfg = load_config()


def create_app(config: Optional[dict] = None) -> Flask:
    base_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        static_folder=str(base_dir.parent / "app" / "static"),
        template_folder=str(base_dir.parent / "app" / "templates"),
    )

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
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "SESSION_COOKIE_SECURE": not os.getenv("DEBUG", "true").lower() == "true",
        }
    )
    if config:
        app.config.update(config)

    testing = app.config.get("TESTING") or os.getenv("TESTING")
    if testing:
        app.config["WTF_CSRF_ENABLED"] = False
    app.config.setdefault("LOGIN_DISABLED", bool(testing))

    init_cache(app)
    init_logging(None)
    csrf.init_app(app)
    limiter.init_app(app)
    talisman.init_app(app, force_https=not app.config.get("TESTING", False))
    jwt.init_app(app)
    db.init_app(app)
    socketio.init_app(app)

    scheduler.init_redis()
    app.redis_online = True
    app.config.setdefault("SYNC_FALLBACK_FILE", str(Path("sync_fallback.jsonl")))

    if not sched.running:

        def enqueue_sync():
            try:
                scheduler.queue.connection.ping()
                fb = Path(app.config["SYNC_FALLBACK_FILE"])
                if fb.exists():
                    fb.unlink()
                scheduler.queue.enqueue(enqueue_sync_job)
                if not getattr(app, "redis_online", True):
                    logger.info("Redis connection restored")
                    socketio.emit("redis_status", {"online": True})
                app.redis_online = True
            except RedisConnError:
                if getattr(app, "redis_online", True):
                    logger.warning("Redis unavailable, deferring sync")
                    socketio.emit("redis_status", {"online": False})
                app.redis_online = False
                with app.app_context():
                    events = SyncEvent.query.filter_by(synced=False).all()
                fb = Path(app.config["SYNC_FALLBACK_FILE"])
                with fb.open("a") as fh:
                    for e in events:
                        fh.write(json.dumps({"event_id": e.event_id}) + "\n")
                Timer(10, enqueue_sync).start()

        sched.add_job(
            enqueue_sync, "interval", minutes=1, id="sync_sender", replace_existing=True
        )
        sched.start()

    @app.before_request
    def log_request() -> None:
        ua = request.headers.get("User-Agent", "")
        entry = f"{datetime.utcnow().isoformat()} {request.path} {ua}\n"
        try:
            with open("analytics.log", "a") as fh:
                fh.write(entry)
        except Exception:
            pass

    register_web(app)
    api.init_app(app)
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    with app.app_context():
        db.create_all()

    return app
