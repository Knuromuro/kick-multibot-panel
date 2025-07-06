# Kick Multibot Panel

This project provides a simple dashboard and backend for managing multiple
Kick.com chat bots. It is designed to support up to **1000** configured bots on
a single instance.

## Backend

- Python Flask application
- SQLite database using SQLAlchemy
- APScheduler for periodic messages
- Async WebSocket client for sending messages to Kick (authenticated via user tokens)

Run the backend (schedules existing bots automatically). The server port can be
changed via the `PORT` environment variable. The WebSocket address defaults to
`wss://chat.kick.com` but can be overridden with `KICK_URI`. The SQLite file
defaults to `bots.db` but can be set with `DB_PATH`. Scheduler limits can be
tuned with `WORKERS` and `MAX_INSTANCES`:
```
python backend/app.py
```

Install dependencies with:
```
pip install -r requirements.txt
```

You can retrieve your Kick `auth_token` by logging in with the helper script:
```
python scripts/login_kick.py --email user@example.com --password mypass
```
Copy the printed token when creating or editing bots.

You can quickly create a bot from the command line using the helper script:
```
python scripts/add_bot.py --channel mychannel --message "Hello" \
    --interval 600 --token <auth_token>
```

For quick testing you can run a standalone bot instance. The
`scripts/run_bot.py` helper connects to Kick and repeatedly sends a message on
the chosen channel at your desired interval:
```
python scripts/run_bot.py --channel mychannel --message "Hello" \
    --interval 600 --token <auth_token>
```

Each bot requires a Kick authentication token (cookie `auth_token`). Provide it
when creating or editing bots so messages are sent from the associated user
account.

## Frontend

Open `frontend/index.html` in your browser. It communicates with the backend via REST endpoints and auto-refreshes bot and log lists every few seconds. Bots can be edited using a dialog that pre-fills their current settings.

### Features
- Create, edit, toggle and delete bots (editing opens a dialog with existing values)
- Manual and scheduled message sending with reconnecting WebSocket client
- View recent logs globally or per bot
- Dashboard supports up to 1000 scheduled bots
- Bots send messages from provided user accounts
- All bot options are accessible directly from the dashboard
