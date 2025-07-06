"""Entry point for the KickBot dashboard and API server."""

import os

from backend.app import create_app
from app.routes import register_web

app = create_app()
register_web(app)

if __name__ == '__main__':
    debug = os.getenv('DEBUG', 'true').lower() == 'true'
    port = int(os.getenv('PORT', '5000'))
    host = os.getenv('HOST', '0.0.0.0')
    try:
        app.run(host=host, port=port, debug=debug)
    except OSError as exc:
        if exc.errno == 98:  # Address already in use
            print(f"Port {port} in use, falling back to random port")
            app.run(host=host, port=0, debug=debug)
        else:
            raise
