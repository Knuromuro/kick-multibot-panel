# Kick MultiBot Panel

This is a minimal management panel for Kick bots using Flask. Features include authentication, group and bot CRUD, websocket bot status updates, service worker for offline caching, Prometheus metrics, and a simple CI pipeline.

## Running

```bash
pip install -r requirements.txt
python app.py
```

Default admin credentials are `admin/admin`.

## Endpoints

- `POST /login` – authenticate and redirect to `/dashboard`.
- `/dashboard` – main UI (requires login).
- `POST /dashboard/api/groups` – create group.
- `POST /dashboard/api/bots` – create bot.
- `POST /dashboard/api/bots/<id>/start` – start bot.
- `POST /dashboard/api/bots/<id>/stop` – stop bot.
- `GET /dashboard/api/bots/<id>/status` – bot status.
- `/metrics` – Prometheus metrics.

## Tests

Run tests with:

```bash
pytest --cov=.
```

## CI

GitHub Actions run linting, tests, and Docker build on each push.
