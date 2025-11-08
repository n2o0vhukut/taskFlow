TaskFlow 向け Slack DM ボット

Flask + Slack Bolt による最小構成のボットです。毎朝 9:00（JST）にDMでチェックインを依頼し、入力内容とTaskFlowのタスクから当日のプランを作成・返信します。

クイックスタート

1) 依存インストール

   python -m venv .venv && source .venv/bin/activate
   pip install -r slack_bot/requirements.txt

2) 環境変数（.env対応）

   # 推奨：dotenvファイルを作成（Git管理対象外）
   cp slack_bot/.env.example slack_bot/.env
   # 例（必要に応じて編集）
   # SLACK_BOT_TOKEN=xoxb-...
   # SLACK_SIGNING_SECRET=...
   # TASKFLOW_API_BASE_URL=http://127.0.0.1:8000
   # TASKFLOW_API_TOKEN=secret
   # DAILY_USER_IDS=UXXXXXXXX,UYYYYYYYY
   # USER_MAP_JSON={"UXXXXXXXX":"masato"}
   # OPENAI_API_KEY=sk-...
   # PORT=3000

3) TaskFlow API を起動（別プロセス）

   python -m taskflow init-db
   python -m taskflow api --host 127.0.0.1 --port 8000

4) Slack と接続するために公開（ngrok など）

   ngrok http 3000

   Slackアプリ側の設定:
   - Event Subscriptions: Request URL -> https://<ngrok>/slack/events
   - Interactivity & Shortcuts: Request URL -> https://<ngrok>/slack/events
   - Scopes: chat:write, im:write, commands

5) ボットを起動

   python -m slack_bot.app

注意事項

- 毎朝 09:00（JST）に `DAILY_USER_IDS` のユーザーへDMします
- モーダルで昨日/今日/ブロッカーを受け取り、TaskFlowへ反映
- プランを生成してDM返信
- 送信失敗は `slack_bot/spool/` にスプールし、5分毎に再送
- スラッシュコマンド:
  - `/plan [hours]` 本日のプランを表示（hours省略時は `DEFAULT_PLAN_HOURS` を使用）
  - `/tasks` タスク一覧（期限順、先頭20件）と要約

エンドツーエンドセットアップ（Slack連携）

Slack DM とスラッシュコマンドを含むフローを動かす手順です。

1) Slackアプリを作成

   - https://api.slack.com/apps → Create New App → From scratch
   - Basic Information → App Name は任意（例: TaskFlow Planner）、Workspace を選択

2) OAuthスコープとインストール

   - OAuth & Permissions → Scopes（Bot Token Scopes）に以下を追加:
     - `chat:write`（メッセージ送信）
     - `im:write`（DM作成）
     - `commands`（スラッシュコマンド）
   - Install App → Install to Workspace → 許可

3) Event/Interactivity のエンドポイント

   - Interactivity & Shortcuts → Enable → Request URL: `https://<ngrok>/slack/events`
   - Event Subscriptions → Enable → Request URL: `https://<ngrok>/slack/events`
     - （Boltはこの1エンドポイントで view_submission/アクション等を受けます）

4) スラッシュコマンド

   - Slash Commands → 新規コマンドを2つ作成:
     - `/plan` → Request URL: `https://<ngrok>/slack/events`
     - `/tasks` → Request URL: `https://<ngrok>/slack/events`
   - Short Description は任意（例: show today's plan / show tasks summary）

5) ローカルサービスの起動

   - Python仮想環境と依存
     - `python -m venv .venv && source .venv/bin/activate`
     - `pip install -U pip && pip install -e . && pip install -r slack_bot/requirements.txt`
   - TaskFlow API
     - `python -m taskflow init-db`
     - `python -m taskflow api --host 127.0.0.1 --port 8000`
   - Slack → ローカルボット(3000番)の公開（ngrok）
     - `ngrok http 3000`
     - 表示された `https://<ngrok>` を Slack の Request URL に設定

6) ボットの環境設定

   - `slack_bot/.env` を作成（dotenvは自動読み込み）
     - `SLACK_BOT_TOKEN=xoxb-...`（Bot User OAuth Token）
     - `SLACK_SIGNING_SECRET=...`（App Credentials）
     - `TASKFLOW_API_BASE_URL=http://127.0.0.1:8000`
     - `TASKFLOW_API_TOKEN=local`
     - `DAILY_USER_IDS=UXXXXXXXX`（毎朝DMの宛先。空でも可）
     - 任意: `PORT=3000`, `LOG_LEVEL=INFO`
     - 任意: `PREVIEW_BEFORE_APPLY=1`（プレビュー→「適用する」ボタン）
     - 任意: `DASHBOARD_URL=http://127.0.0.1:8501`（ダッシュボタン）

