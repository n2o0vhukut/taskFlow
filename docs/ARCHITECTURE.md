# TaskFlow Ops — アーキテクチャ概要（P0）

本ドキュメントは、最小実装（P0）の設計骨子です。CLIとFlask APIの構造、DBモデル、拡張方針を俯瞰できます。

## 目的 / スコープ
- 目的: 最小構成で「パッケージ化」「CLI」「Flask API」「将来のChatGPT連携フック」を提供。
- 非目標（P0）: 本番のChatGPT連携、認証、マイグレーション運用、UI、SSE/WS。

## 技術スタック
- 言語: Python 3.11+
- ランタイム: Flask (API), argparse (CLI)
- DB: SQLite（ファイルDB） + SQLAlchemy (ORM)
- テスト: pytest（スモーク）

## ディレクトリ構成（主な箇所）
```
src/taskflow/
  __main__.py         # `python -m taskflow` エントリ
  cli.py              # CLI実装（argparse）
  api/
    app.py            # Flaskアプリ工場 + /health
    routes.py         # APIルート群（/tasks, /search, /webhooks/events, /chat/completions）
  db/
    session.py        # エンジン/Session生成、DBパス解決
    models.py         # ORMモデル（Task）
    init.py           # DB初期化（create_all + 互換ALTER）
  services/
    tasks.py          # タスクCRUD/一覧/CSVエクスポート
    search.py         # 検索（title/project 部分一致）
    chat.py           # Chatダミー（echo）
```

## レイヤーと依存関係
- CLI層（`cli.py`）/ API層（`api/*`）
  - 入力（引数/HTTP）を受け取り、サービス層を呼び出す。
- サービス層（`services/*`）
  - ビジネスロジック（CRUD/検索/出力）を実装。DB層への依存のみ。
- DB層（`db/*`）
  - SQLAlchemyのSession/EngineとORMモデル、初期化を提供。
- 依存方向: CLI・API → Services → DB → SQLite

## データモデル（P0）
- テーブル: `tasks`
  - `id` INTEGER PK
  - `title` TEXT NOT NULL
  - `project` TEXT NULL
  - `priority` TEXT NOT NULL in {'H','M','L'}（既定 'M'）
  - `estimate_hours` REAL NULL
  - `due_date` DATE NULL（ISO8601）
  - `status` TEXT NOT NULL in {'todo','doing','done'}（既定 'todo'）
  - `created_at` DATETIME NOT NULL（server_default now）
  - `updated_at` DATETIME NOT NULL（onupdate now）
- 実装: `src/taskflow/db/models.py` の `Task` クラス

## サービス層
- `services/tasks.py`
  - `add_task`/`list_tasks`/`get_task`/`update_task`/`mark_done`/`remove_task`
  - `export_tasks_csv(tasks, out_path)`
- `services/search.py`
  - `search_tasks(q)`（title, project のLIKE）
- `services/chat.py`
  - `echo_completion(payload)`（末尾のユーザ発話をecho）

## API 仕様（P0）
- `GET /health` → `{ "status": "ok" }`
- `GET /tasks`（query: `status`, `project`, `due_before`）
- `POST /tasks`（JSON: `title`, `project?`, `priority?`, `estimate_hours?`, `due_date?`）
- `GET /tasks/<id>`
- `PATCH /tasks/<id>`（任意フィールド更新）
- `DELETE /tasks/<id>`
- `POST /search`（JSON: `q`）
- `POST /webhooks/events`（受領ログのみ）
- `POST /chat/completions`（ダミー echo 応答）
- 実装: `src/taskflow/api/app.py`, `src/taskflow/api/routes.py`

## CLI 仕様（P0）
- 実行: `python -m taskflow`
- サブコマンド:
  - `init-db`
  - `add --title --project? --priority [H/M/L] --est? --due?`
  - `list [--status todo|doing|done|all] [--project] [--due-before]`
  - `done <task_id>`
  - `rm <task_id>`
  - `export --format csv --out <path> [--status] [--project]`
  - `api [--host 127.0.0.1] [--port 5000] [--debug]`
- 実装: `src/taskflow/cli.py`

## 設定 / 環境変数
- `TASKFLOW_DB_PATH`: DBファイルパス（相対可、既定: `./data/taskflow.db`）
- `TASKFLOW_SQL_ECHO`: SQLログ出力（'1'/'true' で有効）
- 読み取り: `src/taskflow/db/session.py`

## エラーハンドリング（最小）
- API: 400（必須欠如）、404（対象なし）を最小実装。500はFlask標準。
- CLI: 失敗時は終了コード非0（1/2）。

## テスト（スモーク）
- CLI: init/add/list/done/export の一連をtmp DBで検証
- API: health/CRUD/search/webhook/chat を通しで確認
- 実行: `pytest -q`

## 既存DB互換
- `init-db` で不足列（`estimate_hours`/`due_date`/`status`）を安全に追加。
- 旧列（`est_hours`/`due`）からのデータ移行はP1で別途対応予定。

## 開発フロー（推奨）
1. venvを有効化し `pip install -e .`、`pytest -q` でベースライン確認
2. 変更: services → api/cli の順で追加し、小さくテスト
3. DB変更はP1でAlembic導入、P0では互換ALTERのみ
4. ドキュメントとスモークテストをセットで更新

## P1 ロードマップ（提案）
- ChatGPT本接続（OpenAI SDK、APIキー、リトライ/タイムアウト）
- Alembicマイグレーション（旧列→新列移行）
- 認証/CORS（JWT + CORS設定）
- 入力バリデーション（Pydantic）と例外ハンドラ整備
- Lint/Format/CI（Ruff/Black、pre-commit、GitHub Actions）
- Export拡張（JSON/Markdown、フィルタ）
- 観測性（構造化ログ、簡易メトリクス）
- チャットSSE骨格

## 直近TODO（小粒）
- `/tasks` に `limit/offset` パラメータ追加（ページング）
- APIの400応答メッセージ整形とスキーマ記述
- `datetime.utcnow()` の非推奨置換（`datetime.now(datetime.UTC)`）
- READMEにAPIサンプルcurl追記
