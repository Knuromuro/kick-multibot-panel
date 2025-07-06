from backend.app import create_app
from app.routes import register_web

app = create_app()
register_web(app)

if __name__ == '__main__':
    app.run(debug=True)
