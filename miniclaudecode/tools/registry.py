"""工具注册表 —— 负责注册、延迟激活、执行与并发回退。

延迟激活策略：
- `lazy=False` 的工具为"常驻工具"，始终注入上下文；
- `lazy=True` 的工具默认隐藏，只有用户输入命中其 keywords（或显式 /activate）时才激活，
  从而减少无关工具对上下文 token 的占用。

执行策略：
- 多工具调用优先 asyncio.gather 并发执行；
- 一旦并发执行异常，自动回退为串行执行，保证稳定性。
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from .base import Tool, ToolResult

if TYPE_CHECKING:
    from ..context import AgentContext

# 工具返回结果体积控制（上下文利用率上升时会被收紧）
DEFAULT_MAX_OUTPUT = 30_000      # 默认单工具输出上限（字符）
TIGHT_MAX_OUTPUT = 8_000         # 上下文紧张时的收紧上限


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._active: set[str] = set()          # 当前激活（注入上下文）的工具名
        self._ever_used: set[str] = set()

    # ------------------------------------------------------------------ #
    # 注册与激活
    # ------------------------------------------------------------------ #
    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        if not tool.lazy:
            self._active.add(tool.name)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def activate(self, name: str) -> bool:
        """显式激活一个工具，返回是否成功。"""
        if name in self._tools:
            self._active.add(name)
            return True
        return False

    def deactivate(self, name: str) -> None:
        self._active.discard(name)

    def active_tools(self) -> list[Tool]:
        """按注册顺序返回当前激活的工具。"""
        return [t for name, t in self._tools.items() if name in self._active]

    def active_schemas(self) -> list[dict]:
        return [t.schema() for t in self.active_tools()]

    def lazy_activate_by_text(self, user_text: str) -> list[str]:
        """根据用户输入关键词自动激活延迟工具，返回本次新激活的工具名。"""
        newly: list[str] = []
        low = user_text.lower()
        for tool in self._tools.values():
            if tool.lazy and tool.name not in self._active:
                if any(kw.lower() in low for kw in tool.keywords):
                    self._active.add(tool.name)
                    newly.append(tool.name)
        return newly

    # ------------------------------------------------------------------ #
    # 执行
    # ------------------------------------------------------------------ #
    def _truncate(self, output: str, budget: int) -> str:
        if len(output) <= budget:
            return output
        head = output[: budget // 2]
        tail = output[-(budget // 2):]
        return f"{head}\n... [输出过长，已截断中间 {len(output) - budget} 字符] ...\n{tail}"

    async def run_tool(self, name: str, args: dict, ctx: "AgentContext") -> ToolResult:
        """执行单个工具，保证不向外抛异常（转为 error 结果）。"""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.error(f"未知工具: {name}")

        budget = TIGHT_MAX_OUTPUT if getattr(ctx, "tight_output", False) else DEFAULT_MAX_OUTPUT
        try:
            result = await tool.run(args or {}, ctx)
            if not isinstance(result, ToolResult):
                result = ToolResult.ok(str(result))
        except Exception as exc:  # noqa: BLE001
            result = ToolResult.error(f"工具 {name} 执行异常: {exc}")

        result.output = self._truncate(result.output, budget)
        self._ever_used.add(name)
        ctx.tool_call_count += 1
        return result

    async def run_tool_calls(self, tool_calls: list, ctx: "AgentContext") -> list[ToolResult]:
        """并发执行多个工具调用，异常时回退串行。

        Args:
            tool_calls: 规范化后的 ToolCall 列表。
        Returns:
            与 tool_calls 顺序对应的 ToolResult 列表。
        """
        if len(tool_calls) == 1:
            tc = tool_calls[0]
            return [await self.run_tool(tc.name, tc.parsed, ctx)]

        try:
            return list(await asyncio.gather(
                *[self.run_tool(tc.name, tc.parsed, ctx) for tc in tool_calls]
            ))
        except Exception:
            # 并发执行失败 -> 串行回退，保证至少能完成
            results: list[ToolResult] = []
            for tc in tool_calls:
                results.append(await self.run_tool(tc.name, tc.parsed, ctx))
            return results
