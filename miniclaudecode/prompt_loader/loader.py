"""CLAUDE.md 层级加载与 @include 递归解析。

层级策略（就近优先）：
1. 从工作目录向上逐级查找 CLAUDE.md（含 .claude/CLAUDE.md）；
2. 追加用户全局 ~/.claude/CLAUDE.md（最低优先级）；
3. 每个文件内的 `@include <path>` 指令会被递归展开（相对该文件目录解析）；
4. 最终带入上下文的内容约束在 200 行以内，控制 token 开销。

@include 支持：`@include path/to/file.md`、`@include ./file.md`、`@include "file.md"`。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

MAX_LINES = 200          # CLAUDE.md 带入上下文的行数上限
MAX_INCLUDE_DEPTH = 10   # @include 递归深度上限（防环）

_INCLUDE_RE = re.compile(r'^\s*@include\s+(.+?)\s*$')


def _expand_includes(text: str, base_dir: Path, seen: set[str], depth: int = 0) -> str:
    """递归展开 @include 指令，seen 用于循环引用检测（回溯式：只保留当前链上的文件）。"""
    if depth > MAX_INCLUDE_DEPTH:
        # 超限：不再递归，把残留的 @include 行标成占位，避免原样流入最终文本
        marked: list[str] = []
        for line in text.splitlines():
            if _INCLUDE_RE.match(line):
                marked.append(f"[@include 嵌套过深，已跳过: {line.strip()}]")
            else:
                marked.append(line)
        return "\n".join(marked)
    out: list[str] = []
    for line in text.splitlines():
        m = _INCLUDE_RE.match(line)
        if not m:
            out.append(line)
            continue
        inc = m.group(1).strip().strip('"').strip("'")
        p = Path(inc)
        if not p.is_absolute():
            p = base_dir / p
        p = p.resolve()
        if str(p) in seen:
            out.append(f"[@include 已跳过（循环引用）: {inc}]")
            continue
        if not p.is_file():
            out.append(f"[@include 未找到: {inc}]")
            continue
        seen.add(str(p))
        try:
            sub = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            seen.discard(str(p))
            out.append(f"[@include 读取失败: {inc}]")
            continue
        out.append(_expand_includes(sub, p.parent, seen, depth + 1))
        seen.discard(str(p))  # 递归返回后回退，允许其他分支复用同一文件
    return "\n".join(out)


def _cap_lines(text: str, max_lines: int = MAX_LINES) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + f"\n... [CLAUDE.md 已截断，共 {len(lines)} 行，仅保留前 {max_lines} 行]"


def load_claude_md(start_dir: str, home_dir: Optional[str] = None) -> str:
    """层级加载 CLAUDE.md 并展开 @include，返回合并后的文本。"""
    start = Path(start_dir).resolve()
    home = Path(home_dir).expanduser().resolve() if home_dir else Path.home()

    sources: list[tuple[str, Path]] = []  # (内容, 该文件所在目录)
    seen_paths: set[str] = set()

    # 1) 从工作目录向上逐级查找
    d: Path = start
    while True:
        for name in ("CLAUDE.md", ".claude/CLAUDE.md"):
            p = d / name
            if p.is_file() and str(p) not in seen_paths:
                seen_paths.add(str(p))
                try:
                    sources.append((p.read_text(encoding="utf-8", errors="replace"), p.parent))
                except Exception:
                    pass
        if d.parent == d:
            break
        d = d.parent

    # 2) 用户全局
    for name in ("CLAUDE.md", "CLAUDE.local.md"):
        g = home / ".claude" / name
        if g.is_file() and str(g) not in seen_paths:
            seen_paths.add(str(g))
            try:
                sources.append((g.read_text(encoding="utf-8", errors="replace"), g.parent))
            except Exception:
                pass

    if not sources:
        return ""

    # 3) 展开 @include（以各文件自己的目录为相对基准）
    seen_includes: set[str] = set()
    expanded = [_expand_includes(content, base_dir, seen_includes) for content, base_dir in sources]

    combined = "\n\n".join(expanded)
    return _cap_lines(combined)
