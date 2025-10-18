from __future__ import annotations
import typer, sqlite3, datetime as dt
from rich.console import Console
from rich.table import Table
from .db import get_conn, init_db as _init_db
from .utils import score_task

app = typer.Typer(help="TaskFlow Ops - 日次チェックインと自動計画")

@app.command()
def init_db():
    _init_db()
    typer.echo("DB initialized.")

@app.command()
def add(title: str = typer.Option(..., help="タスク名"),
        project: str = typer.Option(None, help="プロジェクト名"),
        priority: str = typer.Option("M", help="優先度 H/M/L"),
        est: float = typer.Option(1.0, help="推定工数（h）"),
        due: str = typer.Option(None, help="期限 YYYY-MM-DD")):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO tasks(title,project,priority,est_hours,due) VALUES(?,?,?,?,?)",
                (title, project, priority, est, due))
    conn.commit()
    tid = cur.lastrowid
    cur.execute("INSERT INTO events(task_id,kind,message) VALUES(?,?,?)", (tid,"add",f"add:{title}"))
    conn.commit(); conn.close()
    typer.echo(f"Added task #{tid}: {title}")

@app.command()
def list(status: str = typer.Option("todo", help="todo/doing/done/all"), limit: int = 50):
    conn = get_conn(); cur = conn.cursor()
    q = "SELECT * FROM tasks" + ("" if status=="all" else " WHERE status=?")
    rows = cur.execute(q, (status,) if status!="all" else ()).fetchall()
    conn.close()
    scored = [(score_task(r["priority"], r["due"], r["est_hours"]), r) for r in rows]
    scored.sort(key=lambda x: x[0], reverse=True)
    table = Table(title="Tasks")
    for c in ["id","title","project","priority","est_hours","due","status","score"]:
        table.add_column(c)
    for s,r in scored[:limit]:
        table.add_row(str(r["id"]), r["title"], r["project"] or "", r["priority"],
                      f'{r["est_hours"]:.1f}', str(r["due"] or ""), r["status"], f"{s:.2f}")
    Console().print(table)

@app.command()
def done(task_id: int):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE tasks SET status='done', updated_at=CURRENT_TIMESTAMP WHERE id=?", (task_id,))
    cur.execute("INSERT INTO events(task_id,kind,message) VALUES(?,?,?)", (task_id,"done","completed"))
    conn.commit(); conn.close()
    typer.echo(f"Task #{task_id} done.")

@app.command()
def checkin(auto: bool = typer.Option(False, help="対話をスキップして記録のみ")):
    date = dt.date.today().isoformat()
    if auto:
        avail = None; notes = ""
    else:
        avail = typer.prompt("今日の可処分時間（h）", default="3")
        notes = typer.prompt("今日のメモ", default="")
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO checkins(date,available_hours,notes) VALUES(?,?,?)",
                (date, float(avail) if avail else None, notes))
    conn.commit(); conn.close()
    typer.echo(f"Checked in: {date}")

@app.command()
def plan_today(hours: float = 3.0):
    conn = get_conn(); cur = conn.cursor()
    rows = cur.execute("SELECT * FROM tasks WHERE status='todo'").fetchall()
    conn.close()
    scored = [(score_task(r["priority"], r["due"], r["est_hours"]), r) for r in rows]
    scored.sort(key=lambda x: x[0], reverse=True)
    remaining = hours; plan = []
    for s,r in scored:
        if remaining <= 0: break
        dur = min(remaining, max(0.5, min(r["est_hours"], 2.0)))
        plan.append((r, s, dur)); remaining -= dur

    table = Table(title=f"今日のプラン（{hours}h）")
    for c in ["順","task_id","タイトル","時間(h)","スコア"]:
        table.add_column(c)
    for i,(r,s,d) in enumerate(plan,1):
        table.add_row(str(i), str(r["id"]), r["title"], f"{d:.2f}", f"{s:.2f}")
    Console().print(table)

@app.command()
def weekly_report(out: str = "data/weekly.xlsx"):
    import pandas as pd
    from pathlib import Path
    conn = get_conn()
    tasks = pd.read_sql_query("SELECT * FROM tasks", conn)
    events = pd.read_sql_query("SELECT * FROM events", conn)
    checkins = pd.read_sql_query("SELECT * FROM checkins", conn)
    conn.close()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        tasks.to_excel(w, index=False, sheet_name="tasks")
        events.to_excel(w, index=False, sheet_name="events")
        checkins.to_excel(w, index=False, sheet_name="checkins")
    typer.echo(f"Wrote: {out}")

def main():
    app()

if __name__ == "__main__":
    main()
