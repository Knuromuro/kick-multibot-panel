import json
from datetime import datetime

import pytest

from backend.app import create_app, db, Group


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
