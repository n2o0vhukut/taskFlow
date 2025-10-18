from __future__ import annotations
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
DB_PATH = BASE / "data" / "taskflow.db"

def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript('''
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  project TEXT,
  priority TEXT CHECK(priority IN ('H','M','L')) DEFAULT 'M',
  est_hours REAL DEFAULT 1.0,
  due DATE,
  status TEXT CHECK(status IN ('todo','doing','done','archived')) DEFAULT 'todo',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due);

CREATE TABLE IF NOT EXISTS checkins(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE NOT NULL,
  available_hours REAL,
  notes TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER,
  kind TEXT,  -- add/done/edit/note
  message TEXT,
  at DATETIME DEFAULT CURRENT_TIMESTAMP
);
''')
    conn.commit()
    conn.close()
