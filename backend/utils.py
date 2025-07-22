from __future__ import annotations

from functools import wraps
from flask import current_app, session
from flask_jwt_extended import verify_jwt_in_request, get_jwt


def role_required(*roles):
    """Decorator to enforce roles on API routes."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if current_app.config.get("TESTING"):
                return fn(*args, **kwargs)
            if session.get("role") and session["role"] in roles:
                return fn(*args, **kwargs)
            verify_jwt_in_request()
            claims = get_jwt()
            if claims.get("role") not in roles:
                return {"msg": "forbidden"}, 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator
