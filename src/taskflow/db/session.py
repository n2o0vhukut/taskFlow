from __future__ import annotations

import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def _project_root() -> Path:
    # src/taskflow/db/session.py -> parents[3] == project root
    return Path(__file__).resolve().parents[3]


def get_db_path() -> Path:
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
    future=True,
    echo=SQL_ECHO,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

