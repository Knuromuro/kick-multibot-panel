from flask_caching import Cache
import os
from flask import Flask

cache = Cache()


def init_cache(app: Flask | None = None):
    config = {
        'CACHE_TYPE': 'RedisCache',
        'CACHE_REDIS_URL': os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    }
    if app:
        for key, value in config.items():
            app.config.setdefault(key, value)
        cache.init_app(app)
    else:
        dummy = Flask('cache')
        dummy.config.update(config)
        cache.init_app(dummy)


init_cache()
