"""跨会话记忆存储。

设计：JSON 文件持久化，每个条目含 content / tags / created_at。
召回采用「词元重叠 + 标签加权」的轻量打分（无需向量库，零重依赖）；
预留 embedding_fn 扩展点，可替换为真正的语义召回。
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..rag.embedding import cosine


@dataclass
class MemoryEntry:
    entry_id: str
    content: str
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    embedding: Optional[object] = None   # 语义向量（list[float] 或 dict），可选

    def to_dict(self) -> dict:
        return {"entry_id": self.entry_id, "content": self.content,
                "tags": self.tags, "created_at": self.created_at,
                "embedding": self.embedding}

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        return cls(entry_id=d.get("entry_id", ""), content=d.get("content", ""),
                   tags=d.get("tags", []), created_at=d.get("created_at", 0.0),
                   embedding=d.get("embedding"))


def _tokenize(text: str) -> set[str]:
    """中文按字切，英文按词切，做轻量词元集合。"""
    tokens: set[str] = set()
    tokens.update(re.findall(r"[a-zA-Z0-9_]+", text.lower()))
    tokens.update(re.findall(r"[一-鿿]", text))  # 每个汉字作为一个 token
    return tokens


class MemoryStore:
    """基于 JSON 文件的跨会话记忆。"""

    def __init__(self, path: str, embedding_fn: Optional[Callable[[str], list[float]]] = None) -> None:
        self.path = Path(path)
        self.entries: list[MemoryEntry] = []
        self.embedding_fn = embedding_fn
        self._load()

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.entries = [MemoryEntry.from_dict(d) for d in data.get("entries", [])]
            except Exception:
                self.entries = []

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"entries": [e.to_dict() for e in self.entries]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ #
    async def save(self, content: str, tags: list[str] | None = None) -> str:
        """写入一条记忆，返回 entry_id。"""
        # 保证时间戳严格递增：time.time() 分辨率有限，快速连续写入可能同值，
        # 会导致 list_all 按 created_at 倒序排序时顺序不稳定。
        now = time.time()
        if self.entries and now <= self.entries[-1].created_at:
            now = self.entries[-1].created_at + 1e-6
        # 有语义向量时，保存时一并算出并缓存（避免每次召回都重新调 API）
        embedding = None
        if self.embedding_fn is not None:
            try:
                embedding = self.embedding_fn(content)
            except Exception:
                embedding = None
        entry = MemoryEntry(
            entry_id=uuid.uuid4().hex[:12],
            content=content,
            tags=tags or [],
            created_at=now,
            embedding=embedding,
        )
        self.entries.append(entry)
        self._flush()
        return entry.entry_id

    async def recall(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """召回与 query 相关的记忆。有 embedding_fn 走余弦语义，否则词元重叠。"""
        if not self.entries:
            return []
        if self.embedding_fn is not None:
            return self._recall_semantic(query, limit)
        return self._recall_lexical(query, limit)

    def _score_extra(self, query: str, e: MemoryEntry) -> float:
        """标签命中 + 时效性的加分项（词元 / 语义两条路径共用）。"""
        tag_hit = any(t in query for t in e.tags)
        extra = (2.0 if tag_hit else 0.0) + (0.01 * len(e.tags) if tag_hit else 0.0)
        extra += 0.001 * (e.created_at / (time.time() + 1))
        return extra

    def _recall_lexical(self, query: str, limit: int) -> list[MemoryEntry]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return self.entries[-limit:]
        scored: list[tuple[float, MemoryEntry]] = []
        for e in self.entries:
            e_tokens = _tokenize(e.content) | _tokenize(" ".join(e.tags))
            overlap = float(len(q_tokens & e_tokens))
            score = overlap + self._score_extra(query, e)
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:limit]]

    def _recall_semantic(self, query: str, limit: int) -> list[MemoryEntry]:
        try:
            q_emb = self.embedding_fn(query)
        except Exception:
            return self._recall_lexical(query, limit)
        scored: list[tuple[float, MemoryEntry]] = []
        for e in self.entries:
            if e.embedding is not None:
                base = cosine(q_emb, e.embedding)
            else:
                # 老条目无向量：退回词元重叠兜底
                q_tokens = _tokenize(query)
                e_tokens = _tokenize(e.content) | _tokenize(" ".join(e.tags))
                base = float(len(q_tokens & e_tokens))
            score = base + self._score_extra(query, e)
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:limit]]

    async def list_all(self) -> list[MemoryEntry]:
        return sorted(self.entries, key=lambda e: -e.created_at)

    def count(self) -> int:
        return len(self.entries)
