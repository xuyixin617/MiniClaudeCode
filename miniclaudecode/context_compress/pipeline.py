"""上下文压缩流水线编排 —— 4 级渐进式 + 利用率触发。

触发策略：
- 利用率 >= 50%（tighten_ratio）：收紧工具返回体积（ctx.tight_output=True）。
- 利用率 >= 70%（soft_ratio）：microcompact 微压缩 + stale_snip 剪枝。
- 利用率 > 85%（hard_ratio）：auto-compact 全量 LLM 摘要。

各级之间是"渐进增强"关系：先廉价截断，再剪枝/微压缩，最后才动用 LLM 全量摘要。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .budget import budget_truncate
from .micro import microcompact
from .snip import stale_snip
from .auto import auto_compact

if TYPE_CHECKING:
    from ..context import AgentContext

TIGHTEN_RATIO = 0.50   # 开始收紧工具输出体积


class ContextCompressor:
    def __init__(self, config, backend) -> None:
        self.config = config
        self.backend = backend

    def utilization(self, token_used: int) -> float:
        """上下文利用率 = 已用 token / 窗口。"""
        if self.config.context_window <= 0:
            return 0.0
        return token_used / self.config.context_window

    def maybe_soft(self, messages: list[dict], ctx: "AgentContext") -> list[dict]:
        """软压缩（同步、廉价）：收紧 + 微压缩 + 剪枝。每次调用前由 loop 触发。"""
        util = self.utilization(ctx.token_used)

        # 1) 收紧工具输出体积
        ctx.tight_output = util >= TIGHTEN_RATIO

        # 2) 中段：microcompact + stale_snip
        if util >= self.config.compact_soft_ratio:
            messages = stale_snip(messages)
            messages = microcompact(messages)

        # 3) 始终做一次预算兜底
        messages = budget_truncate(messages, max(1, self.config.context_window))
        return messages

    async def maybe_hard(self, messages: list[dict], ctx: "AgentContext") -> list[dict]:
        """硬压缩（异步、LLM）：>85% 触发 auto-compact。"""
        util = self.utilization(ctx.token_used)
        if util >= self.config.compact_hard_ratio and self.backend is not None:
            messages = await auto_compact(messages, self.backend, self.config)
        return messages
