import os
from pathlib import Path

import pytest

from taskflow.api import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "api_test.db"
    monkeypatch.setenv("TASKFLOW_DB_PATH", str(db))
    app = create_app()
    return app.test_client()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_tasks_crud_and_search(client):
    # Create
    r = client.post(
        "/tasks",
        json={
            "title": "統計検定 過去問3セット",
            "project": "資格",
            "priority": "H",
            "estimate_hours": 2.0,
            "due_date": "2025-10-25",
        },
    )
    assert r.status_code == 201
    tid = r.get_json()["id"]

    # Get list
    r = client.get("/tasks")
    assert r.status_code == 200
    assert len(r.get_json()) >= 1

    # Get by id
    r = client.get(f"/tasks/{tid}")
    assert r.status_code == 200

    # Patch
    r = client.patch(f"/tasks/{tid}", json={"status": "done"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "done"

    # Search
    r = client.post("/search", json={"q": "統計"})
    assert r.status_code == 200
    assert any("統計" in x["title"] for x in r.get_json())

    # Webhook
    r = client.post("/webhooks/events", json={"event": "test"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "received"

    # Chat dummy
    r = client.post("/chat/completions", json={"messages": [{"role": "user", "content": "ping"}]})
    assert r.status_code == 200
    data = r.get_json()
    assert data["choices"][0]["message"]["content"].startswith("echo:")

    # Delete
    r = client.delete(f"/tasks/{tid}")
    assert r.status_code == 204

