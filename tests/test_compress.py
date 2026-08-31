"""上下文压缩测试：budget/snip/micro 纯函数 + pipeline 利用率触发。"""
from __future__ import annotations

from miniclaudecode.context_compress.budget import budget_truncate, message_tokens
from miniclaudecode.context_compress.micro import microcompact
from miniclaudecode.context_compress.pipeline import ContextCompressor
from miniclaudecode.context_compress.snip import stale_snip


def test_budget_truncate_keeps_system_and_recent():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "a" * 10000},
        {"role": "user", "content": "recent"},
    ]
    out = budget_truncate(msgs, max_tokens=200)
    assert out[0]["role"] == "system"       # system 恒保留
    assert out[-1]["content"] == "recent"   # 最近的保留
    assert len(out) < len(msgs)             # 中间的旧消息被丢


def test_message_tokens():
    assert message_tokens({"role": "user", "content": ""}) == 0
    assert message_tokens({"role": "user", "content": "hello"}) > 0


def test_stale_snip():
    msgs = [
        {"role": "user", "content": "u"},
        {"role": "tool", "tool_call_id": "1", "name": "g", "content": "x" * 5000},
        {"role": "tool", "tool_call_id": "2", "name": "g", "content": "y" * 5000},
        {"role": "tool", "tool_call_id": "3", "name": "g", "content": "z" * 5000},
        {"role": "tool", "tool_call_id": "4", "name": "g", "content": "w" * 5000},
    ]
    out = stale_snip(msgs, keep_recent=2)
    assert "已剪枝" in out[1]["content"]   # 较早的两条被剪
    assert "已剪枝" in out[2]["content"]
    assert "已剪枝" not in out[3]["content"]  # 最近两条保留完整


def test_microcompact_trims():
    msgs = [{"role": "tool", "tool_call_id": "1", "name": "g", "content": "a" * 10000}]
    out = microcompact(msgs, max_len=4000, tool_max=2000)
    assert len(out[0]["content"]) < 10000
    assert "截断" in out[0]["content"]


def test_pipeline_utilization(config):
    comp = ContextCompressor(config, None)
    assert comp.utilization(5000) == 0.5
    assert comp.utilization(10000) == 1.0


def test_pipeline_soft_tightens_output(config, ctx):
    comp = ContextCompressor(config, None)
    ctx.token_used = 6000  # 60% >= 50% -> 收紧
    comp.maybe_soft([{"role": "user", "content": "hi"}], ctx)
    assert ctx.tight_output is True


def test_pipeline_soft_no_tighten_below_threshold(config, ctx):
    comp = ContextCompressor(config, None)
    ctx.token_used = 1000  # 10% < 50%
    comp.maybe_soft([{"role": "user", "content": "hi"}], ctx)
    assert ctx.tight_output is False


def test_pipeline_soft_micro_compacts(config, ctx):
    comp = ContextCompressor(config, None)
    ctx.token_used = 8000  # 80% >= 70% -> microcompact
    msgs = [{"role": "tool", "tool_call_id": "1", "name": "g", "content": "a" * 10000}]
    out = comp.maybe_soft(msgs, ctx)
    assert len(out[0]["content"]) < 10000
