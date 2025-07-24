import pytest
from backend import create_app
from backend.models import db
import bcrypt


@pytest.fixture
def auth_client(tmp_path):
    password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test.db",
            "SECRET_KEY": "test",
            "WTF_CSRF_ENABLED": False,
            "LOGIN_DISABLED": False,
            "TESTING": True,
            "ADMIN_PASSWORD_HASH": password_hash,
        }
    )
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client


def test_login_success(auth_client):
    res = auth_client.post("/login", data={"username": "admin", "password": "admin"})
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/dashboard")
    res2 = auth_client.get("/dashboard")
    assert res2.status_code == 200


def test_login_failure(auth_client):
    res = auth_client.post("/login", data={"username": "admin", "password": "bad"})
    assert res.status_code == 401


def test_dashboard_requires_login(tmp_path):
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/t.db",
            "SECRET_KEY": "t",
            "WTF_CSRF_ENABLED": False,
            "LOGIN_DISABLED": False,
            "TESTING": True,
        }
    )
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        res = client.get("/dashboard")
        assert res.status_code == 302
        assert res.headers["Location"].endswith("/login")


def test_api_requires_login(tmp_path):
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/t.db",
            "SECRET_KEY": "t",
            "WTF_CSRF_ENABLED": False,
            "LOGIN_DISABLED": False,
            "TESTING": True,
        }
    )
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        res = client.get("/dashboard/api/groups")
        assert res.status_code == 401
