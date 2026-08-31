"""5 种权限模式定义与语义。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionMode:
    key: str
    label: str
    description: str


# 5 种权限模式
MODES: dict[str, PermissionMode] = {
    "default": PermissionMode(
        "default", "默认",
        "读操作直接放行；写文件/执行命令等有副作用操作需确认；危险命令强制拦截并确认。",
    ),
    "plan": PermissionMode(
        "plan", "计划模式",
        "只读：仅允许读取/搜索类工具，所有写操作与命令执行一律拒绝，用于先做方案不落地。",
    ),
    "acceptEdits": PermissionMode(
        "acceptEdits", "接受编辑",
        "自动接受文件编辑（read-before-edit 仍生效），但 shell 命令与危险操作仍需确认。",
    ),
    "bypassPermissions": PermissionMode(
        "bypassPermissions", "绕过权限",
        "完全放开，不做任何拦截。仅用于受信任的自动化/沙箱环境，风险自负。",
    ),
    "dontAsk": PermissionMode(
        "dontAsk", "禁止询问",
        "绝不弹窗询问：只有规则显式 allow 的才放行，其余一律拒绝。适合无人值守。",
    ),
}

DEFAULT_MODE = "default"


def resolve_mode(key: str | None) -> str:
    """把用户输入归一化为合法模式 key。"""
    if key is None:
        return DEFAULT_MODE
    if key in MODES:
        return key
    # 兼容大小写
    for k in MODES:
        if k.lower() == key.lower():
            return k
    return DEFAULT_MODE
