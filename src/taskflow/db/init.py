from __future__ import annotations

from sqlalchemy import text

from .session import Base, engine
from . import models  # noqa: F401 - ensure models are imported


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # Minimal compatibility upgrade for existing SQLite DBs from pre-P0
    with engine.begin() as conn:
        try:
            cols = conn.execute(text("PRAGMA table_info('tasks')")).all()
            present = {c[1] for c in cols}  # type: ignore[index]
            alters = []
            if "estimate_hours" not in present:
                alters.append("ALTER TABLE tasks ADD COLUMN estimate_hours REAL NULL")
            if "due_date" not in present:
                alters.append("ALTER TABLE tasks ADD COLUMN due_date DATE NULL")
            if "status" not in present:
                alters.append(
                    "ALTER TABLE tasks ADD COLUMN status TEXT NOT NULL DEFAULT 'todo'"
                )
            for stmt in alters:
                conn.execute(text(stmt))
        except Exception:
            # Best-effort; safe to ignore for fresh DBs or non-SQLite engines
            pass
