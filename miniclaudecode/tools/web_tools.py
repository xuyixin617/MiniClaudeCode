"""Web 工具：web_fetch / web_search（延迟激活）。

注意：这两个工具会访问外网，默认延迟激活以减少上下文占用；
只有用户输入命中关键词时才注入。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import httpx

from .base import Tool, ToolResult

if TYPE_CHECKING:
    from ..context import AgentContext

_MAX_FETCH = 20_000


def _html_to_text(html: str) -> str:
    """粗略 HTML -> 文本：去 script/style、去标签、压缩空白。"""
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"[ \t\r\f\v]+", " ", html).strip()


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "抓取一个 URL 的网页内容并转为纯文本。"
    lazy = True
    keywords = ["网页", "抓取", "url", "http", "链接", "网站", "fetch", "资料", "文档"]
    parameters = {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "要抓取的 URL"}},
        "required": ["url"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        url = args.get("url", "")
        if not url.startswith(("http://", "https://")):
            return ToolResult.error("URL 必须以 http:// 或 https:// 开头")
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                resp = await client.get(url, headers={"User-Agent": "MiniClaudeCode/0.1"})
                resp.raise_for_status()
        except Exception as exc:
            return ToolResult.error(f"抓取失败: {exc}")

        text = _html_to_text(resp.text)
        if len(text) > _MAX_FETCH:
            text = text[:_MAX_FETCH] + "\n... [已截断]"
        return ToolResult.ok(text or "(无正文)", url=url, status=resp.status_code)


class WebSearchTool(Tool):
    name = "web_search"
    description = "执行一次网页搜索，返回若干条结果的标题、链接与摘要。"
    lazy = True
    keywords = ["搜索", "查一下", "search", "搜索", "最新", "网络"]
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "limit": {"type": "integer", "description": "返回结果条数（默认 5）"},
        },
        "required": ["query"],
    }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        query = args.get("query", "")
        limit = int(args.get("limit") or 5)
        # 使用 DuckDuckGo 的 HTML 版做无密钥搜索，失败时优雅降级
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (MiniClaudeCode)"},
                )
                resp.raise_for_status()
        except Exception as exc:
            return ToolResult.error(f"搜索失败: {exc}")

        # 解析结果块：<a class="result__a" href="...">标题</a> ... <a class="result__snippet">摘要</a>
        html = resp.text
        results: list[str] = []
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
            if len(results) >= limit:
                break
            link = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            results.append(f"- {title}\n  {link}")

        if not results:
            return ToolResult.ok("(未解析到搜索结果，可能被反爬限制)")

        return ToolResult.ok("\n".join(results), count=len(results))
