"""RAG 模块测试：分块、索引、检索、持久化、embedding_fn 升级。"""
from __future__ import annotations

from miniclaudecode.rag import RagEngine, build_embedding_fn, chunk_text
from miniclaudecode.rag.embedding import lexical_embed
from miniclaudecode.rag.glm_embedding import GlmEmbeddingFn


def test_chunk_text_small():
    assert chunk_text("短文本", size=500) == ["短文本"]


def test_chunk_text_long_splits():
    text = "\n\n".join(f"第{i}段内容" for i in range(100))
    chunks = chunk_text(text, size=200, overlap=50)
    assert len(chunks) > 1
    # 每块不超过 size（硬切段落时可能恰好等于 size）
    assert all(len(c) <= 200 for c in chunks)


def test_index_and_search_lexical(tmp_path):
    eng = RagEngine(str(tmp_path / "rag.db"))
    did1 = eng.index_text("架构.md", "MiniClaudeCode 使用 GLM 后端和权限系统", title="架构")
    eng.index_text("菜谱.md", "这是一份番茄炒蛋的菜谱", title="菜谱")

    hits = eng.search("后端是什么", limit=3)
    assert hits
    assert hits[0].doc_id == did1


def test_search_relevant_ordering(tmp_path):
    eng = RagEngine(str(tmp_path / "rag.db"))
    eng.index_text("a", "数据库连接池配置与连接泄漏排查")
    eng.index_text("b", "前端 React 组件渲染性能优化")

    hits = eng.search("数据库 连接池", limit=2)
    assert hits
    assert "连接池" in hits[0].text


def test_persist_across_instances(tmp_path):
    p = str(tmp_path / "rag.db")
    eng = RagEngine(p)
    eng.index_text("d", "持久化测试内容", title="T")
    eng.close()

    eng2 = RagEngine(p)
    docs = eng2.list_indexed()
    assert any(d.title == "T" for d in docs)
    assert eng2.search("持久化")


def test_delete_and_clear(tmp_path):
    eng = RagEngine(str(tmp_path / "rag.db"))
    did = eng.index_text("d", "要删除的内容")
    assert eng.delete(did) is True
    assert eng.search("删除") == []

    eng.index_text("d2", "再来一条")
    assert len(eng.list_indexed()) == 1
    eng.clear()
    assert eng.list_indexed() == []


def test_embedding_fn_cosine(tmp_path):
    """注入 embedding_fn 后走稠密向量余弦检索。"""

    def emb(text: str) -> list:
        # 用 ord() 做确定性分桶（内置 hash() 受 PYTHONHASHSEED 随机化影响，会导致测试偶发失败）
        v = [0.0] * 8
        for ch in text:
            v[ord(ch) % 8] += 1.0
        return v

    eng = RagEngine(str(tmp_path / "rag.db"), embedding_fn=emb)
    did_x = eng.index_text("src-x", "苹果香蕉")
    eng.index_text("src-y", "汽车飞机")

    hits = eng.search("苹果", limit=2)
    assert hits
    assert hits[0].doc_id == did_x


# --------------------------------------------------------------------------- #
# GLM 语义嵌入
# --------------------------------------------------------------------------- #
def test_build_embedding_fn_no_key_returns_lexical(monkeypatch):
    monkeypatch.delenv("MINICLAUDE_EMBEDDING_MODEL", raising=False)
    fn = build_embedding_fn("https://open.bigmodel.cn/api/paas/v4", "")
    assert fn is lexical_embed


def test_build_embedding_fn_with_key_returns_glm(monkeypatch):
    monkeypatch.delenv("MINICLAUDE_EMBEDDING_MODEL", raising=False)
    fn = build_embedding_fn("https://open.bigmodel.cn/api/paas/v4", "sk-test")
    assert isinstance(fn, GlmEmbeddingFn)
    assert fn.url == "https://open.bigmodel.cn/api/paas/v4/embeddings"
    assert fn.model == "embedding-2"
    fn.close()


def test_glm_embedding_success_and_cache(monkeypatch):
    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"data": [{"embedding": [0.1, 0.2]}]}

    class _Client:
        def __init__(self): self.calls = 0
        def post(self, *a, **k): self.calls += 1; return _Resp()
        def close(self): pass

    client = _Client()
    fn = GlmEmbeddingFn("https://open.bigmodel.cn/api/paas/v4", "sk-test")
    fn._client = client
    assert fn("你好") == [0.1, 0.2]
    assert fn("你好") == [0.1, 0.2]   # 命中缓存，不再发请求
    assert client.calls == 1
    fn.close()


def test_glm_embedding_fallback_on_error(monkeypatch):
    class _Boom:
        def post(self, *a, **k): raise RuntimeError("no network")
        def close(self): pass

    fn = GlmEmbeddingFn("https://open.bigmodel.cn/api/paas/v4", "sk-test")
    fn._client = _Boom()
    assert fn("测试") == lexical_embed("测试")   # 失败退回词元嵌入
    fn.close()
