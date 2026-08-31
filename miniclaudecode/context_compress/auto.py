"""auto-compact —— 全量摘要压缩。

当上下文利用率 >85% 时触发：调用 LLM 把较早的对话历史压缩为一段精炼摘要，
仅保留 system 提示与最近若干条消息，从而把上下文重新拉回安全水位。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ..agent_runtime.messages import user_message
from .budget import message_tokens

if TYPE_CHECKING:
    from ..config import Config

_SUMMARY_PROMPT = (
    "你是对话压缩器。请把下面的对话历史压缩为一段结构化中文摘要，"
    "必须保留：1) 用户目标与任务；2) 关键决策与结论；3) 已改动的文件与原因；"
    "4) 遇到的错误与修复方式；5) 当前进度与待办。控制在 800 字以内，只输出摘要正文。"
)


async def auto_compact(messages: list[dict], backend, config: "Config", keep: int = 6) -> list[dict]:
    """对较早历史做 LLM 摘要，返回压缩后的消息列表。"""
    if len(messages) <= keep + 2:
        return messages  # 太短无需压缩

    # 分离 system 前缀（system 提示必须保留）
    system: list[dict] = [m for m in messages if m["role"] == "system"]
    body: list[dict] = [m for m in messages if m["role"] != "system"]

    tail = body[-keep:]
    head = body[:-keep]

    # 若 head 内容极少则不压缩
    if sum(message_tokens(m) for m in head) < 2000:
        return messages

    head_text = "\n\n".join(
        f"[{m['role']}]\n{m.get('content', '')}" for m in head
    )[:24_000]

    try:
        summary_result = await backend.chat(
            [user_message(_SUMMARY_PROMPT + "\n\n===== 对话历史 =====\n" + head_text)],
            tools=None,
        )
        summary = summary_result.content.strip() or "(摘要生成失败)"
    except Exception:
        summary = "(摘要生成失败，保留原文)"
        return messages

    summary_msg = user_message(f"[对话历史摘要]\n{summary}")
    return system + [summary_msg] + tail
