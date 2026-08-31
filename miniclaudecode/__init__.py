"""MiniClaudeCode —— 面向 Harness Engineering 的轻量级本地 Coding Agent CLI。

设计目标聚焦三大核心问题：
1. 工具可控调用 —— 13 个核心工具 + 延迟激活 + read-before-edit 保护；
2. 上下文可持续 —— 4 级渐进式压缩流水线 + 跨会话记忆；
3. 权限安全可预期 —— 四层权限管控（模式 / 规则 / 危险命令 / 交互确认）。
"""

__version__ = "0.1.0"
