from __future__ import annotations

import logging
import os
from datetime import datetime, date, timedelta
import re
import uuid

from flask import Flask, request
from slack_sdk.errors import SlackApiError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from .taskflow_client import TaskFlowClient
from .block_kit import checkin_prompt_blocks, checkin_modal, plan_blocks_from_api
from .spooler import Spooler
from .ai_engine import organize, apply_mutations


logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
log = logging.getLogger(__name__)


# Flask app and Slack Bolt app
flask_app = Flask(__name__)

# Optional offline mode to run without Slack tokens
SLACK_OFFLINE = os.getenv("SLACK_OFFLINE", "0").lower() in {"1", "true", "yes"}
slack_app = None
handler = None
if not SLACK_OFFLINE:
    try:
        from slack_bolt import App as SlackApp  # lazy to allow offline usage
        from slack_bolt.adapter.flask import SlackRequestHandler

        slack_app = SlackApp(token=settings.slack_bot_token, signing_secret=settings.slack_signing_secret)
        handler = SlackRequestHandler(slack_app)
    except Exception as e:
        log.error("Slack initialization failed: %s", e)
        log.error("Set SLACK_OFFLINE=1 to run without Slack.")
        SLACK_OFFLINE = True


# Clients
tf = TaskFlowClient(base_url=settings.taskflow_base_url, token=settings.taskflow_token)
spool = Spooler(settings.spool_dir)

# In-memory store for pending mutations (Dry-Run -> Apply)
_PENDING_MUTATIONS: dict[str, dict] = {}
# In-memory store for dedupe decisions pending confirmation
_PENDING_DEDUPE: dict[str, dict] = {}
# In-memory store and helpers for overdue follow-ups
_OVERDUE_PROMPTS: dict[str, dict] = {}


def _parse_hhmm(s: str | None) -> tuple[int, int] | None:
    if not s:
        return None
    try:
        if "T" in s and len(s) >= 16:
            hh, mm = s.split("T", 1)[1][:5].split(":")
            return int(hh), int(mm)
        if ":" in s:
            hh, mm = s[:5].split(":")
            return int(hh), int(mm)
    except Exception:
        return None
    return None


def _build_overdue_blocks(plan: dict, tasks: list[dict] | None, user_id: str | None) -> list[dict]:
    try:
        items = list((plan or {}).get("blocks") or [])  # type: ignore[union-attr]
    except Exception:
        items = []
    task_ids = {int(t["id"]) for t in (tasks or []) if isinstance(t.get("id"), int)}
    now = datetime.now()
    now_minutes = now.hour * 60 + now.minute
    out: list[dict] = []
    added = 0
    for it in items:
        tid = it.get("task_id")
        if not isinstance(tid, int) or (tasks is not None and tid not in task_ids):
            continue
        start = _parse_hhmm(str(it.get("start")) if it.get("start") is not None else None)
        if not start:
            continue
        if start[0] * 60 + start[1] >= now_minutes:
            continue
        token = uuid.uuid4().hex
        _OVERDUE_PROMPTS[token] = {"task_id": tid, "title": it.get("title"), "start": it.get("start"), "user_id": user_id}
        if added == 0:
            out.append({"type": "section", "text": {"type": "mrkdwn", "text": "*開始時刻を過ぎているタスクの確認*"}})
        out.append({"type": "section", "text": {"type": "mrkdwn", "text": f"• {it.get('title')}（開始：{it.get('start')}）\n状況を教えてください。"}})
        out.append({
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "完了した"}, "style": "primary", "action_id": "overdue_done", "value": token},
                {"type": "button", "text": {"type": "plain_text", "text": "リスケする"}, "action_id": "overdue_reschedule", "value": token},
            ],
        })
        added += 1
        if added >= 3:
            break
    # Due-date overdue checks
    try:
        all_tasks = list(tasks or [])
    except Exception:
        all_tasks = []
    if all_tasks:
        from datetime import date as _date
        today = _date.today()
        due_added = 0
        for t in all_tasks:
            try:
                tid = int(t.get("id")) if t.get("id") is not None else None
                status = str(t.get("status") or "")
                due = t.get("due_date")
            except Exception:
                continue
            if not tid or status == "done" or not due:
                continue
            try:
                d = _date.fromisoformat(str(due))
            except Exception:
                continue
            if d >= today:
                continue
            token = uuid.uuid4().hex
            _OVERDUE_PROMPTS[token] = {"task_id": tid, "title": t.get("title"), "due": due, "user_id": user_id}
            if due_added == 0:
                out.append({"type": "section", "text": {"type": "mrkdwn", "text": "*期限切れタスクの確認*"}})
            out.append({"type": "section", "text": {"type": "mrkdwn", "text": f"• {t.get('title')}（期限：{due}）\n状況を教えてください。"}})
            out.append({
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "完了した"}, "style": "primary", "action_id": "overdue_done", "value": token},
                    {"type": "button", "text": {"type": "plain_text", "text": "リスケする"}, "action_id": "overdue_reschedule", "value": token},
                ],
            })
            due_added += 1
            if due_added >= 3:
                break

    return out


