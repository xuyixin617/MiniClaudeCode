"""跨会话记忆测试：save / recall / list / 持久化。"""
from __future__ import annotations

import asyncio

from miniclaudecode.context_compress.memory import MemoryStore


def _run(coro):
    return asyncio.run(coro)


def test_save_and_recall(tmp_path):
    ms = MemoryStore(str(tmp_path / "m.json"))
    _run(ms.save("项目使用 GLM-4 后端", ["项目", "后端"]))
    _run(ms.save("数据库是 PostgreSQL", ["数据库"]))

    rec = _run(ms.recall("后端是什么"))
    assert any("GLM" in e.content for e in rec)

    rec2 = _run(ms.recall("数据存储"))
    assert any("PostgreSQL" in e.content for e in rec2)


def test_recall_by_tag(tmp_path):
    ms = MemoryStore(str(tmp_path / "m.json"))
    _run(ms.save("测试内容", ["test-tag"]))
    rec = _run(ms.recall("test-tag"))
    assert any("测试内容" in e.content for e in rec)


def test_list_all_sorted(tmp_path):
    ms = MemoryStore(str(tmp_path / "m.json"))
    _run(ms.save("first"))
    _run(ms.save("second"))
    entries = _run(ms.list_all())
    assert len(entries) == 2
    # 按创建时间倒序：second 在前
    assert entries[0].content == "second"


def test_persist_across_instances(tmp_path):
    p = str(tmp_path / "m.json")
    ms = MemoryStore(p)
    _run(ms.save("重要信息"))
    assert ms.count() == 1

    ms2 = MemoryStore(p)  # 重新加载
    assert ms2.count() == 1
    assert ms2.entries[0].content == "重要信息"


def test_recall_empty_store(tmp_path):
    ms = MemoryStore(str(tmp_path / "m.json"))
    assert _run(ms.recall("任意查询")) == []


def test_recall_semantic_uses_embedding(tmp_path):
    """有 embedding_fn 时按余弦相似度召回，能匹配「语义相近但字面不重叠」的内容。"""
    vecs = {"登录鉴权流程": [1.0, 0.0], "用户身份验证": [0.9, 0.1], "番茄炒蛋菜谱": [0.0, 1.0]}
    ms = MemoryStore(str(tmp_path / "m.json"), embedding_fn=lambda t: vecs.get(t, [0.0, 0.0]))
    _run(ms.save("登录鉴权流程"))
    _run(ms.save("番茄炒蛋菜谱"))

    rec = _run(ms.recall("用户身份验证", limit=2))
    assert rec
    assert "登录鉴权" in rec[0].content  # 语义相近者排第一，而非字面重叠者


def test_memory_entry_embedding_persists(tmp_path):
    """save 时缓存语义向量，并随 JSON 持久化、跨实例恢复。"""
    p = str(tmp_path / "m.json")
    ms = MemoryStore(p, embedding_fn=lambda t: [1.0, 2.0, 3.0])
    _run(ms.save("内容A"))
    assert ms.entries[0].embedding == [1.0, 2.0, 3.0]

    ms2 = MemoryStore(p, embedding_fn=lambda t: [1.0, 2.0, 3.0])
    assert ms2.entries[0].embedding == [1.0, 2.0, 3.0]
