from __future__ import annotations

from typing import Any, Dict, List, Optional
import os
import datetime as _dt
import re as _re


def checkin_prompt_blocks() -> List[Dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "おはようございます！本日のチェックインをお願いします。\nボタンから3点（昨日/今日/ブロッカー）を入力してください。",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "チェックインを入力"},
                    "action_id": "open_checkin_modal",
                    "style": "primary",
                }
            ],
        },
    ]


def checkin_modal() -> Dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": "checkin_modal",
        "title": {"type": "plain_text", "text": "Daily Check-in"},
        "submit": {"type": "plain_text", "text": "送信"},
        "close": {"type": "plain_text", "text": "キャンセル"},
        "blocks": [
            {
                "type": "input",
                "block_id": "today_hours_block",
                "label": {"type": "plain_text", "text": "今日の可処分時間(h)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "today_hours_input",
                    "placeholder": {"type": "plain_text", "text": "例: 3.0"},
                },
            },
            {
                "type": "input",
                "block_id": "yesterday_block",
                "label": {"type": "plain_text", "text": "昨日やったこと"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "yesterday_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "例: タスク #123 完了、レビュー送付 など"},
                },
            },
            {
                "type": "input",
                "block_id": "today_block",
                "label": {"type": "plain_text", "text": "今日やること"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "today_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "例: 10-12 仕様書、午後 実装 #234 着手"},
                },
            },
            {
                "type": "input",
                "optional": True,
                "block_id": "blockers_block",
                "label": {"type": "plain_text", "text": "ブロッカー/困りごと"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "blockers_input",
                    "multiline": True,
                },
            },
            {
                "type": "input",
                "optional": True,
                "block_id": "constraints_block",
                "label": {"type": "plain_text", "text": "不可時間/会議 (例: 10:00-11:00)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "constraints_input",
                    "multiline": False,
                },
            },
        ],
    }


def _is_cjk_present(s: str) -> bool:
    return any('\u3040' <= ch <= '\u30ff' or '\u4e00' <= ch <= '\u9fff' for ch in s or "")


def _jp_reason(s: Optional[str]) -> str:
    if not s:
        return ""
    t = str(s)
    # 簡易置換（既知の英語理由→日本語）
    repl = [
        ("Due <=48h", "期限まで48時間以内"),
        ("urgency boost", "緊急度加点"),
        ("Continuity value", "継続作業の価値"),
        ("Likely blocked", "ブロッカーの可能性"),
        ("Ranked by score and placed avoiding busy times", "優先度と予定に基づき配置（不可時間を回避）"),
        ("scheduled", "予定に配置"),
        ("deadline", "期限"),
    ]
    for a, b in repl:
        t = t.replace(a, b)
    return t


def _fmt_date(s: Optional[str]) -> str:
    if not s:
        return "-"
    return str(s)