@flask_app.get("/healthz")
def healthz():  # type: ignore
    return {"ok": True, "time": datetime.utcnow().isoformat() + "Z"}


@flask_app.post("/admin/trigger")
def admin_trigger():  # type: ignore
    token = request.headers.get("X-Admin-Token")
    if settings.admin_token and token != settings.admin_token:
        return {"error": "unauthorized"}, 401
    data = request.get_json(silent=True) or {}
    kind = data.get("type")
    user = data.get("user")
    if kind == "prompt":
        if SLACK_OFFLINE or slack_app is None:
            return {"error": "slack_offline"}, 400
        if user:
            send_daily_prompt(slack_app.client, user)
        else:
            for uid in settings.daily_user_ids:
                send_daily_prompt(slack_app.client, uid)
        return {"status": "prompt_sent"}
    if kind == "drain":
        retry_spool_checkins()
        return {"status": "drained"}
    if kind == "plan":
        if not user:
            return {"error": "user required"}, 400
        try:
            if SLACK_OFFLINE or slack_app is None:
                return {"error": "slack_offline"}, 400
            tf_user = settings.user_map.get(user, user)
            plan = tf.get_plan(tf_user, date.today())
            try:
                tasks = tf.list_tasks(status="all")
            except Exception:
                tasks = []
            over = _build_overdue_blocks(plan or {}, tasks, user)
            blocks = plan_blocks_from_api(plan, tasks) + over
            ch = slack_app.client.conversations_open(users=user)["channel"]["id"]
            slack_app.client.chat_postMessage(channel=ch, text="Plan", blocks=blocks)
            return {"status": "plan_sent"}
        except Exception as e:
            return {"error": str(e)}, 500
    return {"error": "unknown type"}, 400


# ---- AI API endpoints (local to this bot) ----
@flask_app.post("/ai/organize")
def ai_organize():  # type: ignore
    data = request.get_json(silent=True) or {}
    try:
        return organize(data)
    except Exception as e:
        return {"error": str(e)}, 500


@flask_app.post("/ai/apply")
def ai_apply():  # type: ignore
    data = request.get_json(silent=True) or {}
    mutations = data.get("mutations") or {}
    def _apply(kind: str, item: dict):
        if kind == "add":
            return tf.add_task(**{k: v for k, v in item.items() if k in {"title", "project", "priority", "estimate_hours", "due_date"}})
        if kind == "update":
            return tf.update_task(int(item["id"]), **{k: v for k, v in item.items() if k != "id"})
        if kind == "done":
            return tf.mark_done(int(item["id"]))
        if kind == "defer":
            return tf.update_task(int(item["id"]), due_date=item.get("due_date"))
        raise ValueError(f"unknown mutation kind: {kind}")
    try:
        res = apply_mutations(mutations=mutations, apply_fn=_apply, reason=data.get("reason") or "api apply")
        return res
    except Exception as e:
        return {"error": str(e)}, 500


