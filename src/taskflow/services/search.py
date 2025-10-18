from __future__ import annotations

from typing import List
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db.models import Task


def search_tasks(session: Session, q: str) -> List[Task]:
    pattern = f"%{q}%"
    stmt = select(Task).where(or_(Task.title.like(pattern), Task.project.like(pattern)))
    return list(session.scalars(stmt))

