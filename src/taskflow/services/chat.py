from __future__ import annotations

from typing import Dict, Any


def echo_completion(payload: Dict[str, Any]) -> Dict[str, Any]:
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

