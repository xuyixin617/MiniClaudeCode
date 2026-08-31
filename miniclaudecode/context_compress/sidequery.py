"""sideQuery 语义召回 + 异步预取 + 信息新鲜度提醒。

sideQuery：在每轮对话开始前，用用户输入作为查询去记忆库召回相关上下文，
把召回结果作为"侧边上下文"注入本轮对话，减少对原始对话历史的依赖。

异步预取：会话启动时后台预热记忆索引，避免首轮召回阻塞。

新鲜度提醒：基于 read_file 时记录的 mtime，检测文件是否被外部改动并提醒重读。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..context import AgentContext


async def side_query(ctx: "AgentContext", user_text: str, limit: int = 3) -> str:
    """语义召回相关记忆，返回注入用文本片段（空串表示无召回）。"""
    memory = getattr(ctx, "memory", None)
    if memory is None:
        return ""
    try:
        entries = await memory.recall(user_text, limit=limit)
    except Exception:
        return ""
    if not entries:
        return ""
    lines = ["[记忆召回]" + f" {e.content}" for e in entries]
    return "\n".join(lines)


async def prefetch_memory(ctx: "AgentContext") -> None:
    """异步预取：后台预热记忆索引（当前实现为加载/计数，可扩展为预热向量索引）。"""
    memory = getattr(ctx, "memory", None)
    if memory is None:
        return
    await asyncio.to_thread(lambda: memory.count())


def freshness_reminder(ctx: "AgentContext", path: str) -> Optional[str]:
    """检测文件是否自 read 后被外部改动，返回提醒文案（无则 None）。"""
    states = getattr(ctx, "file_states", {})
    state = states.get(str(Path(path).resolve()))
    if not state:
        return None
    try:
        current_mtime = Path(path).stat().st_mtime
    except OSError:
        return None
    if abs(current_mtime - state["mtime"]) > 1e-6:
        return f"⚠️ 文件 {path} 自上次读取后已被外部改动，建议重新 read_file。"
    return None
