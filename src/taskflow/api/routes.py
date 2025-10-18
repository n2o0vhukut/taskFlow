from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from ..db import SessionLocal
from ..services.tasks import (
    add_task,
    get_task,
    list_tasks,
    remove_task,
    update_task,
)
from ..services.search import search_tasks
from ..services.chat import echo_completion


bp = Blueprint("api", __name__)


def _json_error(code: int, message: str):
    return jsonify({"error": message}), code


@bp.get("/tasks")
def get_tasks():  # type: ignore
    status = request.args.get("status")
    project = request.args.get("project")
    due_before = request.args.get("due_before")
    with SessionLocal() as s:
        items = list_tasks(s, status=status, project=project, due_before=due_before)
        return jsonify([t.to_dict() for t in items])


@bp.post("/tasks")
def create_task():  # type: ignore
    data = request.get_json(silent=True) or {}
    title = data.get("title")
    if not title:
        return _json_error(400, "title is required")
    with SessionLocal() as s:
        t = add_task(
            s,
            title=title,
            project=data.get("project"),
            priority=data.get("priority"),
            estimate_hours=data.get("estimate_hours"),
            due_date=data.get("due_date"),
        )
        return jsonify(t.to_dict()), 201


@bp.get("/tasks/<int:task_id>")
def get_task_by_id(task_id: int):  # type: ignore
    with SessionLocal() as s:
        t = get_task(s, task_id)
        if not t:
            return _json_error(404, "not found")
        return jsonify(t.to_dict())


@bp.patch("/tasks/<int:task_id>")
def patch_task(task_id: int):  # type: ignore
    data = request.get_json(silent=True) or {}
    with SessionLocal() as s:
        try:
            t = update_task(s, task_id, **data)
        except ValueError:
            return _json_error(404, "not found")
        return jsonify(t.to_dict())


@bp.delete("/tasks/<int:task_id>")
def delete_task(task_id: int):  # type: ignore
    with SessionLocal() as s:
        try:
            remove_task(s, task_id)
        except ValueError:
            return _json_error(404, "not found")
        return ("", 204)


@bp.post("/search")
def search():  # type: ignore
    data = request.get_json(silent=True) or {}
    q = data.get("q")
    if not q:
        return _json_error(400, "q is required")
    with SessionLocal() as s:
        items = search_tasks(s, q)
        return jsonify([t.to_dict() for t in items])


@bp.post("/webhooks/events")
def webhooks_events():  # type: ignore
    payload = request.get_json(silent=True) or {}
    # Append to simple log file in data/
    try:
        log_dir = Path(__file__).resolve().parents[3] / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "webhooks_events.log"
        entry = {
            "received_at": datetime.utcnow().isoformat() + "Z",
            "payload": payload,
        }
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return jsonify({"status": "received"})


@bp.post("/chat/completions")
def chat_completions():  # type: ignore
    data = request.get_json(silent=True) or {}
    return jsonify(echo_completion(data))

