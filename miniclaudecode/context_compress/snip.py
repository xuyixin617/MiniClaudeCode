"""stale snip —— 过期内容剪枝。

针对已经"过期"（距离当前较远）的工具返回结果做截短：只保留开头一小段 + 提示，
因为这些历史工具输出通常体积大、且对当前决策价值已衰减。
"""
from __future__ import annotations

from typing import Any

_SNIP_LEN = 200          # 剪枝后保留的字符数
_KEEP_RECENT = 6         # 保留最近 N 条工具结果不剪


def _snip(content: str) -> str:
    if len(content) <= _SNIP_LEN:
        return content
    return content[:_SNIP_LEN] + f"\n... [过期结果已剪枝，原 {len(content)} 字符]"


def stale_snip(messages: list[dict], keep_recent: int = _KEEP_RECENT) -> list[dict]:
    """把较早的工具返回截短，保留最近 keep_recent 条完整。"""
    # 从尾部统计最近的 tool 消息数量
    tool_indices = [i for i, m in enumerate(messages) if m["role"] == "tool"]
    keep_from = len(tool_indices) - keep_recent  # 保留最近 keep_recent 条

    result: list[dict] = list(messages)
    seen_tool = 0
    for i in tool_indices:
        if seen_tool < keep_from:
            m = result[i]
            m = dict(m)
            m["content"] = _snip(m.get("content", ""))
            result[i] = m
        seen_tool += 1
    return result