@flask_app.get("/")
def index():  # type: ignore
    return {
        "service": "slack-bot",
        "health": "ok",
        "ui": "/ui",
        "ai_organize": "/ai/organize",
        "ai_apply": "/ai/apply",
        "openai_enabled": bool(os.getenv("OPENAI_API_KEY")),
    }


@flask_app.route("/ui", methods=["GET", "POST"])
def simple_ui():  # type: ignore
    # Minimal HTML form to test organize with/without OpenAI
    if request.method == "POST":
        free_text = request.form.get("free_text", "")
        today_hours = float(request.form.get("today_hours", "0") or 0)
        use_tasks = request.form.get("use_tasks") == "on"
        try:
            tasks = tf.list_tasks(status="all") if use_tasks else []
        except Exception:
            tasks = []
        payload = {
            "free_text": free_text,
            "today_hours": today_hours,
            "dialog_entries": [],
            "context": {"tasks": tasks, "checkins_recent": [], "events_recent": []},
        }
        try:
            res = organize(payload)
        except Exception as e:
            res = {"error": str(e)}
        import html, json
        body = f"""
        <h2>Organize Result</h2>
        <p>engine: <b>{html.escape(str(res.get('engine')))}</b> (openai_enabled={bool(os.getenv('OPENAI_API_KEY'))})</p>
        <pre style='white-space: pre-wrap; background:#f7f7f7; padding:8px;'>{html.escape(json.dumps(res, ensure_ascii=False, indent=2))}</pre>
        <p><a href='/ui'>← back</a></p>
        """
        return f"<html><body>{body}</body></html>"
    # GET: show form
    return """
    <html><body>
      <h2>AI Organize Tester</h2>
      <form method="post">
        <div>
          <label>Today Hours:</label>
          <input name="today_hours" type="number" step="0.5" value="3" />
        </div>
        <div>
          <label>Free Text (新規/不可時間など):</label><br/>
          <textarea name="free_text" rows="8" cols="80">新規: レポート作成
不可: 13:00-14:00
昨日: PR #12 完了
今日: バグ修正 #34</textarea>
        </div>
        <div>
          <label><input type="checkbox" name="use_tasks" checked /> Use current DB tasks</label>
        </div>
        <div>
          <button type="submit">Run organize</button>
        </div>
      </form>
      <hr/>
      <p>OpenAI enabled: <b>{}</b> (set OPENAI_API_KEY to enable)</p>
    </body></html>
    """.format("yes" if os.getenv("OPENAI_API_KEY") else "no")


if not SLACK_OFFLINE and handler is not None:
    @flask_app.post("/slack/events")
    def slack_events():  # type: ignore
        return handler.handle(request)


# 1) Action: open modal from button
if not SLACK_OFFLINE and slack_app is not None:
    @slack_app.action("open_checkin_modal")
    def handle_open_checkin_modal(ack, body, client):  # type: ignore
        ack()
        try:
            client.views_open(trigger_id=body["trigger_id"], view=checkin_modal())
        except SlackApiError as e:
            log.error("views_open failed: %s", e)


_PROCESSED_VIEW_IDS: set[str] = set()


