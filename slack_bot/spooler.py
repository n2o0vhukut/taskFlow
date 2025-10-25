from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Any


@dataclass
class Spooler:
    root_dir: str

    def __post_init__(self) -> None:
        Path(self.root_dir).mkdir(parents=True, exist_ok=True)

    def _kind_dir(self, kind: str) -> Path:
        d = Path(self.root_dir) / kind
        d.mkdir(parents=True, exist_ok=True)
        return d

    def enqueue(self, kind: str, data: Dict[str, Any]) -> str:
        d = self._kind_dir(kind)
        fname = f"{uuid.uuid4().hex}.json"
        path = d / fname
        tmp = d / f".{fname}.tmp"
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return str(path)

    def drain(self, kind: str, handler: Callable[[Dict[str, Any]], bool]) -> None:
        d = self._kind_dir(kind)
        for p in sorted(d.glob("*.json")):
            try:
                with p.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
                ok = handler(payload)
                if ok:
                    try:
                        p.unlink()
                    except FileNotFoundError:
                        pass
            except Exception:
                # keep file for future retry
                continue

