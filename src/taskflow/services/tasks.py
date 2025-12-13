from __future__ import annotations

"""タスクに関するビジネスロジック（サービス層）。

CLI や API 層から呼び出される純粋な処理を提供する。
ここでは SQLAlchemy の `Session` を受け取り、副作用（DB へのコミット）を伴う。

提供関数（主なもの）:
- add_task / list_tasks / get_task / update_task / mark_done / remove_task
- export_tasks_csv: 一覧をCSVに書き出すユーティリティ
"""

from datetime import date, datetime
from typing import Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Task


def _parse_date(s: Optional[str]) -> Optional[date]:
    """`YYYY-MM-DD` 形式の文字列を `date` に変換（未指定なら None）。"""
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
    """タスクを新規作成して永続化する。

    - `priority` は H/M/L のいずれかに正規化（不正値は既定の 'M'）
    - `due_date` は ISO 形式（YYYY-MM-DD）を受け取り `date` へ変換
    - `status` は既定で 'todo'
    生成後に `commit()` と `refresh()` を行い、ID 等を反映したインスタンスを返す。
    """
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
    """条件でタスクを絞り込み、日付とIDで整列して返す。

    - `status`: 'todo'/'doing'/'done' または 'all'（指定なし/`all` はフィルタ無し）
    - `project`: 完全一致でフィルタ
    - `due_before`: 期日の上限（当日含む、ISO日付）。NULLは対象外。
    並び順は「期日あり → 期日なし」の順で、期日昇順、同日内ではID昇順。
    """
    stmt = select(Task)
    if status and status != "all":
        stmt = stmt.where(Task.status == status)
    if project:
        stmt = stmt.where(Task.project == project)
    if due_before:
        # None の期日は比較できないため、まず NOT NULL を条件に含める
        stmt = stmt.where(Task.due_date != None).where(  # noqa: E711
            Task.due_date <= _parse_date(due_before)
        )
    # 期日無しを最後へ送る → 期日昇順 → ID昇順
    stmt = stmt.order_by(Task.due_date.is_(None), Task.due_date.asc(), Task.id.asc())
    return list(session.scalars(stmt))


def get_task(session: Session, task_id: int) -> Optional[Task]:
    """ID で単一タスクを取得（見つからなければ None）。"""
    return session.get(Task, task_id)


def mark_done(session: Session, task_id: int) -> Task:
    """タスクを 'done' に更新。対象が無ければ `ValueError`。"""
    t = session.get(Task, task_id)
    if not t:
        raise ValueError("Task not found")
    t.status = "done"
    session.commit()
    session.refresh(t)
    return t


def remove_task(session: Session, task_id: int) -> None:
    """タスクを削除。対象が無ければ `ValueError`。"""
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
    """タスクを部分更新して返す。対象が無ければ `ValueError`。

    受け付けるフィールド（キー）:
    - `priority`: 'H'/'M'/'L' のみ反映（それ以外は無視）
    - `title`: 非空時に更新
    - `project`: None も可（プロジェクト解除）
    - `estimate_hours`: None または float へ変換して更新
    - `due_date`: ISO 文字列（空や None は期日解除）
    - `status`: 'todo'/'doing'/'done' のみ反映
    更新後は commit + refresh を行う。
    """
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
    """タスク一覧を CSV へ出力し、ファイルパスを返す。

    - 親ディレクトリが無ければ作成
    - 文字コードは UTF-8、改行はプラットフォーム既定（`newline=""`）
    - None 値は空文字として出力
    """
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