# 2) Modal submission: create check-in, fetch plan, reply
if not SLACK_OFFLINE and slack_app is not None:
    @slack_app.view("checkin_modal")
    def handle_checkin_modal(ack, body, client, logger):  # type: ignore
        ack()
        try:
            view = body.get("view", {})
            view_id = view.get("id")
            user_id = body.get("user", {}).get("id")
            vals = view.get("state", {}).get("values", {})
            def _v(block_id: str, action_id: str) -> str:
                return vals.get(block_id, {}).get(action_id, {}).get("value", "").strip()
            hrs_str = _v("today_hours_block", "today_hours_input") or "0"
            y = _v("yesterday_block", "yesterday_input")
            t = _v("today_block", "today_input")
            b = _v("blockers_block", "blockers_input")
            c = _v("constraints_block", "constraints_input")
            # Idempotency (in-memory)
            if view_id in _PROCESSED_VIEW_IDS:
                log.info("duplicate view %s ignored", view_id)
                return
            _PROCESSED_VIEW_IDS.add(view_id)

            # Map Slack user -> TaskFlow user key
            tf_user = settings.user_map.get(user_id, user_id)

            today_date = date.today()
            meta = {
                "slack": {
                    "view_id": view_id,
                    "user_id": user_id,
                }
            }

            def _post_checkin(data):
                try:
                    tf.post_checkin(
                        user=tf_user,
                        checkin_date=today_date,
                        yesterday=data["yesterday"],
                        today=data["today"],
                        blockers=data.get("blockers", ""),
                        meta=meta,
                    )
                    return True
                except Exception as e:
                    log.error("TaskFlow checkin failed: %s", e)
                    return False

            payload = {"yesterday": y, "today": t, "blockers": b}
            if not _post_checkin(payload):
                # Persist for retry
                spool.enqueue("checkins", {
                    "user": tf_user,
                    "date": today_date.isoformat(),
                    **payload,
                    "meta": meta,
                })

            # Build AI organize payload
            try:
                tasks = tf.list_tasks(status="all")
            except Exception:
                tasks = []
            # In this repo, /checkins and /events may not exist; fallback empty
            checkins_recent = []
            events_recent = []

            dialog_entries = [
                {"role": "user", "name": "yesterday", "text": y},
                {"role": "user", "name": "today", "text": t},
                {"role": "user", "name": "blockers", "text": b},
            ]
            free_text = "\n".join(x for x in [y, t, b, c] if x)
            try:
                org = organize({
                    "free_text": free_text,
                    "today_hours": float(hrs_str or 0),
                    "dialog_entries": dialog_entries,
                    "context": {
                        "tasks": tasks,
                        "checkins_recent": checkins_recent,
                        "events_recent": events_recent,
                    },
                })
            except Exception as e:
                log.error("organize failed: %s", e)
                org = {"plan": {"blocks": [], "alerts": [{"code": "ENGINE_ERROR", "message": str(e), "source": "engine", "reason_summary": "organize failure"}], "advice": ""}, "mutations": {"add": [], "update": [], "done": [], "defer": []}}

            def _mut_counts(muts: dict) -> tuple[int, int, int, int]:
                return (
                    len(muts.get("add") or []),
                    len(muts.get("update") or []),
                    len(muts.get("done") or []),
                    len(muts.get("defer") or []),
                )

            # Render plan
            plan_only_blocks = plan_blocks_from_api(org.get("plan") or {}, tasks)
            overdue_blocks = _build_overdue_blocks(org.get("plan") or {}, tasks, user_id)

            # Dry-Run -> show preview with Apply button if enabled
            if settings.preview_before_apply:
                muts = org.get("mutations") or {"add": [], "update": [], "done": [], "defer": []}
                a, u, d, f = _mut_counts(muts)
                token = uuid.uuid4().hex
                _PENDING_MUTATIONS[token] = {
                    "mutations": muts,
                    "reason": "slack check-in apply",
                    "user_id": user_id,
                }
                preview = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": f"*適用予定の変更*  add {a} / update {u} / done {d} / defer {f}"}},
                ]
                # Ambiguous dedupe confirmations (0.7–0.8)
                reviews = [x for x in (org.get("dedupe") or []) if x.get("decision") == "review"]
                if reviews:
                    preview.append({"type": "section", "text": {"type": "mrkdwn", "text": "*重複の可能性*（確認してください）"}})
                    for r in reviews[:5]:
                        dtoken = uuid.uuid4().hex
                        _PENDING_DEDUPE[dtoken] = {
                            "pending_token": token,
                            "matched_task_id": r.get("matched_task_id"),
                            "matched_title": r.get("matched_title"),
                            "candidate_title": r.get("candidate_title"),
                            "similarity": r.get("similarity"),
                            "user_id": user_id,
                        }
                        text = f"'{r.get('candidate_title')}' ≈ 既存 #{r.get('matched_task_id')} '{r.get('matched_title')}' (sim {r.get('similarity')})"
                        preview.extend([
                            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                            {"type": "actions", "elements": [
                                {"type": "button", "text": {"type": "plain_text", "text": "統合する"}, "style": "primary", "action_id": "dedupe_merge", "value": dtoken},
                                {"type": "button", "text": {"type": "plain_text", "text": "別タスク"}, "action_id": "dedupe_new", "value": dtoken},
                            ]},
                        ])
                actions = [{
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "適用する"},
                            "style": "primary",
                            "action_id": "apply_mutations_now",
                            "value": token,
                        }
                    ],
                }]
                blocks = preview + plan_only_blocks + overdue_blocks + actions
            else:
                # Apply mutations to TaskFlow immediately (legacy behavior)
                def _apply(kind: str, item: dict):
                    if kind == "add":
                        return tf.add_task(**{k: v for k, v in item.items() if k in {"title", "project", "priority", "estimate_hours", "due_date"}})
                    if kind == "update":
                        return tf.update_task(int(item["id"]), **{k: v for k, v in item.items() if k != "id"})
                    if kind == "done":
                        return tf.mark_done(int(item["id"]))
                    if kind == "defer":
                        return tf.update_task(int(item["id"]), due_date=item.get("due_date"))
                    raise ValueError(f"unknown mutation kind: {kind}")
                try:
                    apply_mutations(mutations=org.get("mutations") or {}, apply_fn=_apply, reason="slack check-in apply")
                except Exception as e:
                    log.error("apply mutations failed: %s", e)
                blocks = plan_only_blocks + overdue_blocks

            # DM the user
            try:
                # Ensure DM channel
                ch = client.conversations_open(users=user_id)["channel"]["id"]
                client.chat_postMessage(channel=ch, text="チェックインありがとうございます！", blocks=blocks)
            except SlackApiError as e:
                logger.error("chat_postMessage failed: %s", e)
        except Exception as e:
            logger.error("handle_checkin_modal unexpected error: %s", e)


