import json
import pytest

from backend.app import create_app, db


@pytest.fixture
def client(tmp_path):
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path}/test.db',
        'CACHE_TYPE': 'SimpleCache'
    })
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client


def test_create_group(client):
    res = client.post('/dashboard/api/groups', json={
        'name': 'grp',
        'target': 'chan',
        'interval': 60
    })
    assert res.status_code == 201
    gid = res.get_json()['id']

    res = client.get('/dashboard/api/groups')
    assert res.status_code == 200
    assert any(g['id'] == gid for g in res.get_json())

    # duplicate name should fail
    res = client.post('/dashboard/api/groups', json={
        'name': 'grp',
        'target': 'chan2'
    })
    assert res.status_code == 400


def test_create_account(client):
    gid = client.post('/dashboard/api/groups', json={'name': 'g2', 'target': 't'}).get_json()['id']
    res = client.post('/dashboard/api/accounts', json={
        'username': 'user',
        'password': 'pass',
        'group_id': gid
    })
    assert res.status_code == 201
    aid = res.get_json()['id']

    res = client.get('/dashboard/api/accounts')
    assert any(a['id'] == aid for a in res.get_json())

