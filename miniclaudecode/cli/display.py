"""展示辅助 —— 基于 Rich 的终端渲染。

集中管理配色与排版，方便后续统一调整 UI 风格。
"""
from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text


def _configure_utf8() -> None:
    """Windows 中文控制台（GBK）下，Rich 的 Legacy 渲染会因 ›⚙✓✗⛔ 等非 GBK 字符崩溃；
    把 stdout/stderr 重配为 UTF-8，避免 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


_configure_utf8()
console = Console()


def print_welcome(model: str, mode: str, provider: str) -> None:
    """启动横幅。"""
    title = Text("MiniClaudeCode", style="bold cyan")
    info = Text(f" 模型 {model} · 后端 {provider} · 权限 {mode}", style="dim")
    console.print()
    console.print(Panel(Text.assemble(title, "\n", info), border_style="cyan"))
    console.print("[dim]输入 /help 查看命令，Ctrl+C 中断，/exit 退出。[/dim]\n")


def make_stream_writer() -> tuple[Any, dict]:
    """返回 (stream_cb, state)。stream_cb 用于把增量文本流式打印到终端。"""
    state = {"started": False}

    def cb(text: str) -> None:
        if not state["started"]:
            console.print("[bold green]助手[/] ", end="")
            state["started"] = True
        console.print(text, end="", markup=False, highlight=False)

    return cb, state


def finish_stream(state: dict) -> None:
    """流式结束后补一个换行。"""
    if state.get("started"):
        console.print()


def print_markdown(text: str) -> None:
    console.print(Markdown(text))


def print_tool_call(name: str, args: dict) -> None:
    """展示工具调用。"""
    try:
        args_str = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)[:40]}" for k, v in (args or {}).items())
    except Exception:
        args_str = ""
    console.print(f"  [dim]⚙ {name}({args_str})[/dim]")


def print_tool_result(name: str, is_error: bool) -> None:
    mark = "✗" if is_error else "✓"
    style = "red" if is_error else "dim"
    console.print(f"    [{style}]{mark} {name}[/{style}]")


def print_permission_prompt(tool_name: str, args: dict, reason: str) -> None:
    """权限确认提示框。"""
    body = f"[bold]{tool_name}[/bold]\n[dim]{reason}[/dim]"
    if args:
        body += "\n" + json.dumps(args, ensure_ascii=False, indent=2)
    console.print(Panel(body, title="[bold yellow]权限确认[/bold yellow]", border_style="yellow"))


def print_denied(tool_name: str, reason: str) -> None:
    console.print(f"  [bold red]⛔ 已拒绝 {tool_name}: {reason}[/bold red]")


def print_info(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")
