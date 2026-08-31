"""slash 命令分发。"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from . import display

if TYPE_CHECKING:
    from .app import MiniClaudeApp

_HELP_TEXT = """\
[bold]可用命令：[/bold]
  /help                     显示本帮助
  /model <name>             切换模型
  /mode <name>              切换权限模式（default/plan/acceptEdits/bypassPermissions/dontAsk）
  /session list             列出历史会话
  /session save [name]      保存当前会话
  /session load <id>        恢复指定会话
  /tokens                   查看上下文用量与利用率
  /compact                  手动触发全量摘要压缩
  /memory                   查看跨会话记忆
  /tools                    查看工具激活状态
  /activate <tool>          激活指定工具
  /deactivate <tool>        停用指定工具
  /clear                    清空当前对话历史
  /exit | /quit             退出
"""


class SlashCommands:
    def __init__(self, app: "MiniClaudeApp") -> None:
        self.app = app

    async def dispatch(self, raw: str) -> bool:
        """处理 / 开头的命令，返回是否已处理。"""
        if not raw.startswith("/"):
            return False
        parts = raw[1:].strip().split()
        if not parts:
            return True
        cmd = parts[0].lower()
        arg = " ".join(parts[1:])
        handler = getattr(self, f"cmd_{cmd}", None)
        if handler is None:
            display.console.print(f"[red]未知命令 /{cmd}，输入 /help 查看。[/red]")
        else:
            try:
                await handler(arg)
            except Exception as exc:  # noqa: BLE001
                display.console.print(f"[red]命令执行失败: {exc}[/red]")
        return True

    # ------------------------------------------------------------------ #
    async def cmd_help(self, arg: str) -> None:
        display.console.print(_HELP_TEXT)

    async def cmd_model(self, arg: str) -> None:
        if not arg:
            display.console.print(f"当前模型: [bold]{self.app.config.model}[/bold]")
            return
        self.app.config.model = arg.strip()
        display.console.print(f"已切换模型: [bold]{self.app.config.model}[/bold]")

    async def cmd_mode(self, arg: str) -> None:
        from ..permission.modes import MODES, resolve_mode

        if not arg:
            display.console.print(f"当前权限模式: [bold]{self.app.permissions.mode}[/bold]")
            display.console.print("可选: " + ", ".join(MODES.keys()))
            return
        mode = resolve_mode(arg.strip())
        self.app.permissions.set_mode(mode)
        self.app.config.permission_mode = mode
        display.console.print(f"已切换权限模式: [bold]{mode}[/bold] — {MODES[mode].description}")

    async def cmd_session(self, arg: str) -> None:
        parts = arg.strip().split()
        sub = parts[0] if parts else "list"
        if sub == "list":
            sessions = self.app.session_store.list_sessions()
            if not sessions:
                display.console.print("(暂无保存的会话)")
                return
            for s in sessions:
                ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["updated_at"]))
                display.console.print(f"  [{s['session_id']}] {s['title'][:40]} · {ts} · {s['model']}")
        elif sub == "save":
            name = " ".join(parts[1:]) or self.app.title or "未命名"
            self.app.session_store.save(self.app.session_id, self.app.loop.history,
                                        {"title": name, "model": self.app.config.model,
                                         "mode": self.app.permissions.mode})
            display.console.print(f"已保存会话 [bold]{self.app.session_id}[/bold] — {name}")
        elif sub == "load":
            if len(parts) < 2:
                display.console.print("[red]用法: /session load <id>[/red]")
                return
            record = self.app.session_store.load(parts[1])
            if not record:
                display.console.print(f"[red]会话 {parts[1]} 不存在[/red]")
                return
            self.app.loop.restore_history(record.get("history", []))
            self.app.session_id = record.get("session_id", parts[1])
            self.app.title = record.get("title", "")
            if record.get("model"):
                self.app.config.model = record["model"]
            if record.get("mode"):
                self.app.permissions.set_mode(record["mode"])
                self.app.config.permission_mode = record["mode"]
            display.console.print(f"已恢复会话 [bold]{self.app.session_id}[/bold] — {record.get('title', '')}")
        else:
            display.console.print("[red]用法: /session list|save|load[/red]")

    async def cmd_tokens(self, arg: str) -> None:
        used = self.app.loop.current_tokens()
        util = self.app.compressor.utilization(used)
        bar = "#" * int(util * 40)
        display.console.print(
            f"上下文用量: [bold]{used}[/bold] token / 窗口 {self.app.config.context_window}"
            f"  ({util:.1%})\n[dim]{bar}{'.' * (40 - len(bar))}[/dim]"
        )

    async def cmd_compact(self, arg: str) -> None:
        before = self.app.loop.current_tokens()
        self.app.loop.history = await self.app.compressor.maybe_hard(self.app.loop.history, self.app.ctx)
        after = self.app.loop.current_tokens()
        display.console.print(f"压缩完成: {before} -> [bold]{after}[/bold] token")

    async def cmd_memory(self, arg: str) -> None:
        entries = await self.app.memory.list_all()
        if not entries:
            display.console.print("(暂无跨会话记忆)")
            return
        display.console.print(f"共 [bold]{len(entries)}[/bold] 条记忆：")
        for e in entries[:20]:
            tags = f" [dim]#{' #'.join(e.tags)}[/dim]" if e.tags else ""
            display.console.print(f"  [{e.entry_id}]{tags} {e.content[:80]}")

    async def cmd_tools(self, arg: str) -> None:
        active = set(t.name for t in self.app.tools.active_tools())
        for name in self.app.tools.names():
            mark = "[green]●[/green]" if name in active else "[dim]○[/dim]"
            lazy = "[dim]lazy[/dim]" if self.app.tools.get(name).lazy else ""
            display.console.print(f"  {mark} {name} {lazy}")

    async def cmd_activate(self, arg: str) -> None:
        if self.app.tools.activate(arg.strip()):
            display.console.print(f"已激活工具 [bold]{arg.strip()}[/bold]")
        else:
            display.console.print(f"[red]工具不存在: {arg.strip()}[/red]")

    async def cmd_deactivate(self, arg: str) -> None:
        self.app.tools.deactivate(arg.strip())
        display.console.print(f"已停用工具 [bold]{arg.strip()}[/bold]")

    async def cmd_clear(self, arg: str) -> None:
        self.app.loop.history = []
        self.app.title = ""
        display.console.print("已清空当前对话历史。")

    async def cmd_exit(self, arg: str) -> None:
        self.app.running = False

    async def cmd_quit(self, arg: str) -> None:
        self.app.running = False
