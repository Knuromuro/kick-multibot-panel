# KickBot Dashboard

KickBot is a simple web panel for managing chat bots for [Kick.com](https://kick.com). Bots send messages to channels over WebSocket on a schedule and can be controlled from the dashboard.

## Features

- Login page (`admin`/`admin`)
- Create, edit and delete bots with individual messages and intervals
- Manual "Send now" button and automatic scheduling
- Logs stored in a local SQLite database
- Web dashboard with live bot and log updates

## Setup

Install dependencies and start the server:

```bash
pip install -r requirements.txt
python run.py
```

Open <http://localhost:5000/login> and sign in. After logging in, the dashboard lets you manage up to 1000 bots.

Environment variables:

- `DB_PATH` – path to the SQLite file (default `bots.db`)
- `KICK_URI` – Kick WebSocket URI
- `WORKERS` – scheduler thread pool size
- `MAX_INSTANCES` – max concurrent jobs
- `SECRET_KEY` – session secret

## Bots

Each bot requires a Kick `auth_token` which can be obtained using `scripts/login_kick.py`. Bots are created and scheduled automatically. Logs can be viewed per bot from the dashboard.

## Scripts

- `scripts/add_bot.py` – create a bot via the API
- `scripts/run_bot.py` – run a standalone bot
- `scripts/login_kick.py` – retrieve a Kick auth token