# 3) Slash command to fetch today's plan on-demand
if not SLACK_OFFLINE and slack_app is not None:
    @slack_app.command("/plan")
    def handle_plan_cmd(ack, body, client, logger):  # type: ignore
        ack()
        try:
            user_id = body.get("user_id")
            tf_user = settings.user_map.get(user_id, user_id)
            # optional hours arg: "/plan 3" → today_hours=3.0
            raw_text = (body.get("text") or "").strip()
            try:
                hours = float(raw_text) if raw_text else float(settings.default_plan_hours)
            except Exception:
                hours = float(settings.default_plan_hours)
            tasks = tf.list_tasks(status="all")
            org = organize({
                "free_text": "",
                "today_hours": hours,
                "dialog_entries": [],
                "context": {"tasks": tasks, "checkins_recent": [], "events_recent": []},
            })
            over = _build_overdue_blocks(org.get("plan") or {}, tasks, user_id)
            blocks = plan_blocks_from_api(org.get("plan") or {}, tasks) + over
            ch = client.conversations_open(users=user_id)["channel"]["id"]
            client.chat_postMessage(channel=ch, text="本日のプラン", blocks=blocks)
        except Exception as e:
            logger.error("/plan failed: %s", e)

    @slack_app.action("dedupe_merge")
    def handle_dedupe_merge(ack, body, client, logger):  # type: ignore
        ack()
        try:
            token = body.get("actions", [{}])[0].get("value")
            user_id = body.get("user", {}).get("id")
            entry = _PENDING_DEDUPE.pop(token, None)
            if not entry:
                if user_id:
                    ch = client.conversations_open(users=user_id)["channel"]["id"]
                    client.chat_postMessage(channel=ch, text="対象が見つかりませんでした（期限切れ）。")
                return
            tid = int(entry["matched_task_id"]) if entry.get("matched_task_id") is not None else None
            title = entry.get("candidate_title") or ""
            if tid is None:
                raise ValueError("invalid matched_task_id")
            tf.update_task(tid, title=title)
            msg = f"重複を統合しました: #{tid} ← '{title}'"
            if user_id:
                ch = client.conversations_open(users=user_id)["channel"]["id"]
                client.chat_postMessage(channel=ch, text=msg)
        except Exception as e:
            logger.error("dedupe_merge failed: %s", e)

    @slack_app.action("dedupe_new")
    def handle_dedupe_new(ack, body, client, logger):  # type: ignore
        ack()
        try:
            token = body.get("actions", [{}])[0].get("value")
            user_id = body.get("user", {}).get("id")
            entry = _PENDING_DEDUPE.pop(token, None)
            if not entry:
                if user_id:
                    ch = client.conversations_open(users=user_id)["channel"]["id"]
                    client.chat_postMessage(channel=ch, text="対象が見つかりませんでした（期限切れ）。")
                return
            title = entry.get("candidate_title") or ""
            # If we had preview token, append to its add list; else add immediately
            pt = entry.get("pending_token")
            if pt and pt in _PENDING_MUTATIONS:
                _PENDING_MUTATIONS[pt].setdefault("mutations", {}).setdefault("add", []).append({"title": title, "priority": "M"})
                msg = f"別タスクとして扱います（適用時に追加）: '{title}'"
            else:
                tf.add_task(title=title, priority="M")
                msg = f"別タスクとして追加しました: '{title}'"
            if user_id:
                ch = client.conversations_open(users=user_id)["channel"]["id"]
                client.chat_postMessage(channel=ch, text=msg)
        except Exception as e:
            logger.error("dedupe_new failed: %s", e)

    @slack_app.action("apply_mutations_now")
    def handle_apply_mutations_now(ack, body, client, logger):  # type: ignore
        ack()
        try:
            token = body.get("actions", [{}])[0].get("value")
            user_id = body.get("user", {}).get("id")
            entry = _PENDING_MUTATIONS.pop(token, None)
            if not entry:
                # Nothing pending; inform user
                if user_id:
                    ch = client.conversations_open(users=user_id)["channel"]["id"]
                    client.chat_postMessage(channel=ch, text="適用対象が見つかりませんでした（期限切れ）。もう一度お試しください。")
                return

            muts = entry.get("mutations") or {}
            reason = entry.get("reason") or "apply via button"

            def _apply(kind: str, item: dict):
                if kind == "add":
                    return tf.add_task(**{k: v for k, v in item.items() if k in {"title", "project", "priority", "estimate_hours", "due_date"}})
                if kind == "update":
                    return tf.update_task(int(item["id"]), **{k: v for k, v in item.items() if k != "id"})
                if kind == "done":
                    return tf.mark_done(int(item["id"]))
                if kind == "defer":
                    return tf.update_task(int(item["id"]), due_date=item.get("due_date"))
                raise ValueError(f"unknown mutation kind: {kind}")

            res = apply_mutations(mutations=muts, apply_fn=_apply, reason=reason)
            a = sum(1 for x in res.get("applied", []) if x.get("kind") == "add")
            u = sum(1 for x in res.get("applied", []) if x.get("kind") == "update")
            d = sum(1 for x in res.get("applied", []) if x.get("kind") == "done")
            f = sum(1 for x in res.get("applied", []) if x.get("kind") == "defer")
            err = len(res.get("errors", []))
            summary = f"Applied: add {a} / update {u} / done {d} / defer {f} (errors {err})"
            if user_id:
                ch = client.conversations_open(users=user_id)["channel"]["id"]
                client.chat_postMessage(channel=ch, text=summary)
        except Exception as e:
            logger.error("apply_mutations_now failed: %s", e)

    # ---- DMの通常メッセージにも反応（message.im） ----
    # Slack App 設定で Event Subscriptions を有効化し、bot events に "message.im" を追加してください。
    # 併せて Bot Token Scopes に "im:history" を追加し、再インストールが必要です。
    @slack_app.event("message")
    def handle_dm_message_events(body, client, logger):  # type: ignore
        try:
            ev = body.get("event", {})
            # DM以外は無視/ボット自身は無視
            if ev.get("channel_type") != "im" or ev.get("bot_id"):
                return
            channel = ev.get("channel")
            user_id = ev.get("user")
            text = (ev.get("text") or "").strip()
            if not channel or not user_id or not text:
                return

            # ヘルプ
            if text.lower() in {"help", "ヘルプ", "使い方"}:
                help_text = (
                    "使い方:\n"
                    "• そのまま文章を送る → 内容を踏まえて本日のプランを提案\n"
                    "• `3h` や `3 時間` を含める → 可処分時間として扱う\n"
                    "• `/plan 3` でも同様に3時間で計画\n"
                    "• `/tasks` でタスク一覧（期限順）を表示"
                )
                client.chat_postMessage(channel=channel, text=help_text)
                return

            # 時間抽出（例: 3h, 2.5h, 3 時間）
            hours = settings.default_plan_hours
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|時間)", text, re.IGNORECASE)
            if m:
                try:
                    hours = float(m.group(1))
                except Exception:
                    pass

            # organize 実行
            try:
                tasks = tf.list_tasks(status="all")
            except Exception:
                tasks = []
            payload = {
                "free_text": text,
                "today_hours": float(hours or 0),
                "dialog_entries": [],
                "context": {"tasks": tasks, "checkins_recent": [], "events_recent": []},
            }
            try:
                org = organize(payload)
            except Exception as e:
                logger.error("dm organize failed: %s", e)
                client.chat_postMessage(channel=channel, text=f"エラー: {e}")
                return

            over = _build_overdue_blocks(org.get("plan") or {}, tasks, user_id)
            blocks = plan_blocks_from_api(org.get("plan") or {}, tasks) + over
            client.chat_postMessage(channel=channel, text="本日のプラン", blocks=blocks)
        except Exception as e:
            logger.error("handle_dm_message_events unexpected: %s", e)

    @slack_app.action("overdue_done")
    def handle_overdue_done(ack, body, client, logger):  # type: ignore
        ack()
        try:
            token = body.get("actions", [{}])[0].get("value")
            user_id = body.get("user", {}).get("id")
            entry = _OVERDUE_PROMPTS.pop(token, None)
            if not entry:
                return
            tid = int(entry.get("task_id"))
            tf.mark_done(tid)
            if user_id:
                ch = client.conversations_open(users=user_id)["channel"]["id"]
                client.chat_postMessage(channel=ch, text=f"✅ 完了として反映しました: #{tid} {entry.get('title')}")
        except Exception as e:
            logger.error("overdue_done failed: %s", e)

    @slack_app.action("overdue_reschedule")
    def handle_overdue_reschedule(ack, body, client, logger):  # type: ignore
        ack()
        try:
            token = body.get("actions", [{}])[0].get("value")
            user_id = body.get("user", {}).get("id")
            entry = _OVERDUE_PROMPTS.pop(token, None)
            if not entry:
                return
            tid = int(entry.get("task_id"))
            new_due = (date.today() + timedelta(days=1)).isoformat()
            tf.update_task(tid, due_date=new_due)
            if user_id:
                ch = client.conversations_open(users=user_id)["channel"]["id"]
                client.chat_postMessage(channel=ch, text=f"⏭️ リスケしました: #{tid} {entry.get('title')} → 期日 {new_due}")
        except Exception as e:
            logger.error("overdue_reschedule failed: %s", e)

    @slack_app.command("/tasks")
    def handle_tasks_summary_cmd(ack, body, client, logger):  # type: ignore
        """List tasks in due-date order with a quick summary."""
        ack()
        try:
            user_id = body.get("user_id")
            tasks = tf.list_tasks(status="all")
            from datetime import date
            today = date.today()
            # sort by due (None at end), then id
            def _key(t: dict):
                dd = t.get("due_date")
                return (dd is None, dd or "9999-12-31", int(t.get("id") or 0))
            tasks_sorted = sorted(tasks, key=_key)
            total = len(tasks_sorted)
            todo = sum(1 for t in tasks_sorted if (t.get("status") or "todo") == "todo")
            header = f"タスク一覧（期限順）: 総数 {total} / TODO {todo}"
            lines = []
            for i, t in enumerate(tasks_sorted[:20], start=1):
                due = t.get("due_date") or "-"
                pri = t.get("priority") or "-"
                st = t.get("status") or "-"
                title = t.get("title") or "(無題)"
                lines.append(f"{i}. [{pri}/{st}] {title} （期限: {due}）")
            text = "\n".join(lines) if lines else "（タスクがありません）"
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{header}*"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            ]
            if total > 20:
                blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"他 {total-20} 件。必要ならダッシュボードをご確認ください。"}]})
            ch = client.conversations_open(users=user_id)["channel"]["id"]
            client.chat_postMessage(channel=ch, text="タスク一覧（期限順）", blocks=blocks)
        except Exception as e:
            logger.error("/tasks failed: %s", e)


