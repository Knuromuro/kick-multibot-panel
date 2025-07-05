# Kick Multibot Panel

This project provides a simple dashboard and backend for managing multiple Kick.com chat bots.
It is designed to support up to **1000** configured bots on a single instance.

## Backend

- Python Flask application
- SQLite database using SQLAlchemy
- APScheduler for periodic messages
- Async WebSocket client for sending messages to Kick

Run the backend (schedules existing bots automatically):
```
python backend/app.py
```

## Frontend

Open `frontend/index.html` in your browser. It communicates with the backend via REST endpoints and auto-refreshes bot and log lists every few seconds.

### Features
- Create, edit, toggle and delete bots
- Manual and scheduled message sending with reconnecting WebSocket client
- View recent logs globally or per bot
- Dashboard supports up to 1000 scheduled bots
