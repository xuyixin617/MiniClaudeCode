"""RAG 工具：rag_index / rag_search / rag_list（延迟激活）。

三者默认不注入上下文，命中关键词才激活，避免占用 token。它们通过 ``ctx.rag``
访问 RagEngine，本身不含任何检索逻辑 —— 与既有工具的解耦方式一致。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .base import Tool, ToolResult

if TYPE_CHECKING:
    from ..context import AgentContext

# 目录索引时跳过的大型/二进制后缀（避免误索引 node_modules / 构建产物）
_SKIP_EXT = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".exe", ".dll", ".so",
             ".dylib", ".pdf", ".woff", ".woff2", ".ttf", ".ico", ".mp3", ".mp4",
             ".bin", ".jar", ".class", ".o", ".a", ".obj", ".db", ".sqlite", ".lock"}
_MAX_FILE_BYTES = 1_000_000   # 单文件超过 1MB 跳过，控制入库体积


class RagIndexTool(Tool):
    name = "rag_index"
    description = "把一个文件/目录（或一段原始文本）索引进本地知识库，供 rag_search 语义检索。"
    lazy = True
    keywords = ["索引", "入库", "知识库", "建库", "索引文档", "index", "rag"]
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要索引的文件或目录路径（可选，相对工作目录）"},
            "content": {"type": "string", "description": "要索引的原始文本（可选，与 path 二选一）"},
            "title": {"type": "string", "description": "文档标题（可选）"},
        },
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        rag = getattr(ctx, "rag", None)
        if rag is None:
            return ToolResult.error("RAG 引擎未初始化")

        path = args.get("path")
        content = args.get("content")
        title = args.get("title") or ""

        if path:
            p = Path(path)
            if not p.is_absolute():
                p = Path(ctx.config.cwd) / p
            if not p.exists():
                return ToolResult.error(f"路径不存在: {p}")

            files = [p] if p.is_file() else self._collect_files(p)
            doc_ids: list = []
            for f in files:
                try:
                    doc_ids.append(rag.index_file(str(f), title=title))
                except Exception:
                    continue
            if not doc_ids:
                return ToolResult.error(f"未索引到任何文件: {path}")
            return ToolResult.ok(f"已索引 {len(doc_ids)} 个文件", count=len(doc_ids))

        if content:
            doc_id = rag.index_text("inline", content, title=title or "内联文本")
            return ToolResult.ok(f"已索引文本 {doc_id}", doc_id=doc_id)

        return ToolResult.error("请提供 path 或 content 之一")

    @staticmethod
    def _collect_files(root: Path) -> list:
        out: list = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() in _SKIP_EXT:
                continue
            try:
                if p.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            out.append(p)
        return out


class RagSearchTool(Tool):
    name = "rag_search"
    description = "在已索引的知识库中按语义检索相关片段，返回来源与正文。"
    lazy = True
    keywords = ["检索", "查资料", "知识库查询", "相关知识", "查文档", "rag", "search"]
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "查询问题或关键词"},
            "limit": {"type": "integer", "description": "返回条数（默认 5）"},
        },
        "required": ["query"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        rag = getattr(ctx, "rag", None)
        if rag is None:
            return ToolResult.error("RAG 引擎未初始化")

        query = args.get("query", "")
        if not query.strip():
            return ToolResult.error("查询为空")
        hits = rag.search(query, int(args.get("limit") or 5))
        if not hits:
            return ToolResult.ok("(知识库为空或未检索到相关内容，可先用 rag_index 索引文档)")

        lines = []
        for h in hits:
            src = h.title or h.source
            lines.append(f"### {src}  (相关度 {h.score:.2f})\n{h.text}")
        return ToolResult.ok("\n\n".join(lines), count=len(hits))


class RagListTool(Tool):
    name = "rag_list"
    description = "列出知识库中已索引的文档。"
    lazy = True
    keywords = ["列出知识库", "有哪些文档", "索引列表", "知识库列表", "rag list"]
    parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        rag = getattr(ctx, "rag", None)
        if rag is None:
            return ToolResult.error("RAG 引擎未初始化")

        docs = rag.list_indexed()
        if not docs:
            return ToolResult.ok("(知识库为空)")
        lines = [f"[{d.doc_id}] {d.title or d.source} ({len(d.content)} 字符)" for d in docs]
        return ToolResult.ok("\n".join(lines), count=len(docs))
