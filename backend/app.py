"""Backward compatibility module for KickBot Manager."""

from . import create_app, api, jwt, csrf, limiter, talisman, sched, socketio, db

__all__ = [
    "create_app",
    "api",
    "jwt",
    "csrf",
    "limiter",
    "talisman",
    "sched",
    "socketio",
    "db",
]