def send_daily_prompt(client, user_id: str) -> None:
    try:
        ch = client.conversations_open(users=user_id)["channel"]["id"]
        client.chat_postMessage(channel=ch, text="Daily check-in", blocks=checkin_prompt_blocks())
    except SlackApiError as e:
        log.error("send_daily_prompt failed for %s: %s", user_id, e)


def retry_spool_checkins():
    def handler(entry: dict) -> bool:
        try:
            tf.post_checkin(
                user=entry["user"],
                checkin_date=date.fromisoformat(entry["date"]),
                yesterday=entry.get("yesterday", ""),
                today=entry.get("today", ""),
                blockers=entry.get("blockers", ""),
                meta=entry.get("meta"),
            )
            return True
        except Exception as e:
            log.error("retry checkin failed: %s", e)
            return False
    spool.drain("checkins", handler)


def _start_scheduler():
    tz = "Asia/Tokyo"
    sched = BackgroundScheduler(timezone=tz)
    # 9:00 JST daily prompt
    if not SLACK_OFFLINE and slack_app is not None:
        sched.add_job(
            func=lambda: [send_daily_prompt(slack_app.client, uid) for uid in settings.daily_user_ids],
            trigger=CronTrigger(hour=settings.jst_hour, minute=settings.jst_minute),
            id="daily_checkin_prompt",
            replace_existing=True,
        )
    # Fallback auto-plan if no response by 10:00 JST
    if not SLACK_OFFLINE and slack_app is not None:
        sched.add_job(
            func=lambda: [
                slack_app.client.chat_postMessage(
                    channel=slack_app.client.conversations_open(users=uid)["channel"]["id"],
                    text="応答がないため自動プランを提案します",
                    blocks=plan_blocks_from_api(organize({
                        "free_text": "",
                        "today_hours": 0,
                        "dialog_entries": [],
                        "context": {"tasks": tf.list_tasks(status="all"), "checkins_recent": [], "events_recent": []}
                    }).get("plan") or {}, tf.list_tasks(status="all")) + _build_overdue_blocks(organize({
                        "free_text": "",
                        "today_hours": 0,
                        "dialog_entries": [],
                        "context": {"tasks": tf.list_tasks(status="all"), "checkins_recent": [], "events_recent": []}
                    }).get("plan") or {}, tf.list_tasks(status="all"), uid),
                ) for uid in settings.daily_user_ids
            ],
            trigger=CronTrigger(hour=settings.jst_hour + 1, minute=0),
            id="auto_plan_fallback",
            replace_existing=True,
        )
    # Retry spool every 5 minutes
    sched.add_job(retry_spool_checkins, trigger=CronTrigger(minute="*/5"), id="spool_retry", replace_existing=True)
    sched.start()
    log.info("Scheduler started (JST %02d:%02d)", settings.jst_hour, settings.jst_minute)


def create_app() -> Flask:
    # Avoid duplicate scheduler in Flask reloader
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not flask_app.debug:
        try:
            _start_scheduler()
        except Exception as e:
            log.error("scheduler start failed: %s", e)
    return flask_app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=settings.port)
