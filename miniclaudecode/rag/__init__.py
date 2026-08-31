"""RAG 检索与知识库存储层。

对外暴露 :class:`RagEngine` —— 一个自包含的「文档入库 → 分块 → 索引 → 语义检索」引擎，
构建在标准库 sqlite3 之上，零新增依赖。

分层设计：
- :mod:`store`          存储层（SQLite 持久化文档与分块）
- :mod:`embedding`      嵌入抽象（默认词元嵌入，可注入 embedding_fn 升级为向量）
- :mod:`glm_embedding`  GLM 语义嵌入（embedding-2，有密钥自动启用）
- :mod:`retriever`      分块 + 检索引擎 RagEngine

与既有代码的关系（最小侵入）：
- 不修改 loop / backend / permission / context_compress 任何一行；
- 通过 ``tools/rag_tools.py`` 以「延迟激活工具」的形式接入 Agent，按需查询；
- 如需「自动注入 system prompt」，可在 loop 的 side_query 处加一行并行调用（见 GUIDE）。
"""
from __future__ import annotations

from .retriever import RagEngine, SearchHit, chunk_text
from .glm_embedding import build_embedding_fn

__all__ = ["RagEngine", "SearchHit", "chunk_text", "build_embedding_fn"]
