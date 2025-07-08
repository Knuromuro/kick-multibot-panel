# KickBot Manager

KickBot Manager is a lightweight dashboard for controlling chat bots on [Kick.com](https://kick.com). It combines a Flask backend with a simple Tailwind based frontend. Bots connect to Kick chat via WebSocket and can be scheduled or commanded from the web panel.

## Features

- Manage groups and accounts stored in a SQLite database
- Start an asynchronous scheduler that sends messages from accounts to their group's target
- Issue commands to running bots: send a message, check status, restart connection or capture a screenshot
- View the last 50 log lines per bot

## Setup

Install dependencies and start the server:

```bash
pip install -r requirements.txt
python run.py
```

Login at `http://localhost:5000/login` with **admin/admin**.

### Environment variables

- `PORT` – server port (default 5000)
- `DB_PATH` – SQLite file (default `bots.db`)
- `SECRET_KEY` – Flask secret key
- `WORKERS` – scheduler thread pool size (default 50)
- `MAX_INSTANCES` – maximum concurrent scheduled jobs (default 50)
- `KICK_WS_URI` – WebSocket endpoint for Kick chat

## Usage

1. Create a group with a target channel and interval.
2. Add accounts pointing to that group. Each account may specify a messages file with text to send.
3. Click **Start Scheduler** to begin automated sending. Bots run in batches and reconnect on failure.
4. Use the command button next to a bot to send manual messages or request a screenshot.

Logs are stored under `logs/` with one file per bot.
