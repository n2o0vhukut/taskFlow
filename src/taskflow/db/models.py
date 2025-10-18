from __future__ import annotations

from datetime import datetime, date
from typing import Optional
from sqlalchemy import String, Integer, Date, DateTime, CheckConstraint, Float, func
from sqlalchemy.orm import Mapped, mapped_column

from .session import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    project: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    priority: Mapped[str] = mapped_column(String(1), nullable=False, default="M")
    estimate_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="todo")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("priority in ('H','M','L')", name="ck_tasks_priority"),
        CheckConstraint("status in ('todo','doing','done')", name="ck_tasks_status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "project": self.project,
            "priority": self.priority,
            "estimate_hours": self.estimate_hours,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

