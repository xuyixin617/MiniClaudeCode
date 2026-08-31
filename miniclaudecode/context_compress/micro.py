"""microcompact —— 轻量微压缩。

不做 LLM 摘要，仅对单条消息体积做收紧：每条消息截断到上限（头尾保留），
同时折叠多余空白。成本低、无外部调用，适合在利用率中段（50%-70%）触发。
"""
from __future__ import annotations

import re

_DEFAULT_MAX = 4000       # 普通消息上限
_TOOL_MAX = 2000          # 工具返回消息上限（更激进）


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-(limit // 2):]
    return f"{head}\n... [microcompact 截断 {len(text) - limit} 字符] ...\n{tail}"


def microcompact(messages: list[dict], max_len: int = _DEFAULT_MAX, tool_max: int = _TOOL_MAX) -> list[dict]:
    """对消息内容做体积收紧。"""
    out: list[dict] = []
    for m in messages:
        m = dict(m)
        content = m.get("content", "")
        if isinstance(content, str):
            limit = tool_max if m["role"] == "tool" else max_len
            m["content"] = _trim(content, limit)
        out.append(m)
    return out
