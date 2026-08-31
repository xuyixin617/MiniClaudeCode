"""检索引擎 —— 分块 + 索引 + 语义检索的高层封装。

RagEngine 把「存储层（store）」「嵌入层（embedding）」「分块（chunking）」串成一条链路：

    index_text / index_file ─► chunk_text ─► embed ─► SqliteStorage 落盘
    search(query)            ─► embed(query) ─► 与所有分块算余弦相似度 ─► top-k

默认词元嵌入（零依赖）；传入 embedding_fn 即升级为稠密向量语义检索。
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .embedding import Embedder, EmbeddingFn, cosine
from .store import Chunk, Document, SqliteStorage


def chunk_text(text: str, size: int = 500, overlap: int = 100) -> list:
    """按段落把文本切成不超过 size 的块，块间保留 overlap 重叠，保证语义连贯。"""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list = []
    paragraphs = re.split(r"\n\s*\n", text)
    cur = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(cur) + len(para) + 1 <= size:
            cur = f"{cur}\n\n{para}".strip()
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        # 超长段落硬切（带重叠）
        while len(para) > size:
            chunks.append(para[:size])
            para = para[size - overlap:]
        cur = para
    if cur:
        chunks.append(cur)
    return chunks


@dataclass
class SearchHit:
    """一条检索结果。"""

    doc_id: str
    source: str
    title: str
    chunk_index: int
    text: str
    score: float


class RagEngine:
    """RAG 引擎门面。"""

    def __init__(
        self,
        path: str,
        embedding_fn: Optional[EmbeddingFn] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 100,
    ) -> None:
        self.storage = SqliteStorage(path)
        self.embedder = Embedder(embedding_fn)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # ------------------------------------------------------------------ #
    # 索引
    # ------------------------------------------------------------------ #
    def index_text(self, source: str, text: str, title: str = "", metadata: Optional[dict] = None) -> str:
        """把一段原始文本索引进库，返回 doc_id。"""
        doc_id = uuid.uuid4().hex[:12]
        chunks = self._build_chunks(doc_id, source, text, metadata)
        doc = Document(doc_id=doc_id, source=source, title=title or source,
                       content=text, created_at=time.time(), chunks=chunks)
        self.storage.upsert_document(doc)
        return doc_id

    def index_file(self, path: str, title: str = "", metadata: Optional[dict] = None) -> str:
        """把一个文件读入并索引，返回 doc_id。"""
        p = Path(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        return self.index_text(str(p), text, title=title or p.name, metadata=metadata)

    def _build_chunks(self, doc_id: str, source: str, text: str, metadata: Optional[dict]) -> list:
        pieces = chunk_text(text, self.chunk_size, self.chunk_overlap)
        chunks: list = []
        for i, piece in enumerate(pieces):
            chunks.append(Chunk(
                chunk_id=f"{doc_id}:{i}",
                doc_id=doc_id,
                index=i,
                text=piece,
                embedding=self.embedder.embed(piece),
                metadata=dict(metadata or {}),
            ))
        return chunks

    # ------------------------------------------------------------------ #
    # 检索
    # ------------------------------------------------------------------ #
    def search(self, query: str, limit: int = 5, min_score: float = 0.0) -> list:
        """按语义相似度检索 top-k 分块，返回 SearchHit 列表。"""
        q_emb = self.embedder.embed(query)
        scored: list = []
        for c in self.storage.list_chunks():
            if c.embedding is None:
                continue
            s = cosine(q_emb, c.embedding)
            if s > min_score:
                scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        top = scored[:limit]
        if not top:
            return []

        # 一次性加载文档元信息，避免逐条查库
        doc_meta = {d.doc_id: d for d in self.storage.list_documents()}
        hits: list = []
        for s, c in top:
            doc = doc_meta.get(c.doc_id)
            hits.append(SearchHit(
                doc_id=c.doc_id,
                source=doc.source if doc else c.doc_id,
                title=doc.title if doc else "",
                chunk_index=c.index,
                text=c.text,
                score=s,
            ))
        return hits

    # ------------------------------------------------------------------ #
    # 管理
    # ------------------------------------------------------------------ #
    def list_indexed(self) -> list:
        return self.storage.list_documents()

    def delete(self, doc_id: str) -> bool:
        return self.storage.delete_document(doc_id)

    def clear(self) -> None:
        self.storage.clear()

    def close(self) -> None:
        self.storage.close()
        # 若嵌入函数持有网络客户端（如 GLM），一并释放
        closer = getattr(getattr(self.embedder, "embedding_fn", None), "close", None)
        if closer is not None:
            try:
                closer()
            except Exception:
                pass
