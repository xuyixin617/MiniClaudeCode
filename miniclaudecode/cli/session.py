"""会话持久化与会话恢复。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional


class SessionStore:
    """把对话历史以 JSON 文件保存/加载，支持多会话管理。"""

    def __init__(self, data_dir: str) -> None:
        self.dir = Path(data_dir) / "sessions"
        self.dir.mkdir(parents=True, exist_ok=True)

    def new_id(self) -> str:
        return uuid.uuid4().hex[:10]

    def _path(self, session_id: str) -> Path:
        return self.dir / f"{session_id}.json"

    # ------------------------------------------------------------------ #
    def save(self, session_id: str, history: list[dict], meta: Optional[dict] = None) -> str:
        """保存会话，返回 session_id。"""
        meta = meta or {}
        record = {
            "session_id": session_id,
            "created_at": meta.get("created_at", time.time()),
            "updated_at": time.time(),
            "title": meta.get("title", "未命名会话"),
            "model": meta.get("model", ""),
            "mode": meta.get("mode", ""),
            "history": history,
        }
        self._path(session_id).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return session_id

    def load(self, session_id: str) -> Optional[dict]:
        p = self._path(session_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list_sessions(self) -> list[dict]:
        """列出全部会话（按更新时间倒序），仅返回元信息。"""
        out: list[dict] = []
        for p in self.dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                out.append({
                    "session_id": d.get("session_id", p.stem),
                    "title": d.get("title", "未命名"),
                    "updated_at": d.get("updated_at", 0),
                    "model": d.get("model", ""),
                })
            except Exception:
                continue
        out.sort(key=lambda x: -x.get("updated_at", 0))
        return out