def plan_blocks_from_api(plan: Dict[str, Any], tasks: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "本日のプラン"}}
    ]
    # AI plan with blocks/alerts/advice
    if isinstance(plan, dict) and "blocks" in plan:
        total_hours = plan.get("total_hours")
        block_list = list(plan.get("blocks") or [])
        alerts_list = list(plan.get("alerts") or [])
        # Summary line
        try:
            summary = f"総時間：{float(total_hours):.1f} 時間 / 計画数：{len(block_list)} 件 / 警告：{len(alerts_list)} 件"
        except Exception:
            summary = f"計画数：{len(block_list)} 件 / 警告：{len(alerts_list)} 件"
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": summary}]})

        # 全体タスク（先頭10件を表示）
        if tasks is not None:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*全体タスク*"}})
            if tasks:
                lines: List[str] = []
                for i, t in enumerate(tasks[:10], start=1):
                    due = t.get("due_date") or "-"
                    title = t.get("title") or "(無題)"
                    lines.append(f"{i}. {title}  （期限: {due}）")
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
            else:
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "（なし）"}})

            # 期限切れタスク
            today = _dt.date.today()
            overdue: List[str] = []
            for t in tasks:
                dd = t.get("due_date")
                st = t.get("status")
                if not dd or st == "done":
                    continue
                try:
                    d = _dt.date.fromisoformat(dd)
                except Exception:
                    continue
                if d < today:
                    overdue.append(f"• {dd} {t.get('title')}")
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*期限切れタスク*"}})
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": ("\n".join(overdue) if overdue else "（なし）")}})

        # 今日のタスク（優先度順）
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*今日のタスク（優先度順）*"}})
        show_slots = os.getenv("SHOW_TIME_SLOTS", "0").lower() in {"1", "true", "yes"}

        def _hhmm(v: Optional[str]) -> str:
            if not v:
                return ""
            s = str(v)
            if "T" in s and len(s) >= 16:
                # 2025-10-18T09:00:00 → 09:00
                return s.split("T", 1)[1][:5]
            m = _re.match(r"^(\d{1,2}:\d{2})", s)
            return m.group(1) if m else s
        # Fallback map for due_date: plan blockに無い場合は tasks から補完
        id_to_due: Dict[int, str] = {}
        title_to_due: Dict[str, str] = {}
        if tasks:
            for t in tasks:
                try:
                    if isinstance(t.get("id"), int) and t.get("due_date"):
                        id_to_due[int(t["id"])]= str(t.get("due_date"))
                    if t.get("title") and t.get("due_date"):
                        title_to_due[str(t.get("title") or "").strip().lower()] = str(t.get("due_date"))
                except Exception:
                    continue

        for idx, b in enumerate(block_list, start=1):
            t = b.get("title") or "(無題)"
            # 補完ロジック: 1) blockのdue_date 2) task_id一致 3) タイトル一致
            due_val = b.get("due_date")
            if not due_val and isinstance(b.get("task_id"), int):
                due_val = id_to_due.get(int(b.get("task_id")))
            if not due_val and t:
                due_val = title_to_due.get(str(t).strip().lower())
            due = _fmt_date(due_val)
            reason = _jp_reason(b.get("reason_summary"))
            lines: List[str] = [f"{idx}. {t}"]
            if show_slots:
                start_s = _hhmm(b.get("start"))
                end_s = _hhmm(b.get("end"))
                if start_s:
                    lines.append(f"開始：{start_s}")
                if end_s:
                    lines.append(f"終了：{end_s}")
                if not start_s and not end_s:
                    hrs = b.get("hours")
                    hrs_s = f"{hrs}h" if hrs is not None else "-"
                    lines.append(f"所要時間：{hrs_s}")
            else:
                hrs = b.get("hours")
                hrs_s = f"{hrs}h" if hrs is not None else "-"
                lines.append(f"所要時間：{hrs_s}")
            lines.append(f"期限：{due}")
            lines.append(f"理由：{reason}")
            text = "\n".join(lines)
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

        # アドバイス
        if plan.get("advice"):
            advice = str(plan["advice"])  # type: ignore[index]
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*アドバイス*\n{advice}"}})

        # 重要アラート（日本語化）
        if alerts_list:
            def _jp_alert(a: Dict[str, Any]) -> str:
                code = a.get("code")
                msg = str(a.get("message") or "")
                # 簡易変換
                code_jp = {"OVERLOAD": "計画超過", "DEADLINE_RISK": "期限リスク"}.get(code, str(code))
                msg = msg.replace("exceeds", "が上限を超過").replace("not scheduled", "未計画")
                return f"• [{code_jp}] {msg}"
            alert_text = "\n".join(_jp_alert(a) for a in alerts_list)
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*アラート*\n{alert_text}"}})

        # Optional: external dashboard link button
        dash_url = os.getenv("DASHBOARD_URL")
        if dash_url:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "詳細を見る"},
                        "url": dash_url,
                        "action_id": "open_dashboard",
                    }
                ],
            })
        return blocks
    # Flexible rendering: support text, items, or tasks fallback
    if isinstance(plan, dict) and "text" in plan:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": str(plan["text"])}})
    elif isinstance(plan, dict) and "items" in plan and isinstance(plan["items"], list):
        for item in plan["items"]:
            title = item.get("title") or item.get("name") or "(no title)"
            time = item.get("time") or item.get("slot") or ""
            note = item.get("notes") or ""
            text = f"• {time} {title}\n{note}" if note else f"• {time} {title}"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
    elif isinstance(plan, list):
        for it in plan:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"• {it}"}})
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```\n{plan}\n```"},
        })
    return blocks
