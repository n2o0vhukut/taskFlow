from __future__ import annotations

from typing import Any, Dict, List


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


def plan_blocks_from_api(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "本日のプラン"}}
    ]
    # AI plan with blocks/alerts/advice
    if isinstance(plan, dict) and "blocks" in plan:
        if plan.get("alerts"):
            alert_text = "\n".join(f"• [{a.get('code')}] {a.get('message')}" for a in plan.get("alerts", []))
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*アラート*\n{alert_text}"}})
        # Render schedule blocks
        for b in plan.get("blocks", []):
            t = b.get("title") or "(no title)"
            start_end = f"{b.get('start','')}-{b.get('end','')}" if b.get("start") else f"{b.get('hours','')}h"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"• {start_end} {t}"}})
        if plan.get("advice"):
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"_アドバイス_: {plan['advice']}"}]})
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
