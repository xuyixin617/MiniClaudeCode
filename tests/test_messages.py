"""messages.py 单元测试：token 估算、消息构造器、ToolCall 解析。"""
from __future__ import annotations

from miniclaudecode.agent_runtime.messages import (
    ToolCall,
    assistant_message,
    estimate_tokens,
    system_message,
    tool_message,
    user_message,
)


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_english():
    # 英文约 4 字符/token
    assert abs(estimate_tokens("abcd" * 10) - 10) <= 2


def test_estimate_tokens_chinese():
    # 中文约 1.5 字/token
    assert estimate_tokens("你好世界") >= 2


def test_toolcall_parse_valid_json():
    tc = ToolCall.from_openai({
        "id": "c1",
        "type": "function",
        "function": {"name": "grep", "arguments": '{"pattern": "x"}'},
    })
    assert tc.name == "grep"
    assert tc.parsed == {"pattern": "x"}


def test_toolcall_parse_bad_json():
    tc = ToolCall.from_openai({"id": "c1", "function": {"name": "grep", "arguments": "not-json"}})
    assert tc.parsed == {}
    assert tc.name == "grep"


def test_constructors():
    assert system_message("s") == {"role": "system", "content": "s"}
    assert user_message("u") == {"role": "user", "content": "u"}
    assert tool_message("c1", "grep", "r") == {
        "role": "tool", "tool_call_id": "c1", "name": "grep", "content": "r",
    }


def test_assistant_with_toolcalls():
    tc = ToolCall(id="c1", name="grep", arguments="{}", parsed={})
    m = assistant_message("", [tc])
    assert m["role"] == "assistant"
    assert m["tool_calls"][0]["id"] == "c1"
    assert m["tool_calls"][0]["function"]["name"] == "grep"
