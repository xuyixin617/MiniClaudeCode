"""默认工具集装配 —— 注册全部 16 个核心工具。"""
from __future__ import annotations

from .registry import ToolRegistry
from .file_tools import ReadFileTool, WriteFileTool, EditFileTool
from .search_tools import GlobTool, GrepTool
from .shell_tools import BashTool
from .web_tools import WebFetchTool, WebSearchTool
from .meta_tools import TodoWriteTool, TaskTool, MemorySaveTool, MemoryRecallTool, ListMemoryTool
from .rag_tools import RagIndexTool, RagSearchTool, RagListTool


def build_default_registry() -> ToolRegistry:
    """构建并注册 16 个核心工具。

    常驻工具（lazy=False，始终注入上下文）：
      read_file / write_file / edit_file / glob / grep / bash / todo_write
    延迟激活工具（lazy=True，命中关键词时才注入）：
      web_fetch / web_search / task / memory_save / memory_recall / list_memory
      rag_index / rag_search / rag_list（知识库检索）
    """
    reg = ToolRegistry()
    for tool in [
        # 文件
        ReadFileTool(), WriteFileTool(), EditFileTool(),
        # 搜索
        GlobTool(), GrepTool(),
        # Shell
        BashTool(),
        # Web（延迟）
        WebFetchTool(), WebSearchTool(),
        # 元工具
        TodoWriteTool(), TaskTool(), MemorySaveTool(), MemoryRecallTool(), ListMemoryTool(),
        # RAG 知识库（延迟）
        RagIndexTool(), RagSearchTool(), RagListTool(),
    ]:
        reg.register(tool)
    return reg
