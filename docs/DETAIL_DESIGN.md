# 詳細設計（DETAIL DESIGN）

この文書は、API仕様・内部アルゴリズム・メッセージ設計・スケジューラの詳細、ならびにクラス/メソッド粒度のシーケンス図を提供します。

1. API仕様（Bot内）
- POST /ai/organize
  - 入力: `{ free_text, today_hours, dialog_entries[], context{ tasks[], checkins_recent[], events_recent[] } }`
  - 出力: `{ plan{ total_hours, blocks[start,end,hours,title,reason_summary,...], alerts, advice }, mutations{ add/update/done/defer }, dedupe[], audit{} }`
  - 実装: `slack_bot.ai_engine.organize(payload)` →（必要時）`slack_bot.llm_client.organize_with_openai`

- POST /ai/apply
  - 入力: `{ mutations{ add/update/done/defer }, reason }`
  - 出力: `{ applied[], errors[] }`
  - 実装: `slack_bot.ai_engine.apply_mutations(mutations, apply_fn)` で `apply_fn` 経由で `slack_bot.taskflow_client.TaskFlowClient` の CRUD を呼ぶ

- POST /admin/trigger
  - 入力: `{type:"prompt"|"drain"|"plan", user?}` / Header: `X-Admin-Token`
  - 実装: `slack_bot.app.admin_trigger`

2. API仕様（TaskFlow）
- GET /tasks, POST /tasks, GET/PATCH/DELETE /tasks/{id}
  - 実装（Flask）: `src/taskflow/api/routes.py` → サービス層 `src/taskflow/services/tasks.py` → ORM `src/taskflow/db/models.py`

3. アルゴリズム（organize 概要）
- 正規化: NFKC → 小文字化 → 記号除去 → トークン化
- 重複判定: Jaccard類似度（merge≧0.8、review[0.7–0.8)）
- 優先度スコア: priority(H/M/L) + 期限の切迫度 + 連続・ブロッカー調整（±2以内）
- スケジューリング: 09:00開始、0.5–2.0hで配置、不可時間を回避、連続2本まで、today_hours+15%以内

4. メッセージ設計（Block Kit 要点）
- `slack_bot.block_kit.plan_blocks_from_api(plan, tasks)` がDMを組み立てる。
- セクション: サマリ、全体タスク、期限切れ、今日のタスク（開始/終了 or 所要時間、期限、理由）、アドバイス、アラート、（任意）詳細ボタン。

5. スケジューラ/ジョブ
- 09:00 DMプロンプト、10:00 自動プラン、5分おきスプール再送。
- 実装: `slack_bot.app._start_scheduler()`（APScheduler）。

6. 詳細シーケンス図（クラス/メソッド粒度）

6.1 チェックイン→プレビュー→適用
```mermaid
sequenceDiagram
  actor User
  participant Slack
  participant Bolt as slack_bolt.App
  participant App as slack_bot.app
  participant TFc as taskflow_client.TaskFlowClient
  participant AI as ai_engine.organize
  participant LLM as llm_client.organize_with_openai
  participant BK as block_kit.plan_blocks_from_api
  participant TF as TaskFlow API

  User->>Slack: view_submission
  Slack->>Bolt: /slack/events (view_submission)
  Bolt->>App: handle_checkin_modal
  App->>TFc: list_tasks()
  TFc->>TF: GET /tasks
  TF-->>TFc: 200 [tasks]
  App->>AI: organize({free_text,today_hours,tasks})
  alt OPENAI有効
    AI->>LLM: organize_with_openai(payload)
    LLM-->>AI: plan/mutations/dedupe/audit
  end
  App->>BK: plan_blocks_from_api(plan,tasks)
  App-->>Slack: プレビューDM（apply_mutations_now / dedupe_* / overdue_*）
  User->>Slack: action(apply_mutations_now)
  Slack->>Bolt: /slack/events (action)
  Bolt->>App: handle_apply_mutations_now
  loop mutations
    App->>TFc: add/update/done/defer
    TFc->>TF: /tasks CRUD
    TF-->>TFc: 200/4xx
  end
  App-->>Slack: 結果サマリDM
```

