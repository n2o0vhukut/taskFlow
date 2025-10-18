from __future__ import annotations
import datetime as dt

def priority_weight(p: str) -> int:
    return {"H":3,"M":2,"L":1}.get(p or "M", 2)

def days_until(due: str | None) -> int | None:
    if not due: return None
    try:
        d = dt.date.fromisoformat(str(due))
        return (d - dt.date.today()).days
    except Exception:
        return None

def score_task(priority: str, due: str | None, est_hours: float) -> float:
    du = days_until(due)
    due_score = 0
    if du is not None:
        due_score = max(0, 21 - max(du,0)) / 21.0 * 3  # 0..3
    est_score = 2.0 / max(est_hours or 0.1, 0.1)
    return round(priority_weight(priority) + due_score + est_score, 3)
