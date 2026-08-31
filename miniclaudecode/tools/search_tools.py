"""搜索工具：glob（文件查找）/ grep（内容检索）。

纯 Python 实现，避免依赖系统 grep/find，天然跨平台。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from .base import Tool, ToolResult

if TYPE_CHECKING:
    from ..context import AgentContext

# grep 默认跳过的大型/二进制文件后缀
_BINARY_EXT = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".exe", ".dll", ".so", ".dylib",
               ".pdf", ".woff", ".woff2", ".ttf", ".ico", ".mp3", ".mp4", ".bin"}
_MAX_GLOB_RESULTS = 200
_MAX_GREP_RESULTS = 100


class GlobTool(Tool):
    name = "glob"
    description = "按 glob 模式查找文件（如 '**/*.py'）。返回匹配的文件路径列表。"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob 模式"},
            "path": {"type": "string", "description": "搜索根目录（可选，默认工作目录）"},
        },
        "required": ["pattern"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        root = Path(args.get("path") or ctx.config.cwd)
        pattern = args["pattern"]
        matches = sorted(str(p) for p in root.glob(pattern) if not _is_hidden(p))
        if len(matches) > _MAX_GLOB_RESULTS:
            matches = matches[:_MAX_GLOB_RESULTS]
            truncated = True
        else:
            truncated = False
        out = "\n".join(matches) if matches else "(无匹配结果)"
        if truncated:
            out += f"\n... [已截断，仅显示前 {_MAX_GLOB_RESULTS} 条]"
        return ToolResult.ok(out, count=len(matches))


def _is_hidden(p: Path) -> bool:
    return any(part.startswith(".") for part in p.parts)


class GrepTool(Tool):
    name = "grep"
    description = "在文件内容中按正则表达式检索，返回匹配行及其文件位置。"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "path": {"type": "string", "description": "搜索目录（可选，默认工作目录）"},
            "glob": {"type": "string", "description": "文件名过滤，如 '*.py'（可选）"},
            "ignore_case": {"type": "boolean", "description": "是否忽略大小写"},
        },
        "required": ["pattern"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        root = Path(args.get("path") or ctx.config.cwd)
        try:
            rx = re.compile(args["pattern"], re.IGNORECASE if args.get("ignore_case") else 0)
        except re.error as exc:
            return ToolResult.error(f"正则表达式无效: {exc}")

        file_glob = args.get("glob")
        results: list[str] = []
        matched_files = 0
        total_matches = 0

        iterator = root.rglob(file_glob or "*") if file_glob else root.rglob("*")
        for p in iterator:
            if not p.is_file() or _is_hidden(p) or p.suffix.lower() in _BINARY_EXT:
                continue
            if total_matches >= _MAX_GREP_RESULTS:
                break
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if rx.search(line):
                    results.append(f"{p}:{lineno}: {line.strip()}")
                    total_matches += 1
                    if total_matches >= _MAX_GREP_RESULTS:
                        break
            if results and results[-1].startswith(str(p)):
                matched_files += 1

        if not results:
            return ToolResult.ok("(无匹配结果)")
        out = "\n".join(results)
        if total_matches >= _MAX_GREP_RESULTS:
            out += f"\n... [已截断，达到 {_MAX_GREP_RESULTS} 条上限]"
        return ToolResult.ok(out, matches=total_matches, files=matched_files)
