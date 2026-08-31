"""共享 AgentContext —— 贯穿整个 Agent 生命周期的依赖容器。

为了避免各模块（tools / permission / context_compress / cli）之间出现循环导入，
统一把运行期共享对象挂到 AgentContext 上，通过 ctx 传递。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # 仅类型提示，运行时避免循环导入
    from .config import Config
    from .permission.manager import PermissionManager
    from .tools.registry import ToolRegistry
    from .context_compress.memory import MemoryStore


@dataclass
class AgentContext:
    """运行期上下文容器。"""

    config: "Config"
    # 各子系统延迟注入，避免构造顺序耦合
    tools: Any = None                       # ToolRegistry
    permissions: Any = None                 # PermissionManager
    memory: Any = None                      # MemoryStore
    rag: Any = None                         # RagEngine（知识库检索，可选）

    # 会话状态
    conversation_id: Optional[str] = None

    # 运行时统计（用于上下文利用率判断）
    token_used: int = 0
    tool_call_count: int = 0
    aborted: bool = False                   # 用户 Ctrl+C 或 /stop 设置

    # 附加上下文注入（多层级 system prompt 之外的可选扩展）
    extra_context: dict = field(default_factory=dict)

    def set(self, name: str, value: Any) -> None:
        setattr(self, name, value)
