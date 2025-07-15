# KickBot Manager

KickBot Manager is a lightweight dashboard for controlling chat bots on [Kick.com](https://kick.com). It combines a Flask backend with a simple Tailwind based frontend. Bots connect to Kick chat via WebSocket and can be scheduled or commanded from the web panel.

## Features

- Manage groups and accounts stored in a SQLite database
- Start an asynchronous scheduler that sends messages from accounts to their group's target
- Issue commands to running bots: send a message, check status, restart connection or capture a screenshot
- View the last 50 log lines per bot
- Search and filter bots or groups right from the dashboard
- Dark mode toggle and offline indicator

## Setup

Install dependencies and start the server:

```bash
pip install -r requirements.txt
# start both the API and dashboard
python run.py
```

By default the dashboard uses JWT authentication. Login at `/login` and the page
will store access and refresh tokens in `localStorage`. Tokens are automatically
refreshed when API requests return `401 Unauthorized`.

If `TOTP_SECRET` is set, the login form will ask for a time based one time
password.

Obtain an access token via:

```bash
curl -X POST http://localhost:5000/auth/token -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin","totp":"<code>"}'
```

Use the returned `access_token` in the `Authorization` header as `Bearer <token>` for API calls.

The dashboard is a PWA. A service worker caches pages and API responses and uses
Background Sync to POST queued actions to `/sync/push` when connectivity
returns. Click the **Sync Now** button to force a flush while offline.

Run the tests (including a headless browser end-to-end check):

```bash
PYTHONPATH=. pytest -q
```
The end-to-end test uses Selenium with headless Chrome. Ensure `chromedriver`
is installed and available on the system path when running tests.

The panel uses CSRF protection. A token is included in a `<meta>` tag and
automatically sent with API requests by `main.js`.
Newly created groups and accounts now appear on the dashboard immediately.

### API endpoints

- `POST /dashboard/api/groups` – create a group
- `POST /dashboard/api/accounts` – create an account
- `POST /dashboard/api/bots/<id>/start` – start a bot
- `POST /dashboard/api/bots/<id>/stop` – stop a bot
- `GET  /dashboard/api/bots/<id>/status` – check if a bot is running

### Docker

Run with PostgreSQL and Redis using Docker Compose:

```bash
docker-compose up --build
```

For Kubernetes deployments a basic Helm chart is provided under `helm/kickbot`:

```bash
helm install kickbot helm/kickbot
```

### Documentation

The API exposes OpenAPI docs at `/docs`. Developer documentation can be served with `mkdocs serve`.

During development you can also run the backend module directly:

```bash
python backend/app.py
```

Login at `http://localhost:5000/login` with **admin/admin**. If `TOTP_SECRET` is
set, provide the current one-time password.

### Environment variables

Configuration values are loaded from `.env` via `shared.config`. The most
important variables are:

- `PORT` – server port (default 5000)
- `DB_PATH` – SQLite file (default `bots.db`)
- `SECRET_KEY` – Flask secret key
- `WORKERS` – scheduler thread pool size (default 50)
- `MAX_INSTANCES` – maximum concurrent scheduled jobs (default 50)
- `KICK_WS_URI` – WebSocket endpoint for Kick chat
- `REDIS_URL` – Redis connection string for task queue and caching
- `JWT_SECRET_KEY` – secret used to sign access tokens
- `TOTP_SECRET` – base32 secret for two factor login
- `SENTRY_DSN` – optional Sentry endpoint for error reporting
- `SLACK_WEBHOOK` – webhook URL for Slack alerts
- `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` – credentials for Telegram alerts

The backend exposes Prometheus metrics at `/metrics` and uses Redis + RQ for background jobs.
It also provides `/sync/pull` and `/sync/push` for two-way event synchronization.
Errors can optionally be reported to Sentry or Slack/Telegram via the environment
variables `SENTRY_DSN`, `SLACK_WEBHOOK`, `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`.

## Usage

1. Create a group with a target channel and interval.
   Group names must be unique; duplicate names will return an error.
2. Add accounts pointing to that group. Each account may specify a messages file with text to send.
3. Click **Start Scheduler** to begin automated sending. Bots run in batches and reconnect on failure.
4. Use the command button next to a bot to send manual messages or request a screenshot.

Logs are stored under `logs/` with one file per bot.

The dashboard is a Progressive Web App and can be installed on mobile. It uses WebSocket updates and push notifications when bots start or stop. Offline changes are queued locally and synchronized once connectivity returns.

### Mobile screenshots

Below is an example of the mobile layout. The sidebar collapses into a hamburger menu and all controls remain accessible.

![dashboard mobile](docs/index.md)
