"""存储层 —— 基于标准库 sqlite3 的文档/分块持久化。

职责：把「文档（Document）」和它的「分块（Chunk）」可靠地落盘，支持增删查。
上层 RAG 检索、未来的向量索引、元数据过滤都构建在这一层之上。

设计：
- StorageBackend 是抽象接口，SqliteStorage 是默认实现；
- 后续想换向量库（Chroma / FAISS 等）只需实现同一接口，上层 RagEngine 无需改动；
- 分块与文档的关系：1 个 Document → N 个 Chunk（chunks.doc_id 外键关联）。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Chunk:
    """一个分块（检索的最小单元）。"""

    chunk_id: str
    doc_id: str
    index: int
    text: str
    embedding: Optional[object] = None   # list[float] 或 dict[str, float]
    metadata: dict = field(default_factory=dict)


@dataclass
class Document:
    """一份已索引的文档，含若干分块。"""

    doc_id: str
    source: str                 # 来源路径或标识
    title: str = ""
    content: str = ""
    created_at: float = 0.0
    chunks: list = field(default_factory=list)


class StorageBackend:
    """统一存储接口。"""

    def upsert_document(self, doc: Document) -> None:
        raise NotImplementedError

    def get_document(self, doc_id: str) -> Optional[Document]:
        raise NotImplementedError

    def delete_document(self, doc_id: str) -> bool:
        raise NotImplementedError

    def list_documents(self) -> list:
        raise NotImplementedError

    def list_chunks(self) -> list:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    def count_documents(self) -> int:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SqliteStorage(StorageBackend):
    """SQLite 实现：documents / chunks 两张表。"""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + 锁：允许跨线程访问（asyncio 回调等场景）
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS documents(
                    doc_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT,
                    content TEXT,
                    created_at REAL
                )"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS chunks(
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    idx INTEGER,
                    text TEXT,
                    embedding TEXT,
                    metadata TEXT
                )"""
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id)")

    # ------------------------------------------------------------------ #
    def upsert_document(self, doc: Document) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO documents(doc_id, source, title, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (doc.doc_id, doc.source, doc.title, doc.content, doc.created_at),
            )
            # 重写分块：先删后插，保证幂等
            self._conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc.doc_id,))
            for c in doc.chunks:
                self._conn.execute(
                    "INSERT INTO chunks(chunk_id, doc_id, idx, text, embedding, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        c.chunk_id,
                        c.doc_id,
                        c.index,
                        c.text,
                        json.dumps(c.embedding, ensure_ascii=False) if c.embedding is not None else None,
                        json.dumps(c.metadata, ensure_ascii=False),
                    ),
                )

    def get_document(self, doc_id: str) -> Optional[Document]:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc_id, source, title, content, created_at FROM documents WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
            if row is None:
                return None
            doc = Document(doc_id=row[0], source=row[1], title=row[2], content=row[3], created_at=row[4])
            rows = self._conn.execute(
                "SELECT chunk_id, doc_id, idx, text, embedding, metadata FROM chunks "
                "WHERE doc_id = ? ORDER BY idx",
                (doc_id,),
            ).fetchall()
            doc.chunks = [self._row_to_chunk(r) for r in rows]
            return doc

    def delete_document(self, doc_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            self._conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            return cur.rowcount > 0

    def list_documents(self) -> list:
        """列出全部文档（含正文，不含分块）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT doc_id, source, title, content, created_at FROM documents ORDER BY created_at DESC"
            ).fetchall()
        return [Document(doc_id=r[0], source=r[1], title=r[2], content=r[3], created_at=r[4]) for r in rows]

    def list_chunks(self) -> list:
        """列出全部分块（用于检索打分）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT chunk_id, doc_id, idx, text, embedding, metadata FROM chunks ORDER BY doc_id, idx"
            ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def clear(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM chunks")
            self._conn.execute("DELETE FROM documents")

    def count_documents(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    @staticmethod
    def _row_to_chunk(row) -> Chunk:
        embedding = None
        if row[4]:
            try:
                embedding = json.loads(row[4])
            except Exception:
                embedding = None
        metadata = {}
        if row[5]:
            try:
                metadata = json.loads(row[5])
            except Exception:
                metadata = {}
        return Chunk(chunk_id=row[0], doc_id=row[1], index=row[2], text=row[3],
                     embedding=embedding, metadata=metadata)
