from __future__ import annotations

"""Flask アプリケーションファクトリ。

責務:
- DB の初期化（未作成時の create_all と簡易 ALTER）
- 設定値（`TASKFLOW_DB_PATH`）の露出（/health 用の簡易確認にも利用）
- API ルート（Blueprint）の登録

運用時は本開発サーバではなく、Gunicorn/Uvicorn 等のWSGI/ASGIサーバを利用する想定。
"""

from flask import Flask

from ..db.session import get_db_path
from ..db.init import init_db
from .routes import bp as api_bp


def create_app() -> Flask:
    """Flask アプリを構築して返す。"""
    app = Flask(__name__)

    # Simple health-check config
    app.config["TASKFLOW_DB_PATH"] = str(get_db_path())

    # Initialize DB if not present
    init_db()

    # Register API routes
    app.register_blueprint(api_bp)

    @app.get("/health")
    def health():  # type: ignore
        """簡易ヘルスチェック。"""
        return {"status": "ok"}

    return app
