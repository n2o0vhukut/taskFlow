from __future__ import annotations

"""検索ロジック（部分一致）。

title / project を対象に LIKE で部分一致検索を行うシンプルな実装。
大文字小文字の扱いは SQLite の照合順序に依存（既定はACCENT/CASE insensitiveではない）。
必要に応じて `ilike` や照合を拡張可能。
"""

from typing import List
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db.models import Task


def search_tasks(session: Session, q: str) -> List[Task]:
    """`q` を含む title / project を部分一致（LIKE）で検索して返す。"""
    pattern = f"%{q}%"
    stmt = select(Task).where(or_(Task.title.like(pattern), Task.project.like(pattern)))
    return list(session.scalars(stmt))
