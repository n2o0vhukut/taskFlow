from __future__ import annotations

"""チャット機能のダミー実装（echo）。

OpenAI風のレスポンス形式を模し、リクエスト末尾ユーザの `content` をそのまま返す。
将来的に本API接続へ差し替えやすいよう、入出力の形だけ合わせている。
"""

from typing import Dict, Any


def echo_completion(payload: Dict[str, Any]) -> Dict[str, Any]:
    """最後のユーザメッセージの内容を `echo: ...` として返すだけの関数。"""
    messages = payload.get("messages", [])
    # Simple echo of last user content
    content = ""
    if messages:
        last = messages[-1]
        content = last.get("content", "")
    return {
        "id": "dummy-echo",
        "object": "chat.completion",
        "created": 0,
        "model": "dummy",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": f"echo: {content}"},
                "finish_reason": "stop",
            }
        ],
    }
