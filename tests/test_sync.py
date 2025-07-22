import json
from datetime import datetime

import pytest

from backend import create_app
from backend.models import db, Group


@pytest.fixture
def client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test.db",
            "CACHE_TYPE": "SimpleCache",
        }
    )
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client


def test_sync_pull_push(client):
    # create group -> generates sync event
    client.post("/dashboard/api/groups", json={"name": "g", "target": "t"})
    res = client.get("/sync/pull")
    events = res.get_json()["events"]
    assert len(events) == 1
    evt_id = events[0]["event_id"]
    # subsequent pull should be empty
    assert client.get("/sync/pull").get_json()["events"] == []

    # push event back
    event = {
        "event_id": "new" + evt_id,
        "entity": "group",
        "action": "create",
        "payload": {"name": "p", "target": "c"},
        "timestamp": datetime.utcnow().isoformat(),
    }
    res = client.post(
        "/sync/push", data=json.dumps([event]), content_type="application/json"
    )
    assert res.status_code == 200
    assert Group.query.filter_by(name="p").count() == 1


def test_sync_idempotent(client):
    event = {
        "event_id": "same",
        "entity": "group",
        "action": "create",
        "payload": {"name": "g2", "target": "t"},
        "timestamp": datetime.utcnow().isoformat(),
    }
    client.post("/sync/push", json=[event])
    client.post("/sync/push", json=[event])
    assert Group.query.filter_by(name="g2").count() == 1


def test_sync_fallback(tmp_path, monkeypatch):
    recorded = []

    def capture_add_job(func, *a, **kw):
        recorded.append(func)
        return original_add_job(func, *a, **kw)

    from backend import scheduler as backend_app

    original_add_job = backend_app.sched.add_job
    monkeypatch.setattr(backend_app.sched, "add_job", capture_add_job)
    monkeypatch.setattr(
        backend_app,
        "Timer",
        lambda t, f: type("T", (), {"start": lambda self=None: None})(),
    )

    fb = tmp_path / "fb.jsonl"
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/db.sqlite",
            "CACHE_TYPE": "SimpleCache",
            "SYNC_FALLBACK_FILE": str(fb),
        }
    )

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        client.post("/dashboard/api/groups", json={"name": "g3", "target": "t"})

        job = backend_app.sched.get_job("sync_sender")
        enqueue = job.func if job else recorded[0]

        monkeypatch.setattr(
            backend_app.queue,
            "enqueue",
            lambda *a, **k: (_ for _ in ()).throw(backend_app.RedisConnError()),
        )
        with app.app_context():
            enqueue()

        monkeypatch.setattr(backend_app.queue, "enqueue", lambda *a, **k: None)
        monkeypatch.setattr(backend_app.redis_conn, "ping", lambda: True)
        with app.app_context():
            enqueue()
