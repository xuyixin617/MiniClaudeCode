"""backend.py 单元测试：只测纯函数（协议翻译/解析/组装），不发网络请求。"""
from __future__ import annotations

import asyncio

import pytest

from miniclaudecode.agent_runtime.backend import LLMBackend
from miniclaudecode.agent_runtime.messages import Usage


@pytest.fixture
def backend(config):
    b = LLMBackend(config)
    yield b
    try:
        asyncio.run(b.close())
    except Exception:
        pass


def test_to_anthropic_messages(backend):
    sysstr, am = backend._to_anthropic_messages([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "grep", "arguments": '{"pattern":"x"}'}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "name": "grep", "content": "result"},
    ])
    assert sysstr == "sys"
    assert am[0]["role"] == "user"
    assert am[1]["role"] == "assistant"
    assert am[1]["content"][0]["type"] == "tool_use"
    assert am[1]["content"][0]["name"] == "grep"
    assert am[2]["content"][0]["type"] == "tool_result"


def test_tools_to_anthropic(backend):
    tools = [{
        "type": "function",
        "function": {
            "name": "grep",
            "description": "d",
            "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}},
        },
    }]
    out = backend._tools_to_anthropic(tools)
    assert out[0]["name"] == "grep"
    assert out[0]["input_schema"]["type"] == "object"


def test_parse_openai(backend):
    data = {
        "choices": [{
            "message": {
                "content": "hello",
                "tool_calls": [{"index": 0, "id": "c1", "function": {"name": "grep", "arguments": '{"a":1}'}}],
            },
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    r = backend._parse_openai(data)
    assert r.content == "hello"
    assert r.tool_calls[0].name == "grep"
    assert r.tool_calls[0].parsed == {"a": 1}
    assert r.usage.input_tokens == 10


def test_parse_anthropic(backend):
    data = {
        "content": [
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "id": "c1", "name": "grep", "input": {"pattern": "x"}},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "stop_reason": "tool_use",
    }
    r = backend._parse_anthropic(data)
    assert r.content == "hi"
    assert r.tool_calls[0].name == "grep"
    assert r.tool_calls[0].parsed == {"pattern": "x"}


def test_assemble(backend):
    r = backend._assemble(
        ["hello"], {0: {"id": "c1", "name": "grep", "arguments": "{}"}},
        Usage(10, 5), "tool_use",
    )
    assert r.content == "hello"
    assert r.tool_calls[0].name == "grep"
    assert r.stop_reason == "tool_use"
