import os
from pathlib import Path

import pytest

from taskflow.cli import main as cli_main


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("TASKFLOW_DB_PATH", str(db))
    return db


def test_cli_basic_flow(tmp_db, capsys):
    assert cli_main(["init-db"]) == 0
    assert cli_main([
        "add",
        "--title",
        "SKY案件 APIテスト実施",
        "--due",
        "2025-10-20",
        "--est",
        "1.5",
        "--project",
        "業務",
        "--priority",
        "M",
    ]) == 0
    out = capsys.readouterr().out
    assert "Added task #" in out

    assert cli_main(["list"]) == 0
    out = capsys.readouterr().out
    assert "title" in out

    assert cli_main(["done", "1"]) in (0, 1)
    assert cli_main(["export", "--format", "csv", "--out", str(tmp_db.with_suffix(".csv"))]) == 0