6.2 `/plan` 実行
```mermaid
sequenceDiagram
  actor User
  participant Slack
  participant Bolt as slack_bolt.App
  participant App as slack_bot.app
  participant TFc as taskflow_client.TaskFlowClient
  participant AI as ai_engine.organize
  participant BK as block_kit.plan_blocks_from_api
  participant TF as TaskFlow API
  User->>Slack: /plan
  Slack->>Bolt: /slack/events (slash)
  Bolt->>App: handle_plan_cmd
  App->>TFc: list_tasks()
  TFc->>TF: GET /tasks
  TF-->>TFc: 200
  App->>AI: organize({tasks})
  App->>BK: plan_blocks_from_api(plan,tasks)
  App-->>Slack: プランDM（overdueセクション含む）
```

6.3 10:00 自動プラン
```mermaid
sequenceDiagram
  participant Sched as APScheduler
  participant App as slack_bot.app
  participant TFc as taskflow_client.TaskFlowClient
  participant TF as TaskFlow API
  participant AI as ai_engine.organize
  participant BK as block_kit.plan_blocks_from_api
  participant Slack
  Sched->>App: cron(10:00)
  App->>TFc: list_tasks()
  TFc->>TF: GET /tasks
  TF-->>TFc: 200 [tasks]
  App->>AI: organize({today_hours:0,tasks})
  App->>BK: plan_blocks_from_api(plan,tasks)
  App-->>Slack: プランDM（overdueセクション含む）
```

6.4 Bot内API（/ai/organize）
```mermaid
sequenceDiagram
  participant Flask as slack_bot.app.ai_organize
  participant AI as slack_bot.ai_engine.organize
  participant LLM as slack_bot.llm_client.organize_with_openai
  Flask->>AI: organize(payload)
  alt OPENAI有効
    AI->>LLM: organize_with_openai(payload)
    LLM-->>AI: plan/mutations/dedupe/audit
  end
  AI-->>Flask: JSON
```

6.5 Bot内API（/ai/apply）
```mermaid
sequenceDiagram
  participant Flask as slack_bot.app.ai_apply
  participant Apply as slack_bot.ai_engine.apply_mutations
  participant TFc as slack_bot.taskflow_client.TaskFlowClient
  participant TF as TaskFlow API
  Flask->>Apply: apply_mutations(mutations, apply_fn)
  loop each mutation
    Apply->>TFc: add/update/done/defer
    TFc->>TF: /tasks CRUD
    TF-->>TFc: 200/4xx
  end
  Apply-->>Flask: {applied[],errors[]}
```

6.6 Slackアクション: apply_mutations_now
```mermaid
sequenceDiagram
  participant Bolt as slack_bolt.App
  participant App as slack_bot.app.handle_apply_mutations_now
  participant TFc as slack_bot.taskflow_client.TaskFlowClient
  participant TF as TaskFlow API
  Bolt->>App: action(apply_mutations_now)
  loop each mutation
    App->>TFc: add/update/done/defer
    TFc->>TF: /tasks CRUD
    TF-->>TFc: 200/4xx
  end
  App-->>Bolt: chat.postMessage(件数サマリ)
```

6.7 Slackアクション: overdue_done/overdue_reschedule
```mermaid
sequenceDiagram
  participant Bolt as slack_bolt.App
  participant App as slack_bot.app
  participant TFc as slack_bot.taskflow_client.TaskFlowClient
  participant TF as TaskFlow API
  alt overdue_done
    Bolt->>App: action(overdue_done)
    App->>TFc: mark_done(id)
    TFc->>TF: PATCH /tasks/{id} status=done
    TF-->>TFc: 200
    App-->>Bolt: chat.postMessage(完了反映)
  else overdue_reschedule
    Bolt->>App: action(overdue_reschedule)
    App->>TFc: update_task(id, due_date=+1day)
    TFc->>TF: PATCH /tasks/{id}
    TF-->>TFc: 200
    App-->>Bolt: chat.postMessage(期日を更新)
  end
```

6.8 TaskFlow API: /tasks
```mermaid
sequenceDiagram
  participant Flask as taskflow.api.routes
  participant Svc as taskflow.services.tasks
  participant ORM as taskflow.db.models/Session
  Flask->>Svc: list_tasks(status, project, due_before)
  Svc->>ORM: SELECT Task ... ORDER BY due_date
  ORM-->>Svc: rows
  Svc-->>Flask: [Task]
```

