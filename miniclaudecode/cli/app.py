"""CLI 应用 —— 装配全部子系统并运行交互式 REPL。"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from ..config import Config
from ..context import AgentContext
from ..agent_runtime.backend import BackendError, LLMBackend
from ..agent_runtime.loop import AgentLoop
from ..tools.defaults import build_default_registry
from ..permission.manager import PermissionManager
from ..context_compress.memory import MemoryStore
from ..context_compress.pipeline import ContextCompressor
from ..context_compress.sidequery import prefetch_memory
from ..prompt_loader.loader import load_claude_md
from ..rag import RagEngine, build_embedding_fn
from . import display
from .session import SessionStore
from .slash import SlashCommands

_PERMISSION_HINT = "允许(y) / 总是允许(a) / 拒绝(n)"


class MiniClaudeApp:
    def __init__(self, config: Config) -> None:
        self.config = config
        config.ensure_dirs()

        # 共享上下文容器
        self.ctx = AgentContext(config)

        # 子系统
        self.backend = LLMBackend(config)
        self.tools = build_default_registry()
        self.permissions = PermissionManager(config)
        # 语义嵌入：RAG 与跨会话记忆共用同一个 embedding_fn（有密钥走 GLM，无密钥 None）
        embedding_fn = build_embedding_fn(config.base_url, config.api_key)
        self.memory = MemoryStore(
            str(Path(config.data_dir) / "memory.json"),
            embedding_fn=embedding_fn if config.api_key else None,
        )
        self.rag = RagEngine(str(Path(config.data_dir) / "rag.db"), embedding_fn=embedding_fn)
        self.compressor = ContextCompressor(config, self.backend)
        self.session_store = SessionStore(config.data_dir)

        # 回填 ctx 依赖
        self.ctx.tools = self.tools
        self.ctx.permissions = self.permissions
        self.ctx.memory = self.memory
        self.ctx.rag = self.rag
        self.ctx.backend = self.backend

        # Agent 主循环
        self.loop = AgentLoop(self.ctx, self.backend, self.tools, self.permissions, self.compressor)
        self.claude_content = load_claude_md(config.cwd)
        self.loop.set_system_prompt(self.claude_content)

        # 权限交互回调
        self.permissions.set_ask_callback(self._ask_permission)

        # 会话与状态
        self.session_id = self.session_store.new_id()
        self.title = ""
        self.running = True
        self.slash = SlashCommands(self)

    # ------------------------------------------------------------------ #
    # 权限确认（异步，经 to_thread 阻塞读取用户输入）
    # ------------------------------------------------------------------ #
    async def _ask_permission(self, tool_name: str, args: dict, reason: str) -> str:
        def _sync_prompt() -> str:
            display.print_permission_prompt(tool_name, args, reason)
            ans = input(f"  {_PERMISSION_HINT} > ").strip().lower()
            return ans

        ans = await asyncio.to_thread(_sync_prompt)
        if ans in ("y", "yes", "allow", ""):
            return "allow"
        if ans in ("a", "always", "allow_always"):
            return "allow_always"
        return "deny"

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #
    async def run(self) -> None:
        display.print_welcome(self.config.model, self.permissions.mode, self.config.provider)
        await prefetch_memory(self.ctx)

        while self.running:
            try:
                line = await asyncio.to_thread(self._read_line)
            except (EOFError, KeyboardInterrupt):
                display.console.print("\n[dim]再见！[/dim]")
                break

            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                await self.slash.dispatch(line)
                continue
            await self._handle_message(line)

        await self.backend.close()
        self.rag.close()

    def _read_line(self) -> str:
        display.console.print("[bold blue]›[/bold blue] ", end="")
        return input()

    # ------------------------------------------------------------------ #
    async def _handle_message(self, text: str) -> None:
        self.ctx.aborted = False
        if not self.title:
            self.title = text[:30]

        def on_event(evt: str, payload) -> None:
            if evt == "tool_call":
                display.print_tool_call(payload.name, payload.parsed)
            elif evt == "tool_result":
                display.print_tool_result(payload["name"], payload["is_error"])

        stream_writer, state = display.make_stream_writer()
        stream_cb = stream_writer if self.config.enable_stream else None

        try:
            answer = await self.loop.run(text, stream_cb=stream_cb, on_event=on_event)
        except BackendError as exc:
            display.console.print(f"[red]后端错误: {exc}[/red]")
            return
        except Exception as exc:  # noqa: BLE001
            display.console.print(f"[red]运行错误: {exc}[/red]")
            return

        if self.config.enable_stream:
            display.finish_stream(state)
        elif answer:
            display.print_markdown(answer)

        self._autosave()

    def _autosave(self) -> None:
        """每轮结束自动保存会话，便于崩溃/中断后恢复。"""
        try:
            self.session_store.save(
                self.session_id, self.loop.history,
                {"title": self.title or "未命名", "model": self.config.model,
                 "mode": self.permissions.mode},
            )
        except Exception:
            pass  # 自动保存失败不影响交互
