"""元工具：todo_write / task（子代理）/ 记忆三件套（memory_save / memory_recall / list_memory）。"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .base import Tool, ToolResult
from ..agent_runtime.messages import assistant_message, tool_message, user_message

if TYPE_CHECKING:
    from ..context import AgentContext


class TodoWriteTool(Tool):
    name = "todo_write"
    description = "创建/更新任务清单。传入完整 todos 列表（含 id/status/content），用于跟踪多步骤任务。"
    parameters = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "任务列表，每项含 id、status(pending/in_progress/completed)、content",
                "items": {"type": "object"},
            }
        },
        "required": ["todos"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        todos = args.get("todos", [])
        ctx.todos = todos
        lines = []
        for t in todos:
            status = {"pending": "☐", "in_progress": "▣", "completed": "☑"}.get(t.get("status"), "·")
            lines.append(f"{status} [{t.get('id')}] {t.get('content')}")
        return ToolResult.ok("当前任务清单：\n" + ("\n".join(lines) if lines else "(空)"))


class TaskTool(Tool):
    name = "task"
    description = "启动一个受限子代理独立完成子任务（自带工具与权限），返回其最终结论。用于分解复杂任务。"
    lazy = True
    keywords = ["子任务", "子代理", "分派", "subagent", "拆分", "并行"]
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "子任务描述"},
            "max_rounds": {"type": "integer", "description": "子代理最大工具往返次数（默认 8）"},
        },
        "required": ["prompt"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        prompt = args.get("prompt", "")
        max_rounds = min(int(args.get("max_rounds") or 8), 16)

        backend = getattr(ctx, "backend", None)
        if backend is None:
            return ToolResult.error("子代理不可用：缺少 LLM backend")

        # 受限子循环：复用当前 backend / tools / permissions
        messages = [
            {"role": "system", "content": "你是子代理。独立完成给定任务，可调用工具，最终返回简洁结论。"},
            user_message(prompt),
        ]
        tools = ctx.tools.active_schemas()

        final_text = ""
        for _ in range(max_rounds):
            if ctx.aborted:
                break
            result = await backend.chat(messages, tools=tools)
            if result.tool_calls:
                # 子代理也过权限
                tool_results = []
                for tc in result.tool_calls:
                    decision = await ctx.permissions.check(tc.name, tc.parsed)
                    if decision.status == "deny":
                        tool_results.append(tool_message(tc.id, tc.name, f"[权限拒绝] {decision.reason}"))
                        continue
                    r = await ctx.tools.run_tool(tc.name, tc.parsed, ctx)
                    tool_results.append(tool_message(tc.id, tc.name, r.output))
                messages.append(assistant_message(result.content, result.tool_calls))
                messages.extend(tool_results)
                continue
            final_text = result.content
            break

        return ToolResult.ok(final_text or "(子代理无输出)")


class MemorySaveTool(Tool):
    name = "memory_save"
    description = "把一条重要信息写入跨会话记忆（含标签），供未来会话召回。"
    lazy = True
    keywords = ["记住", "记忆", "保存到记忆", "memorize", "以后记得"]
    parameters = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要记住的内容"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表（可选）"},
        },
        "required": ["content"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        memory = getattr(ctx, "memory", None)
        if memory is None:
            return ToolResult.error("记忆模块未初始化")
        entry_id = await memory.save(args.get("content", ""), args.get("tags") or [])
        return ToolResult.ok(f"已写入记忆 {entry_id}")


class MemoryRecallTool(Tool):
    name = "memory_recall"
    description = "语义召回与查询相关的历史记忆。"
    lazy = True
    keywords = ["回忆", "想起", "之前", "历史记忆", "recall", "上次"]
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "查询关键词/句子"},
            "limit": {"type": "integer", "description": "返回条数（默认 5）"},
        },
        "required": ["query"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        memory = getattr(ctx, "memory", None)
        if memory is None:
            return ToolResult.error("记忆模块未初始化")
        entries = await memory.recall(args.get("query", ""), int(args.get("limit") or 5))
        if not entries:
            return ToolResult.ok("(无相关记忆)")
        lines = [f"- {e.content}" for e in entries]
        return ToolResult.ok("\n".join(lines), count=len(entries))


class ListMemoryTool(Tool):
    name = "list_memory"
    description = "列出全部已保存的跨会话记忆。"
    lazy = True
    keywords = ["列出记忆", "有哪些记忆", "list memory"]
    parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        memory = getattr(ctx, "memory", None)
        if memory is None:
            return ToolResult.error("记忆模块未初始化")
        entries = await memory.list_all()
        if not entries:
            return ToolResult.ok("(暂无记忆)")
        lines = [f"[{e.entry_id}] {e.content}" for e in entries]
        return ToolResult.ok("\n".join(lines), count=len(entries))
