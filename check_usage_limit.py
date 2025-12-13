# check_usage_limit.py
# 実行例:
#   export OPENAI_API_KEY="sk-xxxx"
#   export MAX_USD_LIMIT=20.0
#   python check_usage_limit.py

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import Any, Dict

import requests


API_KEY = os.getenv("OPENAI_API_KEY")
MAX_LIMIT = float(os.getenv("MAX_USD_LIMIT", 20.0))  # USD 上限

# OpenAIの課金使用量API（Billing Usage）。
# start_date/end_date は YYYY-MM-DD で指定する必要があります。
BILLING_URL = "https://api.openai.com/v1/dashboard/billing/usage"

# 旧仕様のUsage API（存在する環境向けのフォールバック）。
USAGE_URL = "https://api.openai.com/v1/usage"


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
    }


def _this_month_range() -> tuple[str, str]:
    """今月の開始日と今日の日付を ISO 形式で返す。"""
    today = date.today()
    start = today.replace(day=1)
    return (start.isoformat(), today.isoformat())


def fetch_month_usage_usd() -> float:
    """今月の利用額(USD)を取得する。

    1) 推奨: /v1/dashboard/billing/usage?start_date=..&end_date=..
       - total_usage (cents) または total_cost_usd が返る環境を想定
    2) フォールバック: /v1/usage
       - total_usage or total_cost_usd を読み取り
    いずれも得られない場合は例外を送出する。
    """
    if not API_KEY:
        raise RuntimeError("OPENAI_API_KEY が未設定です。")

    start, end = _this_month_range()

    # 1) Billing Usage API（推奨）
    try:
        resp = requests.get(
            BILLING_URL,
            headers=_headers(),
            params={"start_date": start, "end_date": end},
            timeout=20,
        )
        if resp.status_code == 200:
            data: Dict[str, Any] = resp.json()
            if "total_cost_usd" in data and isinstance(data["total_cost_usd"], (int, float)):
                return float(data["total_cost_usd"])  # すでにUSD
            if "total_usage" in data and isinstance(data["total_usage"], (int, float)):
                # 多くの環境で total_usage は cents（セント）で返る
                return float(data["total_usage"]) / 100.0
            # 他の形式は未対応のためフォールバック
        else:
            # 401/404/429/5xx 等はフォールバックへ
            pass
    except requests.RequestException:
        pass

    # 2) 旧Usage API（ベストエフォート）
    try:
        resp = requests.get(USAGE_URL, headers=_headers(), timeout=20)
        if resp.status_code == 200:
            data: Dict[str, Any] = resp.json()
            if "total_cost_usd" in data and isinstance(data["total_cost_usd"], (int, float)):
                return float(data["total_cost_usd"])
            if "total_usage" in data and isinstance(data["total_usage"], (int, float)):
                return float(data["total_usage"]) / 100.0
    except requests.RequestException:
        pass

    raise RuntimeError("Usage情報の取得に失敗しました（API仕様/権限/日付範囲を確認してください）。")


def main() -> int:
    if not API_KEY:
        print("❌ OPENAI_API_KEYが設定されていません。")
        return 1

    try:
        usd = fetch_month_usage_usd()
    except Exception as e:
        print("❌ Usage APIの取得に失敗しました:", str(e))
        return 1

    print(f"📊 現在の利用額: ${usd:.2f} / 上限: ${MAX_LIMIT:.2f}")

    if usd >= MAX_LIMIT:
        print("⚠️ 上限を超過しました。API呼び出しを停止します。")
        return 1
    else:
        remaining = MAX_LIMIT - usd
        print(f"✅ 残り ${remaining:.2f} まで利用可能です。")
        return 0


if __name__ == "__main__":
    sys.exit(main())

