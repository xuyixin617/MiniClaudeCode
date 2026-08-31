"""文件工具：read_file / write_file / edit_file。

核心安全机制 —— read-before-edit + mtime 新鲜度校验：
1. 编辑前必须先 read_file，注册表会记录该文件的 mtime 与内容哈希；
2. edit_file 执行时校验磁盘上文件 mtime 是否与读取时一致，防止误改外部已变更的文件。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .base import Tool, ToolResult

if TYPE_CHECKING:
    from ..context import AgentContext


def _resolve(path: str, ctx: "AgentContext") -> Path:
    """把相对路径解析到工作目录下，并做越界保护。"""
    p = Path(path)
    if not p.is_absolute():
        p = Path(ctx.config.cwd) / p
    return p.resolve()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_state(ctx: "AgentContext", path: Path) -> dict:
    """读取/刷新文件状态并写入 ctx（供 edit 前新鲜度校验）。"""
    st = path.stat()
    state = {"mtime": st.st_mtime, "hash": _sha256(path.read_bytes())}
    states = getattr(ctx, "file_states", None)
    if states is None:
        states = {}
        ctx.file_states = states
    states[str(path)] = state
    return state


class ReadFileTool(Tool):
    name = "read_file"
    description = "读取文件内容。带行号输出，支持 offset/limit 分段读取，编辑文件前必须先调用本工具。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对或绝对）"},
            "offset": {"type": "integer", "description": "起始行号（可选，从 1 开始）"},
            "limit": {"type": "integer", "description": "读取行数（可选）"},
        },
        "required": ["path"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        path = _resolve(args["path"], ctx)
        if not path.exists():
            return ToolResult.error(f"文件不存在: {path}")
        if path.is_dir():
            return ToolResult.error(f"目标是目录而非文件: {path}")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult.error(f"读取失败: {exc}")

        lines = text.splitlines()
        offset = max(0, int(args.get("offset", 1)) - 1)
        limit = int(args.get("limit") or len(lines))
        selected = lines[offset:offset + limit]

        numbered = [f"{i + 1:>6}\t{line}" for i, line in enumerate(selected, start=offset)]
        _file_state(ctx, path)  # 记录新鲜度
        return ToolResult.ok("\n".join(numbered), lines=len(selected), total=len(lines), path=str(path))


class WriteFileTool(Tool):
    name = "write_file"
    description = "创建或整体覆盖一个文件。传入完整内容。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的完整内容"},
        },
        "required": ["path", "content"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        path = _resolve(args["path"], ctx)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args.get("content", ""), encoding="utf-8")
        except Exception as exc:
            return ToolResult.error(f"写入失败: {exc}")
        _file_state(ctx, path)
        return ToolResult.ok(f"已写入 {path}（{len(args.get('content', ''))} 字符）", path=str(path))


class EditFileTool(Tool):
    name = "edit_file"
    description = "对文件做精确字符串替换（old_string -> new_string）。必须先 read_file 且文件未被外部改动。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "old_string": {"type": "string", "description": "要被替换的原始文本（需与文件内容精确匹配）"},
            "new_string": {"type": "string", "description": "替换后的新文本"},
            "replace_all": {"type": "boolean", "description": "是否替换所有匹配项（默认只替换第一个）"},
        },
        "required": ["path", "old_string", "new_string"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        path = _resolve(args["path"], ctx)
        if not path.exists():
            return ToolResult.error(f"文件不存在: {path}")

        # ---- read-before-edit 校验 ----
        states = getattr(ctx, "file_states", {})
        if str(path) not in states:
            return ToolResult.error("拒绝编辑：尚未 read_file 读取过该文件（read-before-edit 保护）。")

        # ---- mtime 新鲜度校验 ----
        recorded_mtime = states[str(path)]["mtime"]
        current_mtime = path.stat().st_mtime
        if abs(current_mtime - recorded_mtime) > 1e-6:
            return ToolResult.error(
                f"拒绝编辑：文件已被外部改动（mtime 不一致）。请重新 read_file 后再编辑。"
            )

        old = args.get("old_string", "")
        new = args.get("new_string", "")
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            return ToolResult.error(f"读取失败: {exc}")

        count = text.count(old)
        if count == 0:
            return ToolResult.error("未找到 old_string，替换失败（注意精确匹配，包括空白与缩进）。")
        if args.get("replace_all"):
            text = text.replace(old, new)
            replaced = count
        else:
            text = text.replace(old, new, 1)
            replaced = 1

        try:
            path.write_text(text, encoding="utf-8")
        except Exception as exc:
            return ToolResult.error(f"写入失败: {exc}")

        _file_state(ctx, path)  # 刷新状态
        return ToolResult.ok(f"已替换 {replaced} 处（共匹配 {count} 处）", path=str(path), replaced=replaced)
