"""工具基类与结果类型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..context import AgentContext


@dataclass
class ToolResult:
    """工具执行结果。"""

    output: str
    is_error: bool = False
    meta: dict = field(default_factory=dict)  # 附带元信息（如 mtime、行数等）

    @classmethod
    def ok(cls, output: str, **meta) -> "ToolResult":
        return cls(output=output, is_error=False, meta=meta)

    @classmethod
    def error(cls, output: str, **meta) -> "ToolResult":
        return cls(output=output, is_error=True, meta=meta)


class Tool:
    """所有工具的抽象基类。

    子类需实现 `run`；`lazy` 为 True 表示延迟激活（默认不进入 API 上下文），
    `keywords` 用于在用户输入命中时自动激活该工具。
    """

    name: str = ""
    description: str = ""
    # JSON Schema 的对象部分（properties / required），不含 type 外壳
    parameters: dict = {"type": "object", "properties": {}, "required": []}
    lazy: bool = False
    keywords: list[str] = []

    def schema(self) -> dict:
        """返回 OpenAI function 风格的工具描述，供后端注入上下文。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def run(self, args: dict, ctx: "AgentContext") -> ToolResult:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<Tool {self.name}>"
