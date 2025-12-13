from __future__ import annotations

import json
import logging
from typing import Any, Dict

from openai import OpenAI

from .config import settings
from .ai_engine import _writelog  # reuse audit log helper


log = logging.getLogger(__name__)


def _make_openai_client() -> OpenAI:
    kwargs: Dict[str, Any] = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return OpenAI(**kwargs)  # type: ignore[arg-type]


SYSTEM_PROMPT = (
    "You are an expert productivity AI. Given user's dialog and TaskFlow DB context, "
    "you will normalize inputs, resolve duplicates, reprioritize, and generate a realistic day plan.\n"
    "Return STRICT JSON with the following keys only: plan, mutations, dedupe, audit.\n"
    "Constraints: \n"
    "- plan: total_hours, blocks(start,end,hours,title,source,reason_summary, due_date?), alerts(code,message,source,reason_summary), advice\n"
    "- mutations: add[{title,priority,estimate_hours?,due_date?}], update[{id,<fields>}], done[{id}], defer[{id,due_date}]\n"
    "- dedupe: [{source, matched_task_id, similarity, decision}] with decision in ['merge','new']\n"
    "- audit.scoring: list of items with S_base, S_adj(±2), S_total and reasons[{source,reason_summary}]\n"
    "Guardrails: do not exceed today_hours+15%; blocks are 0.5-2.0h; at most two consecutive blocks for same task;"
    " include DEADLINE_RISK alerts with explanation when tasks due in 48h are not scheduled; include OVERLOAD alert if exceeded;"
    " every block and alert MUST include source and reason_summary. If a task has a known due date in context, include it as due_date in blocks.\n"
    "Important: Use Japanese for all human‑facing texts (titles, messages, reasons, alerts, advice)."
)


def _build_user_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Trim context to save tokens
    ctx = payload.get("context") or {}
    tasks = list(ctx.get("tasks") or [])
    # limit to 150 tasks; sort roughly by due/priority if present
    def _pri_val(p):
        return {"H": 3, "M": 2, "L": 1}.get(str(p or "M").upper(), 2)
    tasks_sorted = sorted(tasks, key=lambda t: (t.get("due_date") is None, t.get("due_date") or "9999-12-31", -_pri_val(t.get("priority"))))
    tasks_trim = tasks_sorted[:150]
    ctx_out = {
        "tasks": tasks_trim,
        "checkins_recent": (ctx.get("checkins_recent") or [])[:50],
        "events_recent": (ctx.get("events_recent") or [])[:200],
    }
    return {
        "free_text": payload.get("free_text") or "",
        "today_hours": payload.get("today_hours") or 0,
        "dialog_entries": payload.get("dialog_entries") or [],
        "context": ctx_out,
    }


def organize_with_openai(payload: Dict[str, Any]) -> Dict[str, Any]:
    client = _make_openai_client()
    user_payload = _build_user_payload(payload)
    try:
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            temperature=settings.openai_temperature,
            max_tokens=settings.openai_max_tokens,
        )
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
        _writelog({
            "source": "openai",
            "reason_summary": "LLM organize completed",
            "model": settings.openai_model,
            "usage": getattr(resp, "usage", None) and resp.usage.model_dump(),
        })
        return data
    except Exception as e:
        log.error("OpenAI organize failed: %s", e)
        _writelog({"source": "openai", "reason_summary": f"error {e}"})
        raise
