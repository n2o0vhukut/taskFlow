from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Task


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return date.fromisoformat(str(s))


def add_task(
    session: Session,
    *,
    title: str,
    project: Optional[str] = None,
    priority: Optional[str] = None,
    estimate_hours: Optional[float] = None,
    due_date: Optional[str] = None,
) -> Task:
    p = (priority or "M").upper()
    if p not in {"H", "M", "L"}:
        p = "M"
    t = Task(
        title=title,
        project=project,
        priority=p,
        estimate_hours=estimate_hours,
        due_date=_parse_date(due_date),
        status="todo",
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def list_tasks(
    session: Session,
    *,
    status: Optional[str] = None,
    project: Optional[str] = None,
    due_before: Optional[str] = None,
) -> List[Task]:
    stmt = select(Task)
    if status and status != "all":
        stmt = stmt.where(Task.status == status)
    if project:
        stmt = stmt.where(Task.project == project)
    if due_before:
        stmt = stmt.where(Task.due_date != None).where(  # noqa: E711
            Task.due_date <= _parse_date(due_before)
        )
    stmt = stmt.order_by(Task.due_date.is_(None), Task.due_date.asc(), Task.id.asc())
    return list(session.scalars(stmt))


def get_task(session: Session, task_id: int) -> Optional[Task]:
    return session.get(Task, task_id)


def mark_done(session: Session, task_id: int) -> Task:
    t = session.get(Task, task_id)
    if not t:
        raise ValueError("Task not found")
    t.status = "done"
    session.commit()
    session.refresh(t)
    return t


def remove_task(session: Session, task_id: int) -> None:
    t = session.get(Task, task_id)
    if not t:
        raise ValueError("Task not found")
    session.delete(t)
    session.commit()


def update_task(
    session: Session,
    task_id: int,
    **fields,
) -> Task:
    t = session.get(Task, task_id)
    if not t:
        raise ValueError("Task not found")
    if "priority" in fields and fields["priority"]:
        p = str(fields["priority"]).upper()
        if p in {"H", "M", "L"}:
            t.priority = p
    if "title" in fields and fields["title"]:
        t.title = str(fields["title"])  # type: ignore
    if "project" in fields:
        t.project = fields["project"]
    if "estimate_hours" in fields:
        t.estimate_hours = (
            None if fields["estimate_hours"] is None else float(fields["estimate_hours"])  # type: ignore
        )
    if "due_date" in fields:
        t.due_date = _parse_date(fields["due_date"]) if fields["due_date"] else None
    if "status" in fields and fields["status"]:
        st = str(fields["status"]).lower()
        if st in {"todo", "doing", "done"}:
            t.status = st
    session.commit()
    session.refresh(t)
    return t


def export_tasks_csv(tasks: Sequence[Task], out_path: str) -> str:
    import csv
    from pathlib import Path

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "id",
                "title",
                "project",
                "priority",
                "estimate_hours",
                "due_date",
                "status",
                "created_at",
                "updated_at",
            ]
        )
        for t in tasks:
            w.writerow(
                [
                    t.id,
                    t.title,
                    t.project or "",
                    t.priority,
                    t.estimate_hours if t.estimate_hours is not None else "",
                    t.due_date.isoformat() if t.due_date else "",
                    t.status,
                    t.created_at.isoformat() if t.created_at else "",
                    t.updated_at.isoformat() if t.updated_at else "",
                ]
            )
    return str(p)

