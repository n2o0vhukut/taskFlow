Slack DM Bot for TaskFlow

Minimal Flask + Slack Bolt bot that DMs users at 9:00 JST daily to collect check-ins, updates TaskFlow, and returns a daily plan.

Quick start

1) Install deps

   python -m venv .venv && source .venv/bin/activate
   pip install -r slack_bot/requirements.txt

2) Environment (.env supported)

   # Create a dotenv file (recommended; not committed)
   cp slack_bot/.env.example slack_bot/.env
   # Edit slack_bot/.env and set values, e.g.:
   # SLACK_BOT_TOKEN=xoxb-...
   # SLACK_SIGNING_SECRET=...
   # TASKFLOW_API_BASE_URL=http://127.0.0.1:8000
   # TASKFLOW_API_TOKEN=secret
   # DAILY_USER_IDS=UXXXXXXXX,UYYYYYYYY
   # USER_MAP_JSON={"UXXXXXXXX":"masato"}
   # OPENAI_API_KEY=sk-...
   # PORT=3000

3) Run TaskFlow API (separately)

   python -m taskflow.api

4) Expose bot to Slack (ngrok or cloud)

   ngrok http 3000

   In Slack app settings:
   - Event Subscriptions: Request URL -> https://<ngrok>/slack/events
   - Interactivity & Shortcuts: Request URL -> https://<ngrok>/slack/events
   - Scopes: chat:write, im:write, users:read

5) Run bot

   python -m slack_bot.app

Notes

- Daily DM at JST 09:00 to users in DAILY_USER_IDS
- Modal collects yesterday/today/blockers and pushes to TaskFlow /checkins
- On success fetches /plan and posts it back in DM
- Failed TaskFlow submissions are spooled to slack_bot/spool/ and retried every 5 minutes
- Slash commands:
  - `/plan` shows today's plan
  - `/tasks` shows a quick summary (total/TODO/due<=48h/this week)

Plan message (improved)

- Shows summary: total hours, block count, alert count
- Each item displays start-end, title, priority/due/hours/score, and a brief reason
- Optional "View details" button appears when `DASHBOARD_URL` is set (see below)

Offline mode (no Slack tokens)

- For local AI API testing without valid Slack tokens, set:

  export SLACK_OFFLINE=1

- This disables Slack initialization and scheduling of DM jobs. `/ai/organize` and `/ai/apply` remain usable.

Notes on secrets

- `.env` loading is automatic from project root and `slack_bot/.env`.
- `.gitignore` excludes `.env` files to prevent accidental commits.

Rehearsal (no Slack clicks required)

- Optional admin token for triggers:

  export ADMIN_TOKEN=localtest

- Trigger DM prompt immediately (instead of waiting for 09:00 JST):

  curl -X POST http://127.0.0.1:3000/admin/trigger \
    -H 'Content-Type: application/json' \
    -H 'X-Admin-Token: localtest' \
    -d '{"type":"prompt","user":"UXXXXXXXX"}'

- Force spool drain retry:

  curl -X POST http://127.0.0.1:3000/admin/trigger \
    -H 'Content-Type: application/json' \
    -H 'X-Admin-Token: localtest' \
    -d '{"type":"drain"}'

- Send plan DM for a user:

  curl -X POST http://127.0.0.1:3000/admin/trigger \
    -H 'Content-Type: application/json' \
    -H 'X-Admin-Token: localtest' \
    -d '{"type":"plan","user":"UXXXXXXXX"}'

Use OpenAI (optional)

- Enable LLM-based organize/apply instead of heuristics by setting:

  export OPENAI_API_KEY=sk-...
  export OPENAI_MODEL=gpt-4o-mini   # or gpt-4o, o3-mini, etc.
  export OPENAI_TEMPERATURE=0.2
  export OPENAI_MAX_TOKENS=2000
  # If using Azure or a proxy:
  # export OPENAI_BASE_URL=https://your-endpoint/v1

- With these set, the bot will call OpenAI during organize. On failure it falls back to heuristic engine.

Dashboard link (optional)

- To show a "View details" button in plan DMs, set a public URL for your dashboard:

  export DASHBOARD_URL=http://127.0.0.1:8501

- You can run the provided Streamlit dashboard locally:

  streamlit run app/dashboard.py
