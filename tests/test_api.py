import pytest
import bcrypt

from backend import create_app
from backend.models import db


@pytest.fixture
def client(tmp_path):
    password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test.db",
            "CACHE_TYPE": "SimpleCache",
            "ADMIN_PASSWORD_HASH": password_hash,
        }
    )
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client


def test_create_group(client):
    res = client.post(
        "/dashboard/api/groups", json={"name": "grp", "target": "chan", "interval": 60}
    )
    assert res.status_code == 201
    gid = res.get_json()["id"]

    res = client.get("/dashboard/api/groups")
    assert res.status_code == 200
    data = res.get_json()
    assert any(g["id"] == gid for g in data["items"]) and data["total"] == 1

    res = client.get("/dashboard/api/groups?search=grp")
    assert res.get_json()["total"] == 1

    # duplicate name should fail
    res = client.post("/dashboard/api/groups", json={"name": "grp", "target": "chan2"})
    assert res.status_code == 400


def test_create_account(client):
    gid = client.post(
        "/dashboard/api/groups", json={"name": "g2", "target": "t"}
    ).get_json()["id"]
    res = client.post(
        "/dashboard/api/accounts",
        json={"username": "user", "password": "pass", "group_id": gid},
    )
    assert res.status_code == 201
    aid = res.get_json()["id"]

    res = client.get("/dashboard/api/accounts")
    data = res.get_json()
    assert any(a["id"] == aid for a in data["items"]) and data["total"] == 1

    # creating via /bots endpoint
    res = client.post(
        "/dashboard/api/bots",
        json={"username": "userb", "password": "pass", "group_id": gid},
    )
    assert res.status_code == 201

    # invalid group
    res = client.post(
        "/dashboard/api/accounts",
        json={"username": "bad", "password": "p", "group_id": 9999},
    )
    assert res.status_code == 400


def test_stats_endpoint(client):
    res = client.get("/dashboard/api/stats")
    assert res.status_code == 200
    data = res.get_json()
    assert "runs" in data and "errors" in data


def test_metrics_and_auth(client):
    res = client.post(
        "/auth/token",
        json={"username": "admin", "password": "admin", "totp": "123456"},
    )
    assert res.status_code == 200
    token = res.get_json()["access_token"]
    assert token
    metrics = client.get("/metrics")
    assert metrics.status_code == 200


def test_bot_start_stop(client, tmp_path):
    gid = client.post(
        "/dashboard/api/groups", json={"name": "g3", "target": "t"}
    ).get_json()["id"]
    aid = client.post(
        "/dashboard/api/accounts",
        json={"username": "user2", "password": "pass", "group_id": gid},
    ).get_json()["id"]

    res = client.post(f"/dashboard/api/bots/{aid}/start")
    assert res.status_code == 200
    assert "pid" in res.get_json()

    res = client.get(f"/dashboard/api/bots/{aid}/status")
    assert res.status_code == 200

    res = client.post(f"/dashboard/api/bots/{aid}/stop")
    assert res.status_code == 200
