from __future__ import annotations

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from marshmallow import Schema, fields


db = SQLAlchemy()


class Group(db.Model):
    __tablename__ = "groups"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False, index=True)
    target = db.Column(db.String(80), nullable=False, index=True)
    interval = db.Column(db.Integer, default=600)
    accounts = db.relationship("Account", backref="group", lazy=True)


class Account(db.Model):
    __tablename__ = "accounts"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(120), nullable=False)
    proxy = db.Column(db.String(200))
    messages_file = db.Column(db.String(200))
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False)


class Log(db.Model):
    __tablename__ = "logs"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    message = db.Column(db.String(200))


class SyncEvent(db.Model):
    """Event used for synchronizing state between clients."""

    __tablename__ = "sync_events"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    entity = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    payload = db.Column(db.JSON)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    synced = db.Column(db.Boolean, default=False)


class GroupSchema(Schema):
    name = fields.Str(required=True)
    target = fields.Str(required=True)
    interval = fields.Int(load_default=600)


class AccountSchema(Schema):
    username = fields.Str(required=True)
    password = fields.Str(required=True)
    proxy = fields.Str(load_default=None)
    messages_file = fields.Str(load_default=None)
    group_id = fields.Int(required=True)
