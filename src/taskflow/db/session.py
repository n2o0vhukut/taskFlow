from __future__ import annotations

"""DB セッション/エンジンのセットアップ。

環境変数:
- TASKFLOW_DB_PATH: DBファイルのパス（相対可。未指定時は `./data/taskflow.db`）
- TASKFLOW_SQL_ECHO: SQL ログ出力を有効化（'1' / 'true' / 'True'）

提供物:
- `engine`: SQLAlchemy Engine（SQLite）
- `SessionLocal`: `with SessionLocal() as s:` で使うセッションファクトリ
- `Base`: declarative base（ORM モデルが継承）
"""

import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def _project_root() -> Path:
    """プロジェクトのルートディレクトリを推定して返す。"""
    # src/taskflow/db/session.py -> parents[3] == project root
    return Path(__file__).resolve().parents[3]


def get_db_path() -> Path:
    """DB ファイルパスを決定する。

    - `TASKFLOW_DB_PATH` があればそれを採用（相対ならプロジェクトルート基準）
    - なければ `./data/taskflow.db`（プロジェクト直下）を用意
    ディレクトリは必要なら作成する。
    """
    env = os.getenv("TASKFLOW_DB_PATH")
    if env:
        p = Path(env)
        if not p.is_absolute():
            p = _project_root() / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    default = _project_root() / "data" / "taskflow.db"
    default.parent.mkdir(parents=True, exist_ok=True)
    return default


DB_PATH = get_db_path()
SQL_ECHO = os.getenv("TASKFLOW_SQL_ECHO", "0") in {"1", "true", "True"}

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    future=True,  # 2.0 スタイルの動作
    echo=SQL_ECHO,  # SQL ログ
    connect_args={"check_same_thread": False},  # SQLite をマルチスレッドで使うための緩和
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()
