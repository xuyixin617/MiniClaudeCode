"""消息模型 —— 采用 OpenAI 兼容的规范化格式作为内部表示。

对话历史是一串 dict，规范化字段：
- 用户/助手/系统消息: {"role": "user"|"assistant"|"system", "content": str}
- 助手工具调用:      {"role": "assistant", "content": str, "tool_calls": [ToolCall...]}
- 工具返回:          {"role": "tool", "tool_call_id": str, "name": str, "content": str}

这样便于直接对接 OpenAI 兼容后端，Anthropic 后端由 backend.py 负责翻译。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCall:
    """助手发起的一次工具调用（规范化后的结构）。"""

    id: str
    name: str
    arguments: str = "{}"                 # 原始 JSON 字符串
    parsed: dict = field(default_factory=dict)  # 已解析的参数 dict

    @classmethod
    def from_openai(cls, raw: dict) -> "ToolCall":
        fn = raw.get("function", {})
        arguments = fn.get("arguments", "") or "{}"
        try:
            import json

            parsed = json.loads(arguments) if arguments else {}
        except Exception:
            parsed = {}
        return cls(id=raw.get("id", ""), name=fn.get("name", ""),
                   arguments=arguments, parsed=parsed if isinstance(parsed, dict) else {})

    def to_openai(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class Usage:
    """一次 API 调用的 token 消耗。"""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMResult:
    """后端返回的规范化结果。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = "stop"             # stop / tool_use / length / error


# ---- 便捷构造器 ----

def system_message(text: str) -> dict:
    return {"role": "system", "content": text}


def user_message(text: str) -> dict:
    return {"role": "user", "content": text}


def assistant_message(text: str, tool_calls: Optional[list[ToolCall]] = None) -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = [tc.to_openai() for tc in tool_calls]
    return msg


def tool_message(tool_call_id: str, name: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": content}


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：英文/代码约 4 字符一 token，中文约 1.5 字一 token。

    不引入 tiktoken 重依赖，用启发式估计，足够用于上下文利用率判断。
    """
    if not text:
        return 0
    import re

    cjk = len(re.findall(r"[一-鿿]", text))
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4) + 1
