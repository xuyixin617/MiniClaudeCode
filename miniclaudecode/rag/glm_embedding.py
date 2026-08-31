"""GLM 语义嵌入 —— 把 RagEngine 从「词元嵌入」升级为「稠密向量语义检索」。

默认（未配置 API Key）退回词元嵌入，零成本开箱即用；配置了 MINICLAUDE_API_KEY 后，
自动调用智谱 embedding-2 接口拿到 1024 维稠密向量，让检索能匹配「同义词 / 改写」，
而不只是字面重叠。

端点（OpenAI 兼容）：{base_url}/embeddings
参考：https://docs.bigmodel.cn/cn/guide/models/embedding/embedding-2
"""
from __future__ import annotations

import os
import sys
from typing import Optional

import httpx

from .embedding import Embedding, EmbeddingFn, lexical_embed

_DEFAULT_MODEL = "embedding-2"
_ENV_MODEL = "MINICLAUDE_EMBEDDING_MODEL"


class GlmEmbeddingFn:
    """调用智谱 embedding-2 的嵌入函数，带进程内缓存与失败降级。

    单个实例即一个 ``EmbeddingFn``（可调用对象），可直接注入 RagEngine：
    ``RagEngine(path, embedding_fn=GlmEmbeddingFn(base_url, api_key))``。
    """

    def __init__(self, base_url: str, api_key: str, model: str = _DEFAULT_MODEL, timeout: float = 30.0) -> None:
        self.url = f"{base_url.rstrip('/')}/embeddings"
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = httpx.Client(timeout=timeout)
        self._cache: dict[str, list] = {}

    def __call__(self, text: str) -> Embedding:
        key = (text or "").strip()
        if key in self._cache:
            return self._cache[key]
        try:
            resp = self._client.post(self.url, headers=self._headers,
                                     json={"model": self.model, "input": key})
            resp.raise_for_status()
            vec = resp.json()["data"][0]["embedding"]
            self._cache[key] = vec
            return vec
        except Exception as exc:  # noqa: BLE001  网络/额度/密钥错误
            # 失败退回词元嵌入，保证检索不崩溃；代价是该分块与新向量混用会拉低评分
            print(f"[rag] GLM 嵌入失败，退回词元嵌入: {exc}", file=sys.stderr)
            return lexical_embed(key)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass


def build_embedding_fn(
    base_url: str,
    api_key: str,
    model: Optional[str] = None,
    timeout: float = 30.0,
) -> EmbeddingFn:
    """构造嵌入函数：有密钥走 GLM 稠密向量，无密钥退回词元嵌入。"""
    model = model or os.environ.get(_ENV_MODEL, _DEFAULT_MODEL)
    if not api_key:
        return lexical_embed
    return GlmEmbeddingFn(base_url=base_url, api_key=api_key, model=model, timeout=timeout)
