import os
import json

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import app, db, User, cache

def setup_module(module):
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['CACHE_TYPE'] = 'SimpleCache'
    cache.init_app(app)
    with app.app_context():
        db.create_all()
        db.session.add(User(username='test', password='test'))
        db.session.commit()


def test_login_and_dashboard():
    client = app.test_client()
    resp = client.post('/login', data={'username': 'test', 'password': 'test'})
    assert resp.status_code == 302
    resp = client.get('/dashboard')
    assert resp.status_code == 200


def test_create_group():
    client = app.test_client()
    client.post('/login', data={'username': 'test', 'password': 'test'})
    resp = client.post('/dashboard/api/groups', json={'name': 'g1'})
    assert resp.status_code == 201
    data = json.loads(resp.data)
    assert data['name'] == 'g1'


def test_start_stop_bot():
    client = app.test_client()
    client.post('/login', data={'username': 'test', 'password': 'test'})
    resp = client.post('/dashboard/api/groups', json={'name': 'g1'})
    gid = resp.get_json()['id']
    resp = client.post('/dashboard/api/bots', json={'name': 'b1', 'group_id': gid})
    bid = resp.get_json()['id']
    resp = client.post(f'/dashboard/api/bots/{bid}/start')
    assert resp.status_code == 200
    resp = client.post(f'/dashboard/api/bots/{bid}/stop')
    assert resp.status_code == 200
