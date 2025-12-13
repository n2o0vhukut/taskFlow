# 運用手順（OPERATIONS）

前提
- Python 3.11+
- Slack App（Bot Token, Signing Secret）、ngrok等の公開URL

セットアップ
1) 仮想環境・依存
```
python -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -e . && pip install -r slack_bot/requirements.txt
```

2) TaskFlow API（別ターミナル）
```
python -m taskflow init-db
python -m taskflow api --host 127.0.0.1 --port 8000
```

3) Slack 公開URL（ngrok）
```
ngrok http 3000
```
Slack App 設定: Interactivity/Events/Slash の Request URL を `https://<ngrok>/slack/events` に設定。

4) 環境変数（slack_bot/.env）
- 必須: `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `TASKFLOW_API_BASE_URL`, `TASKFLOW_API_TOKEN`
- 任意: `PREVIEW_BEFORE_APPLY=1`, `DASHBOARD_URL=...`, `SHOW_TIME_SLOTS=1`, `DAILY_USER_IDS=...`

5) ボット起動
```
PORT=3000 python -m slack_bot.app
```
ヘルス: `curl http://127.0.0.1:3000/healthz`

Slack操作
- `/plan` でプラン表示、`/tasks` で要約
- 9:00にチェックインDM → モーダル送信 → プレビューDM（適用ボタン）
- 10:00に自動プラン（無応答時）

トラブルシュート
- Bad request URL: ngrokドメインを最新にし、末尾が`/slack/events`か確認
- 3000番が使用中: `PORT=3001 python -m slack_bot.app`
- LLM未設定: organizeはヒューリスティックで動作

