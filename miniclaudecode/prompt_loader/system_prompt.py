"""多层级 system prompt 注入架构。

层级（自底向上拼接，低层级更通用、高层级更贴近当前任务）：
1. 基础层 BASE_PROMPT：角色、工具使用纪律、安全底线；
2. 项目层 CLAUDE.md：项目/用户自定义规则；
3. 记忆层：sideQuery 召回的跨会话记忆；
4. 动态层：权限模式、工作目录、日期等运行期状态。

拼接顺序即优先级语义：越靠后的层级对行为约束越具体、越优先。
"""
from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import AgentContext

BASE_PROMPT = """你是 MiniClaudeCode，一个面向编码场景的本地 Coding Agent。

## 工作纪律
- 修改文件前必须先 read_file（read-before-edit）；用 edit_file 做精确替换，而非重写整个文件。
- 先搜索（glob/grep）定位，再阅读，最后再修改；不要凭猜测改代码。
- 复杂任务先用 todo_write 列出步骤，逐个推进并更新状态。
- 输出简洁、直接：优先给结论与改动，避免冗长铺垫。

## 工具使用
- read_file / write_file / edit_file / glob / grep / bash 为常驻工具。
- 需要联网查资料时使用 web_fetch / web_search；需要子代理时使用 task。
- 重要信息可用 memory_save 写入跨会话记忆，用 memory_recall 召回。

## 安全底线
- 所有写文件与命令执行都会经过权限系统；被拒绝时不要反复重试，而是改用其他方案或向用户说明。
- 不删除、不覆盖工作目录之外的文件；不执行破坏性命令。
"""


def build_system_prompt(
    ctx: "AgentContext",
    claude_content: str = "",
    memory_content: str = "",
) -> str:
    """按多层级架构组装 system prompt。"""
    cfg = ctx.config
    layers: list[str] = [BASE_PROMPT]

    if claude_content:
        layers.append("## 项目指令 (CLAUDE.md)\n" + claude_content)

    if memory_content:
        layers.append("## 跨会话记忆\n" + memory_content)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    dynamic = (
        "## 运行环境\n"
        f"- 当前日期: {now}\n"
        f"- 工作目录: {cfg.cwd}\n"
        f"- 权限模式: {cfg.permission_mode}\n"
        f"- 模型: {cfg.model}\n"
        "- 遵循以上所有规则完成用户请求。"
    )
    layers.append(dynamic)

    return "\n\n".join(layers)
