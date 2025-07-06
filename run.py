import os

from backend.app import create_app
from app.routes import register_web

app = create_app()
register_web(app)

if __name__ == '__main__':
    debug = os.getenv('DEBUG', 'true').lower() == 'true'
    port = int(os.getenv('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=debug)
