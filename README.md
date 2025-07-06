# KickBot Dashboard

KickBot is a simple web panel for managing chat bots for [Kick.com](https://kick.com). Bots send messages to channels over WebSocket on a schedule and can be controlled from the dashboard.

## Features

- Login page (`admin`/`admin`)
- Create, edit and delete bots with individual messages and intervals
- Manual "Send now" button and automatic scheduling
- Logs stored in a local SQLite database
- Optional bot groups with "Start All" and "Start group" actions
- Web dashboard with live bot and log updates

## Setup

Install dependencies and start the server:

```bash
pip install -r requirements.txt
# optional environment variables can be set before running
# for example, launch the app on port 8000 without debug:
PORT=8000 DEBUG=false python run.py
# you can also run `python backend/app.py` directly, but `run.py` ensures the
# dashboard blueprint is registered
```

If the selected port is already taken, the server automatically falls back to a
random free port and prints a notice.

Open `http://localhost:<PORT>/login` (replace `<PORT>` with your chosen port) and sign in. After logging in, the dashboard
lets you manage up to 1000 bots.

Environment variables:

- `DB_PATH` – path to the SQLite file (default `bots.db`)
- `KICK_URI` – Kick WebSocket URI
- `WORKERS` – scheduler thread pool size
- `MAX_INSTANCES` – max concurrent jobs
- `SECRET_KEY` – session secret
- `PORT` – server port (default `5000`)
- `DEBUG` – set to `false` to disable Flask debug mode

## Bots

Each bot requires a Kick `auth_token` which can be obtained using `scripts/login_kick.py`. Bots belong to optional *groups* so you can trigger messages for multiple bots at once. Logs can be viewed per bot from the dashboard and you can start all bots or a single group via dashboard buttons.

When creating or editing a bot in the dashboard, leave the group field blank if you do not want the bot included in group actions.

## Scripts

- `scripts/add_bot.py` – create a bot via the API
- `scripts/run_bot.py` – run a standalone bot
- `scripts/login_kick.py` – retrieve a Kick auth token

## Testing

Run a quick smoke test to ensure the code compiles and the server starts:

```bash
python -m py_compile backend/app.py app/routes.py run.py \
    bots/bot_runner.py scripts/add_bot.py scripts/login_kick.py \
    scripts/run_bot.py shared/logger.py
python run.py & sleep 3; pkill -f run.py
```
