# Kick Multibot Panel

This project provides a simple dashboard and backend for managing multiple Kick.com chat bots.

## Backend

- Python Flask application
- SQLite database using SQLAlchemy
- APScheduler for periodic messages
- Async WebSocket client for sending messages to Kick

Run the backend:
```
python backend/app.py
```

## Frontend

Open `frontend/index.html` in your browser. It communicates with the backend via REST endpoints.
