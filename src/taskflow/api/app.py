from __future__ import annotations

from flask import Flask

from ..db.session import get_db_path
from ..db.init import init_db
from .routes import bp as api_bp


def create_app() -> Flask:
    app = Flask(__name__)

    # Simple health-check config
    app.config["TASKFLOW_DB_PATH"] = str(get_db_path())

    # Initialize DB if not present
    init_db()

    # Register API routes
    app.register_blueprint(api_bp)

    @app.get("/health")
    def health():  # type: ignore
        return {"status": "ok"}

    return app

