# TaskFlow Ops（P0）— 日次チェックイン + 自動計画 + 履歴可視化

## セットアップ
```bash
pip install -r requirements.txt
python -m taskflow init-db
```

## よく使うコマンド
```bash
# 日次チェックイン（対話）
python -m taskflow checkin

# タスク登録/一覧/完了
python -m taskflow add --title "統計検定 過去問3セット" --due 2025-10-25 --est 2 --project "資格" --priority H
python -m taskflow list
python -m taskflow done 1

# 今日の計画（可処分3h想定）
python -m taskflow plan-today --hours 3

# 週次レポート（Excel）
python -m taskflow weekly-report --out data/weekly.xlsx

# ダッシュボード
streamlit run app/dashboard.py
```
