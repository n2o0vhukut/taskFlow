from __future__ import annotations

"""
TaskFlow CLI
=================

argparse ベースのシンプルな CLI 実装です。

責務:
- 引数/サブコマンドを解釈し、サービス層を呼び出す
- 標準出力に結果を表示し、終了コードで成否を表す

主なサブコマンド:
- init-db: DB 初期化
- add: タスク追加
- list: タスク一覧
- done: タスクを完了状態へ
- rm: タスク削除
- export: タスクを CSV へ出力
- api: Flask API サーバの起動
"""

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
    """幅揃えした簡易テーブルを標準出力へ描画する。

    - `headers`: ヘッダ行（文字列の配列）
    - `rows`: データ行（各行は配列）

    列ごとの最大幅を計算し、左寄せで整形する。
    """
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt_row(values):
        return " ".join(str(v).ljust(widths[i]) for i, v in enumerate(values))

    # ヘッダ + 罫線
    print(fmt_row(headers))
    print(" ".join("-" * w for w in widths))
    # 本文
    for r in rows:
        print(fmt_row(r))


def cmd_init_db(args) -> int:
    """DB を初期化するサブコマンドの実体。

    成功時は 0 を返す。
    """
    init_db()
    print("DB initialized.")
    return 0


def cmd_add(args) -> int:
    """タスクを1件追加する。

    `--title` は必須。`--project`/`--priority`/`--est`/`--due` は任意。
    """
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
    """タスクの一覧を表示する。

    フィルタ: `--status`, `--project`, `--due-before`。
    """
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
    """指定IDのタスクを done にする。

    見つからない場合は標準エラーに出力し、終了コード 1。
    """
    with SessionLocal() as s:
        try:
            t = mark_done(s, args.task_id)
        except ValueError:
            print("Task not found", file=sys.stderr)
            return 1
        print(f"Task #{t.id} done.")
    return 0


def cmd_rm(args) -> int:
    """指定IDのタスクを削除する。

    見つからない場合は終了コード 1。
    """
    with SessionLocal() as s:
        try:
            remove_task(s, args.task_id)
        except ValueError:
            print("Task not found", file=sys.stderr)
            return 1
        print(f"Task #{args.task_id} removed.")
    return 0


def cmd_export(args) -> int:
    """タスクをファイルへエクスポートする（現状は CSV のみ）。

    未対応フォーマットを指定した場合は終了コード 2。
    """
    if args.format != "csv":
        print("Only csv is supported in P0", file=sys.stderr)
        return 2
    with SessionLocal() as s:
        items = list_tasks(s, status=args.status, project=args.project)
        path = export_tasks_csv(items, args.out)
        print(f"Exported: {path}")
    return 0


def cmd_api(args) -> int:
    """Flask API サーバを起動する。

    `--host`/`--port`/`--debug` をそのまま Flask へ渡す。
    """
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """argparse のルートパーサーを構築して返す。"""
    p = argparse.ArgumentParser(prog="taskflow", description="TaskFlow CLI")
    sub = p.add_subparsers(dest="cmd")

    # init-db
    sp = sub.add_parser("init-db", help="Initialize database")
    sp.set_defaults(func=cmd_init_db)

    # add
    sp = sub.add_parser("add", help="Add a task")
    sp.add_argument("--title", required=True)
    sp.add_argument("--project", default=None)
    sp.add_argument("--priority", default="M", choices=["H", "M", "L"])  # 既定は M
    sp.add_argument("--est", type=float, default=None, help="estimate hours")
    sp.add_argument("--due", default=None, help="YYYY-MM-DD")
    sp.set_defaults(func=cmd_add)

    # list
    sp = sub.add_parser("list", help="List tasks")
    sp.add_argument("--status", default="todo", choices=["todo", "doing", "done", "all"])  
    sp.add_argument("--project", default=None)
    sp.add_argument("--due-before", dest="due_before", default=None)
    sp.set_defaults(func=cmd_list)

    # done
    sp = sub.add_parser("done", help="Mark task done")
    sp.add_argument("task_id", type=int)
    sp.set_defaults(func=cmd_done)

    # rm
    sp = sub.add_parser("rm", help="Remove task")
    sp.add_argument("task_id", type=int)
    sp.set_defaults(func=cmd_rm)

    # export
    sp = sub.add_parser("export", help="Export tasks")
    sp.add_argument("--format", default="csv")
    sp.add_argument("--out", required=True)
    sp.add_argument("--status", default="all", choices=["todo", "doing", "done", "all"])  
    sp.add_argument("--project", default=None)
    sp.set_defaults(func=cmd_export)

    # api
    sp = sub.add_parser("api", help="Run Flask API server")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=5000)
    sp.add_argument("--debug", action="store_true")
    sp.set_defaults(func=cmd_api)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    """エントリポイント。

    - `argv` が指定されなければ `sys.argv[1:]` が使われる
    - サブコマンド未指定時はヘルプを表示して 0 を返す
    - 各サブコマンド関数の戻り値をそのままプロセス終了コードに使う
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
