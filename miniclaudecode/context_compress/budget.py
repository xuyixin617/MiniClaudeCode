"""budget truncation —— 预算截断。

最基础的一级：按 token 预算对消息做 FIFO 截断，保留 system 与最近的消息，
当超预算时从最旧的非 system 消息开始丢弃。
"""
from __future__ import annotations

import json
from typing import Any

from ..agent_runtime.messages import estimate_tokens


def message_tokens(msg: dict) -> int:
    """估算单条消息 token。"""
    n = estimate_tokens(msg.get("content", ""))
    for tc in msg.get("tool_calls", []):
        n += estimate_tokens(json.dumps(tc, ensure_ascii=False))
    return n


def budget_truncate(messages: list[dict], max_tokens: int) -> list[dict]:
    """确保消息总 token 不超 max_tokens（从旧到新丢弃，system 恒保留）。"""
    # 分离 system 前缀
    system: list[dict] = []
    body: list[dict] = []
    for m in messages:
        (system if m["role"] == "system" else body).append(m)

    sys_cost = sum(message_tokens(m) for m in system)
    budget = max(0, max_tokens - sys_cost)

    kept: list[dict] = []
    used = 0
    # 从最新往前尽量保留
    for m in reversed(body):
        cost = message_tokens(m)
        if used + cost <= budget:
            kept.append(m)
            used += cost
        else:
            break
    kept.reverse()
    return system + kept
