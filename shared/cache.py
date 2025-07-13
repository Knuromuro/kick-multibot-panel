from flask_caching import Cache
import os
from flask import Flask

cache = Cache()


def init_cache(app: Flask | None = None) -> None:
    """Initialize Flask-Caching.

    Uses Redis when ``REDIS_URL`` is defined, otherwise falls back to
    ``SimpleCache`` so the application can run without Redis.
    """
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        config = {
            "CACHE_TYPE": "RedisCache",
            "CACHE_REDIS_URL": redis_url,
        }
    else:
        config = {"CACHE_TYPE": "SimpleCache"}

    if app is None:
        dummy = Flask("cache")
        dummy.config.update(config)
        cache.init_app(dummy)
    else:
        for key, value in config.items():
            app.config.setdefault(key, value)
        cache.init_app(app)


init_cache()
