from __future__ import annotations

import logging
import os
from datetime import datetime, date

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
            blocks = plan_blocks_from_api(plan)
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

            # Apply mutations to TaskFlow (idempotent-ish per engine design)
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

            # Render plan
            blocks = plan_blocks_from_api(org.get("plan") or {})

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
            d = date.today()
            tasks = tf.list_tasks(status="all")
            org = organize({
                "free_text": "",
                "today_hours": 0,
                "dialog_entries": [],
                "context": {"tasks": tasks, "checkins_recent": [], "events_recent": []},
            })
            blocks = plan_blocks_from_api(org.get("plan") or {})
            ch = client.conversations_open(users=user_id)["channel"]["id"]
            client.chat_postMessage(channel=ch, text="本日のプラン", blocks=blocks)
        except Exception as e:
            logger.error("/plan failed: %s", e)


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
                    }).get("plan") or {}),
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