6.9 TaskFlow API: POST /tasks
```mermaid
sequenceDiagram
  participant Flask as taskflow.api.routes.create_task
  participant Svc as taskflow.services.tasks.add_task
  participant ORM as SQLAlchemy(Session/Task)
  Flask->>Svc: add_task(title, ...)
  Svc->>ORM: INSERT INTO tasks
  ORM-->>Svc: id
  Svc-->>Flask: Task
```

6.10 TaskFlow API: PATCH /tasks/{id}
```mermaid
sequenceDiagram
  participant Flask as taskflow.api.routes.patch_task
  participant Svc as taskflow.services.tasks.update_task
  participant ORM as SQLAlchemy(Session/Task)
  Flask->>Svc: update_task(id, fields)
  Svc->>ORM: UPDATE tasks SET ... WHERE id
  ORM-->>Svc: ok
  Svc-->>Flask: Task
```

6.11 Slack: /slack/events（/plan）
```mermaid
sequenceDiagram
  participant Bolt as slack_bolt.App
  participant App as slack_bot.app.handle_plan_cmd
  participant TFc as slack_bot.taskflow_client.TaskFlowClient
  participant AI as slack_bot.ai_engine.organize
  participant BK as slack_bot.block_kit.plan_blocks_from_api
  participant TF as TaskFlow API
  Bolt->>App: slash:/plan
  App->>TFc: list_tasks()
  TFc->>TF: GET /tasks
  TF-->>TFc: 200 [tasks]
  App->>AI: organize({tasks})
  App->>BK: plan_blocks_from_api(plan,tasks)
  App-->>Bolt: chat.postMessage(blocks)
```


7. データスキーマ詳細（tasks）
- priority: 'H'|'M'|'L'（CHECK制約）。
- status: 'todo'|'doing'|'done'（CHECK制約）。
- due_date: ISO日付（NULL可）。

8. バリデーションとエラー
- /ai/organize: today_hoursは数値。必須フィールド欠落は400/422相当。
- /ai/apply: 未知のmutationはエラー配列に格納しつつ処理継続。

9. Check-in Modal v2（タスク進捗入力 + 新規追加）

目的
- 現状の自由記述中心の入力から、既存タスクの進捗/状態/期日を直接編集できるUIへ拡張する。同時に新規タスクを追加可能にする。

構成（Block Kit 概要）
- セクションA: 今日の可処分時間（数値）
- セクションB: 既存タスク（上位N件）
  - 表示対象の例: 期限が近い順、doing優先、H優先、最大N=10
  - 各行: タイトル（表示のみ）/ 状態（todo/doing/done セレクト）/ 期日（plain_text_input YYYY-MM-DD）/ （任意）メモ
- セクションC: 新規タスク追加（可変個数、最大M=5）
  - 各行: タイトル（text）/ 期限（text YYYY-MM-DD）/ 優先（H/M/L セレクト）/ 見積（数値）
- セクションD: 自由記述（任意。抽出/重複統合の補助として維持）

データ化（送信時）
- `checkin_v2.progress[]`: `{id, status?, due_date?, note?}`… 既存タスクの更新意図
- `checkin_v2.add[]`: `{title, priority?, estimate_hours?, due_date?}`… 新規追加
- `today_hours`: 数値
- `free_text`: 任意

適用フロー
```mermaid
sequenceDiagram
  participant Bolt as slack_bolt.App
  participant App as slack_bot.app.handle_checkin_modal
  participant TFc as taskflow_client.TaskFlowClient
  participant AI as ai_engine.organize
  participant BK as block_kit.plan_blocks_from_api
  Note over Bolt,App: モーダル送信（v2）
  App->>App: checkin_v2.progress を mutations.update/done/defer に変換
  App->>App: checkin_v2.add を mutations.add に変換
  alt PREVIEW_ON
    App-->>Bolt: プレビューDM（件数 + plan + 重複review + overdue確認 + 「適用する」）
  else PREVIEW_OFF
    App->>TFc: /tasks CRUD（update/add/done）
  end
  App->>AI: organize({today_hours, free_text, tasks})
  App->>BK: plan_blocks_from_api(plan,tasks)
  App-->>Bolt: プランDM
```

備考
- タスク数が多い場合は上位N件に絞る。N/M は環境変数で調整可能にする。
- 期日入力は ISO（YYYY-MM-DD）。不正値は無視/警告（プレビューに理由を表示）。
- 既存の自由記述の抽出（新規/完了/延期）は v2結果とマージし、重複/競合は v2入力を優先。
