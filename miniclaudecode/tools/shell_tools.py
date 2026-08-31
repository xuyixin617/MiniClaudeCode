"""Shell 工具：执行系统命令。

安全说明：真正的危险命令拦截在 permission 层完成（详见 permission.dangerous）。
本工具只负责执行与输出收敛，不做拦截判断。
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from typing import TYPE_CHECKING

from .base import Tool, ToolResult

if TYPE_CHECKING:
    from ..context import AgentContext

_MAX_OUTPUT = 20_000          # 执行结果最大输出
_TIMEOUT = 120                # 命令超时秒数


class BashTool(Tool):
    name = "bash"
    description = "在系统 shell 中执行一条命令并返回 stdout/stderr。用于编译、测试、git 等操作。"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "timeout": {"type": "integer", "description": "超时秒数（可选，默认 120）"},
        },
        "required": ["command"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        command = args.get("command", "")
        if not command.strip():
            return ToolResult.error("命令为空")

        timeout = int(args.get("timeout") or _TIMEOUT)
        cwd = ctx.config.cwd

        # Windows 用 cmd.exe / POSIX 用 sh；shell=True 时参数即完整命令行
        shell = os.environ.get("COMSPEC") or ("cmd.exe" if os.name == "nt" else "/bin/sh")

        def _run() -> tuple[int, str, str]:
            proc = subprocess.run(
                command, shell=True, cwd=cwd, capture_output=True, text=True,
                timeout=timeout, encoding="utf-8", errors="replace",
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""

        try:
            code, stdout, stderr = await asyncio.to_thread(_run)
        except subprocess.TimeoutExpired:
            return ToolResult.error(f"命令超时（>{timeout}s）: {command}")

        out = stdout.rstrip()
        if stderr.strip():
            out += ("\n" if out else "") + "[stderr]\n" + stderr.rstrip()
        if len(out) > _MAX_OUTPUT:
            out = out[:_MAX_OUTPUT] + f"\n... [已截断 {len(out) - _MAX_OUTPUT} 字符]"
        if not out:
            out = "(无输出)"

        return ToolResult.ok(out, exit_code=code) if code == 0 else ToolResult.error(out, exit_code=code)
