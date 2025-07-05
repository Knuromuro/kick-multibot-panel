import asyncio
import json
from datetime import datetime
from threading import Thread

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
import websockets

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bots.db'
db = SQLAlchemy(app)

class Bot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String(80), nullable=False)
    message = db.Column(db.String(200), nullable=False)
    interval = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, default=True)

class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    message = db.Column(db.String(200))
    channel = db.Column(db.String(80))

scheduler = BackgroundScheduler(
    executors={'default': ThreadPoolExecutor(max_workers=50)},
    job_defaults={'max_instances': 20}
)
scheduler.start()

async def send_kick_message(channel: str, message: str):
    """Send a message to Kick chat via WebSocket."""
    uri = "wss://chat.kick.com"
    try:
        async with websockets.connect(uri) as ws:
            payload = json.dumps({"channel": channel, "message": message})
            await ws.send(payload)
    except Exception as e:
        print(f"Failed to send message: {e}")

async def schedule_job(bot_id: int, channel: str, message: str):
    await send_kick_message(channel, message)
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

@app.route('/bots', methods=['GET'])
def list_bots():
    bots = Bot.query.all()
    return jsonify([{"id": b.id, "channel": b.channel, "message": b.message,
                     "interval": b.interval, "active": b.active} for b in bots])

@app.route('/bots', methods=['POST'])
def create_bot():
    data = request.json
    bot = Bot(channel=data['channel'], message=data['message'], interval=data['interval'])
    db.session.add(bot)
    db.session.commit()
    schedule_bot(bot)
    return jsonify({'id': bot.id}), 201

@app.route('/bots/<int:bot_id>', methods=['PUT'])
def update_bot(bot_id):
    bot = Bot.query.get_or_404(bot_id)
    data = request.json
    bot.channel = data.get('channel', bot.channel)
    bot.message = data.get('message', bot.message)
    bot.interval = data.get('interval', bot.interval)
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

@app.route('/bots/<int:bot_id>/send', methods=['POST'])
def send_now(bot_id):
    bot = Bot.query.get_or_404(bot_id)
    asyncio.run_coroutine_threadsafe(schedule_job(bot.id, bot.channel, bot.message), aio_loop)
    return jsonify({'status': 'sent'})

@app.route('/logs', methods=['GET'])
def get_logs():
    logs = Log.query.order_by(Log.timestamp.desc()).limit(50).all()
    return jsonify([{"id": l.id, "bot_id": l.bot_id, "timestamp": l.timestamp.isoformat(),
                     "message": l.message, "channel": l.channel} for l in logs])

def schedule_bot(bot: Bot):
    """Create or update a scheduled job for the bot."""
    scheduler.remove_job(str(bot.id)) if scheduler.get_job(str(bot.id)) else None
    if bot.active:
        scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(
            schedule_job(bot.id, bot.channel, bot.message), aio_loop),
            'interval', seconds=bot.interval, id=str(bot.id), replace_existing=True)

# Schedule bots on startup
with app.app_context():
    initialize_jobs()

if __name__ == '__main__':
    app.run(debug=True)
