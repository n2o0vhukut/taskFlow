"""TaskFlow Dashboard (Streamlit)

初心者でも動かしやすいように、アプリ本体と同じDBパスの解決ロジックを利用し、
存在しないテーブル（events / checkins）があっても安全に空表示へフォールバックします。
"""

import streamlit as st
import sqlite3
import pandas as pd
from pathlib import Path

try:
    # パッケージが editable インストールされていれば利用可
    from taskflow.db.session import get_db_path  # type: ignore
    DB_PATH = get_db_path()
except Exception:
    # フォールバック: リポジトリ直下の data/taskflow.db
    BASE = Path(__file__).resolve().parents[1]
    DB_PATH = BASE / "data" / "taskflow.db"


st.set_page_config(page_title="TaskFlow Dashboard", layout="wide")
st.title("✅ TaskFlow Dashboard")
st.caption("日次チェックイン・タスク履歴の可視化（P0）")


@st.cache_data
def load():
    """DB から tasks / events / checkins を読み込む（無ければ空DataFrame）。"""
    p = Path(DB_PATH)
    if not p.exists():
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    conn = sqlite3.connect(p)
    try:
        tasks = pd.read_sql_query("SELECT * FROM tasks", conn)
    except Exception:
        tasks = pd.DataFrame()
    try:
        events = pd.read_sql_query("SELECT * FROM events", conn)
    except Exception:
        events = pd.DataFrame()
    try:
        checkins = pd.read_sql_query("SELECT * FROM checkins", conn)
    except Exception:
        checkins = pd.DataFrame()
    conn.close()
    return tasks, events, checkins


tasks, events, checkins = load()

c1, c2, c3, c4 = st.columns(4)
c1.metric("タスク総数", len(tasks))
c2.metric("TODO", int((tasks["status"] == "todo").sum()) if not tasks.empty else 0)
c3.metric("完了", int((tasks["status"] == "done").sum()) if not tasks.empty else 0)
c4.metric("チェックイン日数", checkins["date"].nunique() if not checkins.empty else 0)

tab1, tab2, tab3 = st.tabs(["タスク一覧", "イベント履歴", "チェックイン"])
with tab1:
    if tasks.empty:
        st.info("まだタスクがありません。`python -m taskflow add ...` を実行してください。")
    else:
        st.dataframe(tasks, use_container_width=True, hide_index=True)
        st.download_button(
            "Download tasks.csv", tasks.to_csv(index=False).encode("utf-8"), "tasks.csv"
        )

with tab2:
    if events.empty:
        st.info("イベント履歴がありません。")
    else:
        st.dataframe(
            events.sort_values("at", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

with tab3:
    if checkins.empty:
        st.info("チェックインがありません。`python -m taskflow checkin` を実行してください。")
    else:
        st.dataframe(
            checkins.sort_values("date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
        # 週次完了数の棒グラフ（簡易）
        ev = events.copy()
        if not ev.empty and "at" in ev.columns and "kind" in ev.columns:
            ev["at"] = pd.to_datetime(ev["at"], errors="coerce")
            ev = ev.dropna(subset=["at"])  # 解析不能な日付は除外
            ev["week"] = ev["at"].dt.to_period("W").astype(str)
            weekly = (
                ev[ev["kind"] == "done"].groupby("week").size().reset_index(name="done_count")
            )
            st.bar_chart(weekly.set_index("week"))