7) ボットを起動

   - `python -m slack_bot.app`
   - ヘルス確認: `curl http://127.0.0.1:3000/healthz` → `{ "ok": true, ... }`

8) Slack上で確認

   - DMで `/plan` → 本日のプラン
   - DMで `/tasks` → total/TODO/期限<=48h/今週 の要約
   - 毎朝9:00(JST) に `DAILY_USER_IDS` へチェックインDM（ボタン）
   - 手動テスト（後述）でDMを即時送信可

事前プレビュー → 適用（Dry‑Run → Apply）

- 既定（`PREVIEW_BEFORE_APPLY=1`）では、チェックイン後にプレビューDMを先に送ります:
  - 差分件数（add/update/done/defer）と当日プランを表示
  - 「適用する」ボタンを押すと差分を適用し、件数サマリを返信
- すぐ適用したい場合は以下を設定:

  export PREVIEW_BEFORE_APPLY=0

プランメッセージ（改善点）

- サマリ（合計時間・ブロック数・警告数）を冒頭に表示
- 各項目は「開始-終了/所要時間」「タイトル」「P/時間/期限/スコア」、理由（1行）を表示
- `DASHBOARD_URL` 設定時は「詳細を見る」ボタンを表示

重複処理（確認帯）

- 類似度≥0.8 は自動統合（既存にマージ）
- 0.7–0.8 はプレビューDMで確認:
  - 「統合する」→ 既存タスクへタイトルを統合（rename）
  - 「別タスク」→ 新規として扱う（プレビュー保留中のaddに連結）

オフラインモード（Slackトークン不要）

- Slackトークンが無くてもローカル検証可能:

  export SLACK_OFFLINE=1

- Slack初期化とDMスケジュールを無効化。`/ai/organize` `/ai/apply` は利用可。

シークレットの取り扱い

- ルートと `slack_bot/.env` を自動読み込み（dotenv）
- `.gitignore` により `.env` はコミット対象外

リハーサル（Slack操作なしで動作確認）

- 任意の管理トークンを設定:

  export ADMIN_TOKEN=localtest

- DMプロンプトを即時送信:

  curl -X POST http://127.0.0.1:3000/admin/trigger \
    -H 'Content-Type: application/json' \
    -H 'X-Admin-Token: localtest' \
    -d '{"type":"prompt","user":"UXXXXXXXX"}'

- スプール再送を起動:

  curl -X POST http://127.0.0.1:3000/admin/trigger \
    -H 'Content-Type: application/json' \
    -H 'X-Admin-Token: localtest' \
    -d '{"type":"drain"}'

- 指定ユーザーへプランDMを送信:

  curl -X POST http://127.0.0.1:3000/admin/trigger \
    -H 'Content-Type: application/json' \
    -H 'X-Admin-Token: localtest' \
    -d '{"type":"plan","user":"UXXXXXXXX"}'

OpenAI を使う（任意）

- ヒューリスティックの代わりにLLMで organize/apply を行う設定:

  export OPENAI_API_KEY=sk-...
  export OPENAI_MODEL=gpt-4o-mini   # 例: gpt-4o, o3-mini など
  export OPENAI_TEMPERATURE=0.2
  export OPENAI_MAX_TOKENS=2000
  # Azureやプロキシを使う場合:
  # export OPENAI_BASE_URL=https://your-endpoint/v1

- 失敗時はヒューリスティックへ自動フォールバックします。

オフライン/ローカル検証

- Slackを使わずUIで試す:

  export SLACK_OFFLINE=1

- 起動後に `http://127.0.0.1:3000/ui` を開く
- 「Use current DB tasks」をONにすると、ローカルの TaskFlow API からタスクを取得

トラブルシューティング

- 127.0.0.1:3000 に繋がらない → 既に使用中。`PORT=3001 python -m slack_bot.app`
- Slackが Bad request URL → ngrok のURLを Slack App 設定（Interactivity/Events/Slash）に再設定
- `/plan` `/tasks` が反応しない → Slash Commands の Request URL を `/slack/events` にしているか確認
- OpenAI未設定 → organizeはヒューリスティックで動作（UIの engine 行で確認）

ダッシュボードリンク（任意）

- プランDMに「詳細を見る」ボタンを出す場合:

  export DASHBOARD_URL=http://127.0.0.1:8501

- 付属のStreamlitダッシュボードを起動:

  streamlit run app/dashboard.py
