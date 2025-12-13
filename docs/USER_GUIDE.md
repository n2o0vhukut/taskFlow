# TaskFlow Slack AI Planner 取扱説明書

この文書は、初心者の方でも迷わずにセットアップ・利用できることを目的としたユーザー向けガイドです。Slack のDMで毎朝の進捗を入力すると、AIがタスク整理と当日プラン（ブロック計画）を自動生成して返信します。

---

## 1. できること（概要）
- 9:00（JST）にボットがDMで「チェックイン」を依頼（ボタン→モーダル入力）
- 入力（昨日/今日/可処分時間/不可時間/ブロッカー）からAIが整理
  - 新規タスク抽出、重複統合、優先度再評価、期限リスク警告
  - 可処分時間に収まるブロック計画（0.5–2.0h）を生成
- 差分（add/update/done/defer）をTaskFlow DBへ自動反映
- 日中は `/plan` で再計画をいつでも確認

---

## 2. 前提・要件
- macOS / Linux（Python 3.11+ 推奨）
- Slack ワークスペース（Bot アプリを作成できる権限）
- OpenAI API キー（試験利用は安価モデル gpt-4o-mini を推奨／任意）
- ngrok（ローカルをインターネット公開する場合に使用）

---

## 3. セットアップ（最短）
1) 依存インストール（仮想環境を推奨）
```
python -m venv .venv && source .venv/bin/activate
pip install -r slack_bot/requirements.txt
```

2) .env の作成（秘密はGitにコミットしない）
```
cp slack_bot/.env.example slack_bot/.env
# 必要に応じて編集（例）
# Slackなしで検証: SLACK_OFFLINE=1
# TaskFlow API: TASKFLOW_API_BASE_URL=http://127.0.0.1:8000, TASKFLOW_API_TOKEN=dev
# OpenAI: OPENAI_API_KEY=sk-... , OPENAI_MODEL=gpt-4o-mini
# ポート: PORT=3000
```

3) TaskFlow API を起動
```
python -m taskflow api --port 8000
```

4) ボット（サーバ）を起動
```
python -m slack_bot.app
# 既に 3000 が使われている場合: PORT=3001 python -m slack_bot.app
```

5) OpenAI 接続の確認（任意）
- ブラウザで `http://127.0.0.1:<PORT>/ui` を開き「Run organize」
- 画面に `engine: openai` が出れば OpenAI 経由で動作
- 監査ログ: `tail -n 5 data/ai_audit.jsonl` に `"source":"openai"` が出れば裏側もOK

---

## 4. Slack 連携（本番利用）
1) Slackアプリ（Bot）設定
- Scopes（Bot）: `chat:write`, `im:write`, `commands`
- Interactivity & Shortcuts: `https://<ngrok>/slack/events`
- Slash Command `/plan`: `https://<ngrok>/slack/events`
- ワークスペースにインストール

2) サーバの設定
- `slack_bot/.env` に実トークン設定：
  - `SLACK_BOT_TOKEN=xoxb-...`
  - `SLACK_SIGNING_SECRET=...`
  - `SLACK_OFFLINE` は未設定（Slack接続を有効化）
- `ngrok http <PORT>` を起動、上記URLに登録

3) 試運転
- 即時DM送信（9時待たずに）
```
curl -X POST http://127.0.0.1:<PORT>/admin/trigger \
  -H 'Content-Type: application/json' \
  -d '{"type":"prompt","user":"UXXXXXXXX"}'
```
- DMの「チェックインを入力」→ モーダル送信 → 当日プランがDMで返る

---

## 5. 毎日の使い方（通常運用）
- 9:00（JST）にDMが届く → ボタン→モーダルで入力
  - 今日の可処分時間（h）
  - 昨日やったこと／今日やること（自由記述）
  - ブロッカー（任意）
  - 不可時間/会議（例: `10:00-11:00`）
- 送信直後、AIが整理→DB反映→ブロック計画をDM返信
- 無応答の場合、10:00に自動プラン（DBベース）をDM

---

## 6. 日中の再計画・手動操作
- 再計画を確認: Slackで `/plan`
- 即時DM（モーダル）を再送: 管理トリガ
```
curl -X POST http://127.0.0.1:<PORT>/admin/trigger \
  -H 'Content-Type: application/json' \
  -d '{"type":"prompt","user":"UXXXXXXXX"}'
```
- そのユーザーへプランだけDM: `{"type":"plan","user":"U..."}`
- スプール再送（TaskFlow障害復旧後）: `{"type":"drain"}`

---

## 7. OpenAI とコスト上限
- 試験運用は安価モデル `gpt-4o-mini` を推奨
- 予算上限制御（任意/推奨）
```
export OPENAI_API_KEY=sk-...
export MAX_USD_LIMIT=20.0
python check_usage_limit.py  # 上限超過ならエラー終了
```
- 運用では、アプリ起動前（または日次cron）で `check_usage_limit.py` を実行してください

---

## 8. ダッシュボード（任意）
- DBの中身を簡易表示：
```
streamlit run app/dashboard.py
```
- タスク一覧／イベント履歴（存在すれば）／チェックインの簡易可視化

---

## 9. よくあるトラブル
- `invalid_auth`（Slack）
  - トークンや Request URL の設定不備。ローカル検証は `SLACK_OFFLINE=1` で回避
- `engine: heuristic` のまま（/ui）
  - `OPENAI_API_KEY` 未設定、FW/プロキシ、モデル未対応など。`data/ai_audit.jsonl` を確認
- ポート競合
  - `PORT=3001 python -m slack_bot.app` など、空いているポートを使用
- TaskFlowに `/checkins` が無い
  - このリポのローカルAPIは `/tasks` のみ。チェックインはスプール保存、計画はボット内AIで生成

---

## 10. データとログの場所
- 監査ログ: `data/ai_audit.jsonl`
- 送信失敗スプール: `slack_bot/spool/`
- DB（SQLite）: 既定は `data/taskflow.db`（環境により異なる）

---

## 11. セキュリティの注意
- `.env` に秘密（Slack/OpenAIキー）を保存。Gitにコミットしない
- ログに本文やキーを出力しない方針（既定設定）
- 必要に応じてキーの定期ローテーションを実施

---

## 12. エンドポイント早見表（ボット）
- `GET /` … 簡易情報（`openai_enabled` など）
- `GET /healthz` … ヘルス
- `GET/POST /ui` … テストフォーム（OpenAI疎通）
- `POST /ai/organize` … AI整理API
- `POST /ai/apply` … DB反映API
- `POST /admin/trigger` … 管理トリガ（`prompt`/`plan`/`drain`）
- `POST /slack/events` … Slack 連携（本番運用時）

---

## 13. 環境変数（主なもの）
- Slack: `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_OFFLINE`
- TaskFlow: `TASKFLOW_API_BASE_URL`, `TASKFLOW_API_TOKEN`
- OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TEMPERATURE`, `OPENAI_MAX_TOKENS`, `MAX_USD_LIMIT`
- Bot: `DAILY_USER_IDS`, `USER_MAP_JSON`, `JST_HOUR`, `JST_MINUTE`, `PORT`, `LOG_LEVEL`

---

## 14. 困ったら
- まずは `/ui` で organize を実行し、`engine: openai` を確認
- `data/ai_audit.jsonl` を tail して判断ログを確認
- Slack の場合は ngrok URL とスコープの再確認
- それでも解決しない場合は、起動ログ（エラー全文）と .env の（秘密を伏せた）値を共有してください

