"""Backend service for managing Kick chat bots."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
import os
from threading import Thread

from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
import websockets

# retry attempts for websocket messages
MAX_RETRIES = 3

BASE_DIR = Path(__file__).resolve().parent
app = Flask(
    __name__, static_folder=str(BASE_DIR.parent / "frontend"), static_url_path=""
)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///bots.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

class Bot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String(80), nullable=False)
    message = db.Column(db.String(200), nullable=False)
    interval = db.Column(db.Integer, nullable=False)
    token = db.Column(db.String(200), nullable=False)
    active = db.Column(db.Boolean, default=True)

class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    message = db.Column(db.String(200))
    channel = db.Column(db.String(80))

scheduler = BackgroundScheduler(
    executors={"default": ThreadPoolExecutor(max_workers=100)},
    job_defaults={"max_instances": 50},
)
scheduler.start()

class KickClient:
    """Minimal WebSocket client with reconnect logic for a user."""

    def __init__(self, uri: str, token: str):
        self.uri = uri
        self.token = token
        self.ws = None
        self._lock = asyncio.Lock()

    async def _connect(self):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                headers = {"Authorization": f"Bearer {self.token}"}
                self.ws = await websockets.connect(
                    self.uri,
                    extra_headers=headers,
                    ping_interval=20,
                    ping_timeout=20,
                )
                return
            except Exception as exc:  # pragma: no cover - connection errors
                print(f"connect attempt {attempt} failed: {exc}")
                await asyncio.sleep(1)

    async def send(self, channel: str, message: str):
        payload = json.dumps({"channel": channel, "message": message})
        async with self._lock:
            if not self.ws or self.ws.closed:
                await self._connect()
            try:
                await self.ws.send(payload)
            except Exception as exc:
                print(f"send failed: {exc}")
                await self._connect()
                await self.ws.send(payload)


KICK_URI = os.getenv("KICK_URI", "wss://chat.kick.com")
_clients = {}

def get_client(token: str) -> "KickClient":
    """Return a cached KickClient for a given token."""
    if token not in _clients:
        _clients[token] = KickClient(KICK_URI, token)
    return _clients[token]

async def send_kick_message(token: str, channel: str, message: str):
    """Send a message using a user's token."""
    client = get_client(token)
    await client.send(channel, message)

async def schedule_job(bot_id: int, token: str, channel: str, message: str):
    await send_kick_message(token, channel, message)
    log = Log(bot_id=bot_id, message=message, channel=channel)
    db.session.add(log)
    db.session.commit()

def start_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

# Background asyncio event loop
aio_loop = asyncio.new_event_loop()
thread = Thread(target=start_async_loop, args=(aio_loop,))
thread.daemon = True
thread.start()

# Initialize database
def initialize_jobs():
    """Schedule all bots from the database on startup."""
    for bot in Bot.query.all():
        schedule_bot(bot)

with app.app_context():
    db.create_all()

@app.route('/')
def index():
    """Serve the single page application."""
    return app.send_static_file('index.html')
@app.route('/bots', methods=['GET'])
def list_bots():
    bots = Bot.query.all()
    return jsonify([
        {
            "id": b.id,
            "channel": b.channel,
            "message": b.message,
            "interval": b.interval,
            "token": b.token,
            "active": b.active,
        }
        for b in bots
    ])

@app.route('/bots', methods=['POST'])
def create_bot():
    data = request.json
    bot = Bot(
        channel=data["channel"],
        message=data["message"],
        interval=data["interval"],
        token=data["token"],
        active=data.get("active", True),
    )
    db.session.add(bot)
    db.session.commit()
    schedule_bot(bot)
    return jsonify({'id': bot.id}), 201

@app.route('/bots/<int:bot_id>', methods=['GET'])
def get_bot(bot_id):
    """Return single bot details."""
    bot = Bot.query.get_or_404(bot_id)
    return jsonify({
        'id': bot.id,
        'channel': bot.channel,
        'message': bot.message,
        'interval': bot.interval,
        'token': bot.token,
        'active': bot.active,
    })

@app.route('/bots/<int:bot_id>', methods=['PUT'])
def update_bot(bot_id):
    bot = Bot.query.get_or_404(bot_id)
    data = request.json
    bot.channel = data.get('channel', bot.channel)
    bot.message = data.get('message', bot.message)
    bot.interval = data.get('interval', bot.interval)
    bot.token = data.get('token', bot.token)
    bot.active = data.get('active', bot.active)
    db.session.commit()
    schedule_bot(bot)
    return jsonify({'status': 'updated'})

@app.route('/bots/<int:bot_id>', methods=['DELETE'])
def delete_bot(bot_id):
    bot = Bot.query.get_or_404(bot_id)
    scheduler.remove_job(str(bot.id))
    db.session.delete(bot)
    db.session.commit()
    return jsonify({'status': 'deleted'})

@app.route('/bots/<int:bot_id>/toggle', methods=['POST'])
def toggle_bot(bot_id):
    """Toggle bot active state."""
    bot = Bot.query.get_or_404(bot_id)
    bot.active = not bot.active
    db.session.commit()
    schedule_bot(bot)
    return jsonify({'active': bot.active})

@app.route('/bots/<int:bot_id>/send', methods=['POST'])
def send_now(bot_id):
    bot = Bot.query.get_or_404(bot_id)
    asyncio.run_coroutine_threadsafe(
        schedule_job(bot.id, bot.token, bot.channel, bot.message), aio_loop
    )
    return jsonify({'status': 'sent'})

@app.route('/logs', methods=['GET'])
def get_logs():
    logs = Log.query.order_by(Log.timestamp.desc()).limit(50).all()
    return jsonify([{"id": l.id, "bot_id": l.bot_id, "timestamp": l.timestamp.isoformat(),
                     "message": l.message, "channel": l.channel} for l in logs])

@app.route('/bots/<int:bot_id>/logs', methods=['GET'])
def get_bot_logs(bot_id):
    """Return recent logs for a single bot."""
    logs = Log.query.filter_by(bot_id=bot_id).order_by(Log.timestamp.desc()).limit(50).all()
    return jsonify([{"id": l.id, "timestamp": l.timestamp.isoformat(), "message": l.message,
                     "channel": l.channel} for l in logs])

def schedule_bot(bot: Bot):
    """Create or update a scheduled job for the bot."""
    if scheduler.get_job(str(bot.id)):
        scheduler.remove_job(str(bot.id))
    if bot.active:
        scheduler.add_job(
            lambda: asyncio.run_coroutine_threadsafe(
                schedule_job(bot.id, bot.token, bot.channel, bot.message), aio_loop
            ),
            'interval', seconds=bot.interval, id=str(bot.id), replace_existing=True
        )

# Schedule bots on startup
with app.app_context():
    initialize_jobs()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
