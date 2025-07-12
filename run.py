"""Entry point for the KickBot dashboard and API server."""

import os

from backend.app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    debug = os.getenv('DEBUG', 'true').lower() == 'true'
    port = int(os.getenv('PORT', '5000'))
    host = os.getenv('HOST', '0.0.0.0')
    try:
        socketio.run(app, host=host, port=port, debug=debug)
    except OSError as exc:
        if exc.errno == 98:  # Address already in use
            print(f"Port {port} in use, falling back to random port")
            socketio.run(app, host=host, port=0, debug=debug)
        else:
            raise
