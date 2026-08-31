"""权限体系测试：模式归一化、规则、危险命令、四层判定、白名单持久化。"""
from __future__ import annotations

import asyncio

from miniclaudecode.permission.dangerous import detect_danger
from miniclaudecode.permission.manager import PermissionManager
from miniclaudecode.permission.modes import MODES, resolve_mode
from miniclaudecode.permission.rules import Rule, RuleSet


def _run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ #
# 模式
# ------------------------------------------------------------------ #
def test_resolve_mode():
    assert resolve_mode(None) == "default"
    assert resolve_mode("PLAN") == "plan"          # 大小写不敏感
    assert resolve_mode("acceptEdits") == "acceptEdits"
    assert resolve_mode("bogus") == "default"      # 非法回退默认
    assert set(MODES) == {"default", "plan", "acceptEdits", "bypassPermissions", "dontAsk"}


# ------------------------------------------------------------------ #
# 规则
# ------------------------------------------------------------------ #
def test_ruleset_deny_wins(tmp_path):
    rs = RuleSet(str(tmp_path / "rules.json"))
    rs.add(Rule(type="allow", tool="bash", pattern="echo"))
    rs.add(Rule(type="deny", tool="bash", pattern=r"rm\s+-rf"))
    assert rs.evaluate("bash", "rm -rf /")[0] == "deny"
    assert rs.evaluate("bash", "echo hi")[0] == "allow"
    assert rs.evaluate("grep", "echo hi")[0] is None  # 工具不匹配


def test_ruleset_save_load(tmp_path):
    p = str(tmp_path / "r.json")
    rs = RuleSet(p)
    rs.add_allow("bash", "echo")
    rs.save()
    rs2 = RuleSet(p)
    assert rs2.evaluate("bash", "echo hi")[0] == "allow"


# ------------------------------------------------------------------ #
# 危险命令
# ------------------------------------------------------------------ #
def test_detect_danger():
    ids = {h.id for h in detect_danger("rm -rf / && sudo poweroff")}
    assert "rm_recursive" in ids
    assert "sudo" in ids
    assert "shutdown_reboot" in ids


def test_detect_danger_clean():
    assert detect_danger("echo hello") == []


# ------------------------------------------------------------------ #
# 四层判定（各模式）
# ------------------------------------------------------------------ #
def test_bypass_mode(config):
    pm = PermissionManager(config)
    pm.set_mode("bypassPermissions")
    assert _run(pm.check("bash", {"command": "rm -rf /"})).status == "allow"


def test_plan_mode(config):
    pm = PermissionManager(config)
    pm.set_mode("plan")
    assert _run(pm.check("read_file", {"path": "a"})).status == "allow"
    assert _run(pm.check("write_file", {"path": "a", "content": "x"})).status == "deny"
    assert _run(pm.check("bash", {"command": "echo hi"})).status == "deny"


def test_accept_edits_mode(config):
    pm = PermissionManager(config)
    pm.set_mode("acceptEdits")
    assert _run(pm.check("write_file", {"path": "a", "content": "x"})).status == "allow"
    # 命令类仍需确认，无回调 -> 拒绝
    assert _run(pm.check("bash", {"command": "echo hi"})).status == "deny"


def test_accept_edits_rejects_path_escape(config):
    pm = PermissionManager(config)
    pm.set_mode("acceptEdits")
    # 路径越界 => 危险，走确认 => 无回调拒绝
    assert _run(pm.check("write_file", {"path": "../outside.py", "content": "x"})).status == "deny"


def test_dont_ask_mode(config):
    pm = PermissionManager(config)
    pm.set_mode("dontAsk")
    assert _run(pm.check("read_file", {"path": "a"})).status == "allow"     # 只读仍放行
    assert _run(pm.check("write_file", {"path": "a", "content": "x"})).status == "deny"
    assert _run(pm.check("bash", {"command": "echo hi"})).status == "deny"


def test_default_no_callback_denies_write(config):
    pm = PermissionManager(config)  # default 模式
    assert _run(pm.check("read_file", {"path": "a"})).status == "allow"
    assert _run(pm.check("write_file", {"path": "a", "content": "x"})).status == "deny"
    assert _run(pm.check("bash", {"command": "echo hi"})).status == "deny"


def test_ask_callback_allow(config):
    pm = PermissionManager(config)

    async def cb(tool, args, reason):
        return "allow"

    pm.set_ask_callback(cb)
    assert _run(pm.check("write_file", {"path": "a", "content": "x"})).status == "allow"


def test_ask_callback_deny(config):
    pm = PermissionManager(config)

    async def cb(tool, args, reason):
        return "deny"

    pm.set_ask_callback(cb)
    assert _run(pm.check("bash", {"command": "echo hi"})).status == "deny"


# ------------------------------------------------------------------ #
# 白名单：allow_always 沉淀为持久化规则
# ------------------------------------------------------------------ #
def test_whitelist_persists(config):
    pm = PermissionManager(config)

    async def cb(tool, args, reason):
        return "allow_always"

    pm.set_ask_callback(cb)
    d = _run(pm.check("bash", {"command": "echo persist_test"}))
    assert d.status == "allow"
    assert d.via == "whitelist"

    # 新管理器加载同一白名单，无回调也应命中
    pm2 = PermissionManager(config)
    d2 = _run(pm2.check("bash", {"command": "echo persist_test"}))
    assert d2.status == "allow"
    assert d2.via == "whitelist"
