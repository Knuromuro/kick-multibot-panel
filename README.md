# KickBot Manager

KickBot Manager is a Flask-based dashboard for running chat bots on [Kick.com](https://kick.com). It controls Selenium bots that connect to Kick chat via WebSocket and lets you manage groups of accounts, schedule messages and view logs in real time. If Redis is unavailable the app falls back to an in-memory queue so bots continue to run.

## Architecture

- **backend/** – Flask API, SQLAlchemy models and APScheduler jobs
- **bots/** – Selenium bot runner and helpers
- **app/templates** & **app/static** – Tailwind dashboard and JavaScript logic
- **shared/** – configuration loader, caching and logging utilities

Bots belong to `Account` records which are linked to a `Group`. Each group has a target channel and interval for sending messages.

## Installation & Setup

Requirements:
- Python 3.10+
- Google Chrome and chromedriver
- Redis (optional)

```bash
git clone <repo>
cd kick-multibot-panel
pip install -r requirements.txt
```

Create a `.env` file based on `.env.example` and set values like `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL` and Kick credentials.

## Running the Application

Start the server in development mode:

```bash
python run.py
```

Visit `http://127.0.0.1:5000/dashboard` to log in and use the panel.

For production use a WSGI server such as Gunicorn behind Nginx or run the provided Docker container.

## Using the Dashboard

1. Log in with the admin credentials or via OAuth if configured.
2. Create a **group** with a target channel and sending interval.
3. Add **accounts** to the group.
4. Start the scheduler or individual bots using the buttons on the page.
5. View live logs and bot status. Search boxes filter groups and bots without errors when empty.

## API Endpoints

- `GET /dashboard/api/groups` – list groups
- `POST /dashboard/api/groups` – create a group
- `GET /dashboard/api/accounts` – list accounts
- `POST /dashboard/api/accounts` – create an account
- `GET /dashboard/api/bots` – list bots
- `POST /dashboard/api/bots/<id>/start` – start a bot
- `POST /dashboard/api/bots/<id>/stop` – stop a bot
- `GET /dashboard/api/bots/<id>/logs` – recent log lines

## Redis Fallback

Redis is optional. When Redis cannot be reached the server logs a warning only once and runs scheduled tasks inline. Pending sync events are written to `sync_fallback.jsonl` and replayed once Redis is back online.

## Security & Best Practices

- Login returns JWTs which the dashboard stores in HttpOnly cookies.
- Requests are rate limited and protected by CSRF.
- Store hashed passwords in environment variables instead of plain text.

## Future Improvements

- Scale to thousands of bots
- Better CAPTCHA handling during login
- More detailed UI feedback and metrics

## Quick Start for New Developers

```bash
pip install -r requirements.txt
python run.py
```

Open your browser at `http://127.0.0.1:5000/dashboard` and start creating groups and bots.
