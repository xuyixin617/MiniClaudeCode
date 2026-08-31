"""权限管理器 —— 四层管控编排。

四层：
1. 模式层（mode）：bypassPermissions 直接放行；plan 只读；dontAsk 不询问直接拒；等等。
2. 规则层（rule）：声明式 allow/deny，deny 优先。
3. 危险层（danger）：18+ 类高危命令正则检测，命中强制进入确认流程。
4. 交互层（ask）：用户确认 + 白名单（"总是允许" 会沉淀为持久化 allow 规则）。

判定顺序：bypass -> deny 规则 -> allow 规则 -> 危险检测 -> 模式/类别默认 -> 交互确认。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from .dangerous import DangerousPattern, describe_danger, detect_danger
from .modes import resolve_mode
from .rules import RuleSet

if TYPE_CHECKING:
    from ..config import Config

# 工具类别
READ_ONLY = {"read_file", "glob", "grep", "web_fetch", "web_search", "memory_recall", "list_memory", "todo_write"}
WRITE = {"write_file", "edit_file", "memory_save"}
SHELL = {"bash"}
TASK = {"task"}

# 交互确认回调：返回 "allow" | "deny" | "allow_always"
AskCallback = Callable[[str, dict, str], Awaitable[str]]


@dataclass
class PermissionDecision:
    status: str           # "allow" | "deny"
    reason: str
    via: str = ""         # 来源：bypass/rule/danger/mode/ask/whitelist


class PermissionManager:
    def __init__(self, config: "Config") -> None:
        self.config = config
        self.mode = resolve_mode(config.permission_mode)
        rules_path = str(Path(config.permission_dir) / "rules.json")
        whitelist_path = str(Path(config.permission_dir) / "whitelist.json")
        self.rules = RuleSet(rules_path)
        self.whitelist = RuleSet(whitelist_path)
        self.ask_callback: Optional[AskCallback] = None

    # ------------------------------------------------------------------ #
    def set_mode(self, mode: str) -> None:
        self.mode = resolve_mode(mode)

    def set_ask_callback(self, cb: AskCallback) -> None:
        self.ask_callback = cb

    # ------------------------------------------------------------------ #
    @staticmethod
    def _subject(tool_name: str, args: dict) -> str:
        if tool_name == "bash":
            return args.get("command", "")
        return json.dumps(args, ensure_ascii=False)

    def _path_danger(self, args: dict) -> Optional[str]:
        """写文件工具的路径越界检测：路径逃出工作目录视为高风险。"""
        path = args.get("path", "")
        if not path:
            return None
        try:
            cwd = Path(self.config.cwd).resolve()
            target = Path(path)
            if not target.is_absolute():
                target = cwd / target
            target = target.resolve()
            if not str(target).startswith(str(cwd)):
                return f"路径越界写入：{target} 不在工作目录 {cwd} 内"
        except Exception:
            return None
        return None

    # ------------------------------------------------------------------ #
    async def check(self, tool_name: str, args: dict) -> PermissionDecision:
        subject = self._subject(tool_name, args)

        # 1. 绕过模式
        if self.mode == "bypassPermissions":
            return PermissionDecision("allow", "bypassPermissions 模式", "bypass")

        # 2. 规则层（deny 优先，其次 allow，最后白名单）
        decision, rule = self.rules.evaluate(tool_name, subject)
        if decision == "deny":
            return PermissionDecision("deny", rule.description or f"命中 deny 规则", "rule")
        if decision == "allow":
            return PermissionDecision("allow", rule.description or "命中 allow 规则", "rule")
        w_decision, w_rule = self.whitelist.evaluate(tool_name, subject)
        if w_decision == "allow":
            return PermissionDecision("allow", w_rule.description or "命中白名单", "whitelist")

        # 3. 危险层
        danger_reason = ""
        if tool_name == "bash":
            hits: list[DangerousPattern] = detect_danger(subject)
            if hits:
                danger_reason = "危险命令：" + describe_danger(hits)
        elif tool_name in WRITE:
            path_danger = self._path_danger(args)
            if path_danger:
                danger_reason = path_danger

        # 4. 模式/类别默认
        if tool_name in READ_ONLY:
            return PermissionDecision("allow", "只读工具默认放行", "mode")

        # plan 模式：只读之外一律拒绝
        if self.mode == "plan":
            return PermissionDecision("deny", "plan 模式只读，拒绝副作用操作", "mode")

        # acceptEdits：文件编辑自动放行（read-before-edit 仍生效）
        if self.mode == "acceptEdits" and tool_name in WRITE and not danger_reason:
            return PermissionDecision("allow", "acceptEdits 模式自动接受编辑", "mode")

        # 危险操作或写/命令操作，进入确认流程
        reason = danger_reason or f"{tool_name} 属于写/命令类操作"
        if self.mode == "dontAsk":
            return PermissionDecision("deny", f"dontAsk 模式拒绝：{reason}", "mode")

        return await self._ask(tool_name, args, reason, subject)

    # ------------------------------------------------------------------ #
    async def _ask(self, tool_name: str, args: dict, reason: str, subject: str) -> PermissionDecision:
        """交互确认 + 白名单沉淀。"""
        if self.ask_callback is None:
            # 非交互环境（无 CLI 回调）：默认拒绝，保证安全可预期
            return PermissionDecision("deny", f"无交互确认环境，自动拒绝：{reason}", "ask")

        answer = await self.ask_callback(tool_name, args, reason)
        if answer == "allow_always":
            # 白名单：沉淀为持久化 allow 规则
            self.whitelist.add_allow(tool_name, re.escape(subject), f"白名单: {reason}")
            self.whitelist.save()
            return PermissionDecision("allow", f"已加入白名单：{reason}", "whitelist")
        if answer == "allow":
            return PermissionDecision("allow", "用户确认允许", "ask")
        return PermissionDecision("deny", "用户拒绝", "ask")
