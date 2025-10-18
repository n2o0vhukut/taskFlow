from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .db import init_db, SessionLocal
from .services.tasks import (
    add_task,
    list_tasks,
    mark_done,
    remove_task,
    export_tasks_csv,
)
from .api import create_app


def _render_table(headers, rows) -> None:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))
    def fmt_row(values):
        return " ".join(str(v).ljust(widths[i]) for i, v in enumerate(values))
    print(fmt_row(headers))
    print(" ".join("-" * w for w in widths))
    for r in rows:
        print(fmt_row(r))


def cmd_init_db(args) -> int:
    init_db()
    print("DB initialized.")
    return 0


def cmd_add(args) -> int:
    with SessionLocal() as s:
        t = add_task(
            s,
            title=args.title,
            project=args.project,
            priority=args.priority,
            estimate_hours=args.est,
            due_date=args.due,
        )
        print(f"Added task #{t.id}: {t.title}")
    return 0


def cmd_list(args) -> int:
    with SessionLocal() as s:
        items = list_tasks(
            s, status=args.status, project=args.project, due_before=args.due_before
        )
        rows = [
            [
                t.id,
                t.title,
                t.project or "",
                t.priority,
                f"{t.estimate_hours:.1f}" if t.estimate_hours is not None else "",
                t.due_date.isoformat() if t.due_date else "",
                t.status,
            ]
            for t in items
        ]
        _render_table(
            ["id", "title", "project", "priority", "est", "due", "status"], rows
        )
    return 0


def cmd_done(args) -> int:
    with SessionLocal() as s:
        try:
            t = mark_done(s, args.task_id)
        except ValueError:
            print("Task not found", file=sys.stderr)
            return 1
        print(f"Task #{t.id} done.")
    return 0


def cmd_rm(args) -> int:
    with SessionLocal() as s:
        try:
            remove_task(s, args.task_id)
        except ValueError:
            print("Task not found", file=sys.stderr)
            return 1
        print(f"Task #{args.task_id} removed.")
    return 0


def cmd_export(args) -> int:
    if args.format != "csv":
        print("Only csv is supported in P0", file=sys.stderr)
        return 2
    with SessionLocal() as s:
        items = list_tasks(s, status=args.status, project=args.project)
        path = export_tasks_csv(items, args.out)
        print(f"Exported: {path}")
    return 0


def cmd_api(args) -> int:
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="taskflow", description="TaskFlow CLI")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("init-db", help="Initialize database")
    sp.set_defaults(func=cmd_init_db)

    sp = sub.add_parser("add", help="Add a task")
    sp.add_argument("--title", required=True)
    sp.add_argument("--project", default=None)
    sp.add_argument("--priority", default="M", choices=["H", "M", "L"]) 
    sp.add_argument("--est", type=float, default=None, help="estimate hours")
    sp.add_argument("--due", default=None, help="YYYY-MM-DD")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("list", help="List tasks")
    sp.add_argument("--status", default="todo", choices=["todo", "doing", "done", "all"]) 
    sp.add_argument("--project", default=None)
    sp.add_argument("--due-before", dest="due_before", default=None)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("done", help="Mark task done")
    sp.add_argument("task_id", type=int)
    sp.set_defaults(func=cmd_done)

    sp = sub.add_parser("rm", help="Remove task")
    sp.add_argument("task_id", type=int)
    sp.set_defaults(func=cmd_rm)

    sp = sub.add_parser("export", help="Export tasks")
    sp.add_argument("--format", default="csv")
    sp.add_argument("--out", required=True)
    sp.add_argument("--status", default="all", choices=["todo", "doing", "done", "all"]) 
    sp.add_argument("--project", default=None)
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("api", help="Run Flask API server")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=5000)
    sp.add_argument("--debug", action="store_true")
    sp.set_defaults(func=cmd_api)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
