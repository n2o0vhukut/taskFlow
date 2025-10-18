# TaskFlow Ops (P0)

最小実装のパッケージ化、CLI、Flask API、将来のChatGPT連携フックを提供します。

## 要件
- Python 3.11+
- SQLite (同梱)

## インストール（開発向け）
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## 初期化と基本コマンド
```bash
# DB初期化
python -m taskflow init-db

# タスク登録/一覧/完了/削除
python -m taskflow add --title "統計検定 過去問3セット" --due 2025-10-25 --est 2 --project 資格 --priority H
python -m taskflow list [--status todo|doing|done|all] [--project <name>] [--due-before YYYY-MM-DD]
python -m taskflow done <task_id>
python -m taskflow rm <task_id>

# エクスポート（CSV）
python -m taskflow export --format csv --out data/tasks_YYYYMMDD.csv
```

## Flask API（開発サーバ）
```bash
python -m taskflow api --host 127.0.0.1 --port 5000 --debug
```

エンドポイント（P0）
- GET /health → {"status":"ok"}
- GET /tasks （クエリ: status, project, due_before）
- POST /tasks （JSON: title, project?, priority?, estimate_hours?, due_date?）
- GET /tasks/<id>
- PATCH /tasks/<id>
- DELETE /tasks/<id>
- POST /search （JSON: q）
- POST /webhooks/events （受領ログのみ）
- POST /chat/completions （ダミー echo 応答）

## 環境変数
- TASKFLOW_DB_PATH: DBファイルのパス（未設定時は ./data/taskflow.db）

## テスト
```bash
pytest -q
```

## メモ
- P0は最小構成です。P1でAlembic, 認証, バリデーション, Lint/CI等を拡充します。

## 詳細設計
- アーキテクチャの骨子と拡張方針は `docs/ARCHITECTURE.md` を参照してください。
