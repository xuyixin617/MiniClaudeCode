"""工具系统测试：注册表、延迟激活、文件三件套（含 read-before-edit / mtime）、搜索、shell。"""
from __future__ import annotations

import asyncio
import os

from miniclaudecode.tools.defaults import build_default_registry


def _run(coro):
    return asyncio.run(coro)


def test_registry_counts():
    reg = build_default_registry()
    assert len(reg.names()) == 16
    # 常驻 7 个，延迟 9 个
    assert len(reg.active_tools()) == 7
    lazy = [t.name for t in reg._tools.values() if t.lazy]
    assert len(lazy) == 9


def test_lazy_activate_by_keyword():
    reg = build_default_registry()
    newly = reg.lazy_activate_by_text("帮我搜索一下最新的资料")
    assert "web_search" in newly
    # 再次调用不再重复激活
    newly2 = reg.lazy_activate_by_text("再搜索一次")
    assert "web_search" not in newly2


def test_run_unknown_tool(ctx):
    reg = build_default_registry()
    r = _run(reg.run_tool("nope", {}, ctx))
    assert r.is_error


def test_truncate_helper():
    reg = build_default_registry()
    out = reg._truncate("x" * 100, 50)
    assert "截断" in out
    assert len(out) > 50  # 头 + 尾 + 提示


# ------------------------------------------------------------------ #
# 文件工具：read-before-edit + mtime
# ------------------------------------------------------------------ #
def test_write_then_read(ctx, tmp_path):
    reg = build_default_registry()
    r = _run(reg.run_tool("write_file", {"path": "a.py", "content": "print(1)\n"}, ctx))
    assert not r.is_error
    r = _run(reg.run_tool("read_file", {"path": "a.py"}, ctx))
    assert not r.is_error
    assert "print(1)" in r.output
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "print(1)\n"


def test_edit_requires_read_first(ctx, tmp_path):
    reg = build_default_registry()
    # 直接用 Python 创建文件（未经工具 read/write，故 file_states 无记录）
    (tmp_path / "b.py").write_text("print(1)\n", encoding="utf-8")
    r = _run(reg.run_tool("edit_file", {
        "path": "b.py", "old_string": "print(1)", "new_string": "print(2)",
    }, ctx))
    assert r.is_error
    assert "read_file" in r.output  # read-before-edit 提示


def test_edit_after_read_works(ctx, tmp_path):
    reg = build_default_registry()
    (tmp_path / "c.py").write_text("print(1)\n", encoding="utf-8")
    _run(reg.run_tool("read_file", {"path": "c.py"}, ctx))
    r = _run(reg.run_tool("edit_file", {
        "path": "c.py", "old_string": "print(1)", "new_string": "print(2)",
    }, ctx))
    assert not r.is_error
    assert (tmp_path / "c.py").read_text(encoding="utf-8") == "print(2)\n"


def test_edit_rejects_stale_mtime(ctx, tmp_path):
    reg = build_default_registry()
    p = tmp_path / "d.py"
    p.write_text("print(1)\n", encoding="utf-8")
    _run(reg.run_tool("read_file", {"path": "d.py"}, ctx))
    # 模拟外部改动：只改 mtime
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 10))
    r = _run(reg.run_tool("edit_file", {
        "path": "d.py", "old_string": "print(1)", "new_string": "print(2)",
    }, ctx))
    assert r.is_error
    assert "外部改动" in r.output


def test_edit_old_string_not_found(ctx, tmp_path):
    reg = build_default_registry()
    (tmp_path / "e.py").write_text("print(1)\n", encoding="utf-8")
    _run(reg.run_tool("read_file", {"path": "e.py"}, ctx))
    r = _run(reg.run_tool("edit_file", {
        "path": "e.py", "old_string": "不存在的文本", "new_string": "x",
    }, ctx))
    assert r.is_error


# ------------------------------------------------------------------ #
# 搜索与 shell
# ------------------------------------------------------------------ #
def test_glob(ctx, tmp_path):
    reg = build_default_registry()
    (tmp_path / "x.py").write_text("", encoding="utf-8")
    (tmp_path / "y.txt").write_text("", encoding="utf-8")
    r = _run(reg.run_tool("glob", {"pattern": "*.py"}, ctx))
    assert "x.py" in r.output
    assert "y.txt" not in r.output


def test_grep(ctx, tmp_path):
    reg = build_default_registry()
    (tmp_path / "g.py").write_text("TODO fix\nprint(1)\n", encoding="utf-8")
    r = _run(reg.run_tool("grep", {"pattern": "TODO"}, ctx))
    assert "TODO" in r.output
    assert "g.py" in r.output


def test_grep_no_match(ctx, tmp_path):
    reg = build_default_registry()
    (tmp_path / "g.py").write_text("print(1)\n", encoding="utf-8")
    r = _run(reg.run_tool("grep", {"pattern": "不存在的关键词XYZ"}, ctx))
    assert not r.is_error
    assert "无匹配" in r.output


def test_bash_echo(ctx):
    reg = build_default_registry()
    r = _run(reg.run_tool("bash", {"command": "echo hello123"}, ctx))
    assert not r.is_error
    assert "hello123" in r.output


def test_tight_output_truncates(ctx, tmp_path):
    reg = build_default_registry()
    (tmp_path / "big.txt").write_text("a" * 20000, encoding="utf-8")
    ctx.tight_output = True
    r = _run(reg.run_tool("read_file", {"path": "big.txt"}, ctx))
    assert "截断" in r.output
