from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Thread, Timer as _Timer  # Timer re-exported for tests
import subprocess
from typing import Dict, Optional
from uuid import uuid4

import redis
from rq import Queue
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from flask import current_app, Flask
from shared.config import load_config
from shared.logger import logger, notify_webhook
from bots.instance import BotInstance
from .models import db, Group, Account, Log, SyncEvent
from flask_socketio import SocketIO
from prometheus_client import Counter, Gauge, CollectorRegistry

Timer = _Timer

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

redis_conn: Optional[redis.Redis] = None
queue = None
redis_online = True
APP: Optional[Flask] = None

registry = CollectorRegistry()
runs_counter = Counter("bot_runs", "Number of bot executions", registry=registry)
errors_counter = Counter("bot_errors", "Number of bot errors", registry=registry)
running_gauge = Gauge(
    "bots_running", "Currently running bot processes", registry=registry
)

bots: Dict[int, BotInstance] = {}
processes: Dict[int, subprocess.Popen] = {}


def init_redis() -> None:
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


def log_sync_event(entity: str, action: str, payload: dict, socketio: SocketIO) -> None:
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


def run_bot_task(bot_id: int, socketio: SocketIO) -> None:
    logger.info("starting bot task %s", bot_id)
    app = APP or current_app
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
        socketio.emit("bot_error", {"id": bot_id})


def schedule_all(socketio: SocketIO) -> None:
    sched.remove_all_jobs()
    for acc in Account.query.all():
        group = Group.query.get(acc.group_id)
        if not group:
            continue
        try:
            sched.add_job(
                lambda aid=acc.id: asyncio.run_coroutine_threadsafe(
                    send_job(aid, socketio), aio_loop
                ),
                "interval",
                seconds=group.interval,
                id=str(acc.id),
                replace_existing=True,
            )
        except Exception as exc:  # noqa: broad-except
            logger.error("could not schedule job %s: %s", acc.id, exc)


async def send_job(account_id: int, socketio: SocketIO) -> None:
    app = APP or current_app
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
    with app.app_context():
        log = Log(account_id=account_id, message=message)
        db.session.add(log)
        db.session.commit()
    socketio.emit("status", {"message": f"sent message for {account_id}"})


def process_unsent_events(socketio: SocketIO) -> None:
    app = APP or current_app
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
