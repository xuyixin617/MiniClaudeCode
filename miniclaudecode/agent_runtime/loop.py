"""Agent 主循环 —— 把「模型 ↔ 工具」的往返编排起来。

单轮处理流程：
1. 按用户输入做工具延迟激活；
2. sideQuery 召回跨会话记忆；
3. 组装多层级 system prompt；
4. 进入工具往返循环：调用模型 -> 权限预检 -> 并发执行工具（失败回退串行）-> 注入结果；
5. 每轮根据上下文利用率触发软/硬压缩；
6. 模型返回纯文本时结束本轮，返回最终答案。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from .messages import (
    assistant_message,
    estimate_tokens,
    system_message,
    tool_message,
    user_message,
)

if TYPE_CHECKING:
    from ..context import AgentContext
    from .backend import LLMBackend
    from ..tools.registry import ToolRegistry
    from ..permission.manager import PermissionManager
    from ..context_compress.pipeline import ContextCompressor
    from ..prompt_loader.system_prompt import build_system_prompt  # noqa: F401

# 流式回调类型
StreamCallback = Callable[[str], Any]


class AgentLoop:
    def __init__(
        self,
        ctx: "AgentContext",
        backend: "LLMBackend",
        tools: "ToolRegistry",
        permissions: "PermissionManager",
        compressor: "ContextCompressor",
    ) -> None:
        self.ctx = ctx
        self.backend = backend
        self.tools = tools
        self.permissions = permissions
        self.compressor = compressor

        self.history: list[dict] = []          # 对话历史（不含 system）
        self.system_prompt: str = ""
        self.claude_content: str = ""

    # ------------------------------------------------------------------ #
    def set_system_prompt(self, claude_content: str) -> None:
        self.claude_content = claude_content

    def restore_history(self, history: list[dict]) -> None:
        """会话恢复：注入历史消息。"""
        self.history = list(history)

    # ------------------------------------------------------------------ #
    async def run(
        self,
        user_text: str,
        stream_cb: Optional[StreamCallback] = None,
        on_event: Optional[Callable[[str, Any], Any]] = None,
    ) -> str:
        """处理一条用户消息，返回最终回复文本。

        Args:
            user_text: 用户输入。
            stream_cb: 流式文本回调（收到增量即调用）。
            on_event: 事件回调（tool_call / tool_result），供 CLI 展示工具活动。
        """
        if not user_text.strip():
            return ""

        # 1) 工具延迟激活
        newly = self.tools.lazy_activate_by_text(user_text)

        # 2) sideQuery 语义召回
        from ..context_compress.sidequery import side_query

        memory_content = await side_query(self.ctx, user_text)

        # 3) 组装 system prompt（多层级）
        from ..prompt_loader.system_prompt import build_system_prompt

        system = build_system_prompt(self.ctx, self.claude_content, memory_content)
        self.system_prompt = system  # 缓存完整 system，供 current_tokens 准确估算

        # 4) 追加用户消息
        self.history.append(user_message(user_text))

        # 5) 工具往返循环
        final_answer = ""
        for _ in range(self.ctx.config.max_tool_rounds):
            if self.ctx.aborted:
                break

            messages = [system_message(system)] + self.history
            # 软压缩：收紧/剪枝/微压缩 + 预算兜底
            messages = self.compressor.maybe_soft(messages, self.ctx)

            result = await self.backend.chat(messages, tools=self.tools.active_schemas(), stream_cb=stream_cb)
            self.ctx.token_used += result.usage.total

            if not result.tool_calls:
                final_answer = result.content
                if result.content:
                    self.history.append(assistant_message(result.content))
                break

            # 模型发起了工具调用：先记录 assistant 消息
            self.history.append(assistant_message(result.content, result.tool_calls))
            for tc in result.tool_calls:
                if on_event:
                    on_event("tool_call", tc)

            # 权限预检（串行，保证交互式确认不打架）
            tool_results: list[dict] = [None] * len(result.tool_calls)  # type: ignore
            runnable: list[tuple[int, Any]] = []
            for i, tc in enumerate(result.tool_calls):
                decision = await self.permissions.check(tc.name, tc.parsed)
                if decision.status == "deny":
                    tool_results[i] = tool_message(tc.id, tc.name, f"[权限拒绝] {decision.reason}")
                else:
                    runnable.append((i, tc))

            # 并发执行工具（registry 内部已做失败回退串行）
            if runnable:
                tcs = [tc for _, tc in runnable]
                outs = await self.tools.run_tool_calls(tcs, self.ctx)
                for (i, tc), r in zip(runnable, outs):
                    tool_results[i] = tool_message(tc.id, tc.name, r.output)
                    if on_event:
                        on_event("tool_result", {"name": tc.name, "is_error": r.is_error})

            self.history.extend(tool_results)

            # 硬压缩：>85% 触发 auto-compact
            self.history = await self.compressor.maybe_hard(self.history, self.ctx)

        return final_answer or "(未产生回复，可能触达工具往返上限)"

    # ------------------------------------------------------------------ #
    def current_tokens(self) -> int:
        """估算当前历史总 token（含 system 与项目指令）。

        system_prompt 在每轮 run() 时被赋值为完整多层级 system（已含 CLAUDE.md 与动态层）；
        尚未运行过一轮时为空串，退回仅估算项目指令，避免漏算。
        """
        total = estimate_tokens(self.system_prompt) or estimate_tokens(self.claude_content)
        for m in self.history:
            total += estimate_tokens(m.get("content", ""))
            for tc in m.get("tool_calls", []):
                total += estimate_tokens(str(tc))
        return total
