"""嵌入抽象层。

默认使用「词元嵌入」：中文按字、英文/数字按词切分，转成带词频权重的稀疏向量，
用 dict[str, float] 表示，零依赖即可完成相似度检索（与跨会话记忆 MemoryStore 的
词元召回一脉相承，但这里输出真正的向量并可算余弦相似度）。

如需真正的语义检索，向 RagEngine 注入 ``embedding_fn``（返回 list[float] 稠密向量），
引擎会自动切换到余弦相似度。这样设计让 RAG 模块「开箱即用、可升级」。
"""
from __future__ import annotations

import math
import re
from typing import Callable, Optional, Union

# 向量可以是稠密 list[float]（embedding_fn）或稀疏 dict[str, float]（词元嵌入）
Embedding = Union[list, dict]
EmbeddingFn = Callable[[str], Embedding]

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[一-鿿]")


def lexical_embed(text: str) -> dict:
    """词元嵌入：中文按字、英文按词，返回带词频权重的稀疏向量。"""
    vec: dict = {}
    for tok in _TOKEN_RE.findall((text or "").lower()):
        vec[tok] = vec.get(tok, 0.0) + 1.0
    return vec


def _dot(a, b) -> float:
    if isinstance(a, dict) and isinstance(b, dict):
        return sum(a[k] * b.get(k, 0.0) for k in a)
    if isinstance(a, dict) or isinstance(b, dict):
        return 0.0  # 混合类型不支持，安全降级为 0
    return sum(x * y for x, y in zip(a, b))


def _norm(v) -> float:
    if isinstance(v, dict):
        return math.sqrt(sum(x * x for x in v.values()))
    return math.sqrt(sum(x * x for x in v))


def cosine(a, b) -> float:
    """余弦相似度，兼容稠密 list 与稀疏 dict。"""
    na, nb = _norm(a), _norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return _dot(a, b) / (na * nb)


class Embedder:
    """嵌入器：有 embedding_fn 用向量，否则用词元嵌入。"""

    def __init__(self, embedding_fn: Optional[EmbeddingFn] = None) -> None:
        self.embedding_fn = embedding_fn

    def embed(self, text: str) -> Embedding:
        if self.embedding_fn is not None:
            return self.embedding_fn(text)
        return lexical_embed(text)
