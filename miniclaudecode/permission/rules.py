"""声明式 allow / deny 规则。

规则格式（JSON 文件，可持久化）：
    {
      "type": "allow" | "deny",
      "tool": "bash" 或 "*" 表示全部,
      "pattern": "正则表达式",   // 匹配命令串（仅 bash）/ 参数 JSON / 路径
      "description": "说明"
    }

优先级：deny > allow；更精确的 tool 匹配优先于通配符。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Rule:
    type: str                       # "allow" | "deny"
    tool: str = "*"                 # 工具名或 "*"
    pattern: str = ""               # 正则
    description: str = ""
    _rx: Optional[re.Pattern] = field(default=None, repr=False, init=False)

    def matches(self, tool_name: str, subject: str) -> bool:
        """判断规则是否命中：tool 匹配 + pattern 命中 subject。"""
        if self.tool != "*" and self.tool != tool_name:
            return False
        if not self.pattern:
            return False
        if self._rx is None:
            try:
                self._rx = re.compile(self.pattern, re.IGNORECASE)
            except re.error:
                return False
        return bool(self._rx.search(subject))

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        return cls(type=d.get("type", "allow"), tool=d.get("tool", "*"),
                   pattern=d.get("pattern", ""), description=d.get("description", ""))

    def to_dict(self) -> dict:
        return {"type": self.type, "tool": self.tool, "pattern": self.pattern,
                "description": self.description}


class RuleSet:
    """规则集合，支持文件加载/保存。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path
        self.rules: list[Rule] = []
        if path and Path(path).exists():
            self.load(path)

    def load(self, path: str) -> None:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.rules = [Rule.from_dict(d) for d in data.get("rules", [])]
        except Exception:
            self.rules = []

    def save(self) -> None:
        if not self.path:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.path).write_text(
            json.dumps({"rules": [r.to_dict() for r in self.rules]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, rule: Rule) -> None:
        self.rules.append(rule)

    def add_allow(self, tool: str, pattern: str, description: str = "") -> None:
        self.add(Rule(type="allow", tool=tool, pattern=pattern, description=description))

    def evaluate(self, tool_name: str, subject: str) -> tuple[Optional[str], Optional[Rule]]:
        """返回 (decision, matched_rule)：decision 为 'allow'/'deny'/None。"""
        deny: Optional[Rule] = None
        allow: Optional[Rule] = None
        for r in self.rules:
            if not r.matches(tool_name, subject):
                continue
            if r.type == "deny" and deny is None:
                deny = r
            elif r.type == "allow" and allow is None:
                allow = r
        if deny is not None:
            return "deny", deny
        if allow is not None:
            return "allow", allow
        return None, None
