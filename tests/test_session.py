"""会话持久化测试：save / load / list / 缺失处理。"""
from __future__ import annotations

from miniclaudecode.cli.session import SessionStore


def test_save_and_load(tmp_path):
    ss = SessionStore(str(tmp_path))
    sid = ss.new_id()
    ss.save(sid, [{"role": "user", "content": "hi"}], {"title": "测试", "model": "m", "mode": "default"})

    rec = ss.load(sid)
    assert rec is not None
    assert rec["history"][0]["content"] == "hi"
    assert rec["title"] == "测试"
    assert rec["model"] == "m"


def test_load_missing(tmp_path):
    ss = SessionStore(str(tmp_path))
    assert ss.load("nonexistent") is None


def test_list_sessions(tmp_path):
    ss = SessionStore(str(tmp_path))
    ss.save(ss.new_id(), [{"role": "user", "content": "a"}], {"title": "A"})
    ss.save(ss.new_id(), [{"role": "user", "content": "b"}], {"title": "B"})
    sessions = ss.list_sessions()
    assert len(sessions) == 2
    titles = {s["title"] for s in sessions}
    assert titles == {"A", "B"}
