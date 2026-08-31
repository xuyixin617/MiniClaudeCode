"""配置加载模块。

配置来源优先级（高 -> 低）：
1. 命令行参数（在 main.py 中覆盖）
2. 环境变量 / .env 文件
3. 代码内默认值

支持的常见 OpenAI 兼容后端（base_url 指向对应平台）：
- 智谱 GLM:   https://open.bigmodel.cn/api/paas/v4
- DeepSeek:   https://api.deepseek.com/v1
- OpenAI:     https://api.openai.com/v1
- Anthropic:  https://api.anthropic.com  (provider=anthropic)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv()  # 自动读取工作目录下的 .env
except Exception:  # dotenv 缺失时静默降级
    pass


@dataclass
class Config:
    """运行期全局配置。"""

    # ---- 模型后端 ----
    provider: str = "openai"                 # "openai" | "anthropic"
    model: str = "gpt-4o-mini"               # 默认模型
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    temperature: float = 0.2
    max_tokens: int = 8192                   # 单次回复最大 token

    # ---- 上下文窗口 ----
    context_window: int = 128_000            # 模型上下文窗口（token）
    # 压缩触发阈值
    compact_soft_ratio: float = 0.70         # >70% 收紧工具返回体积
    compact_hard_ratio: float = 0.85         # >85% 触发 auto-compact 全量摘要

    # ---- 权限 ----
    permission_mode: str = "default"         # default/plan/acceptEdits/bypassPermissions/dontAsk
    permission_dir: str = ""                 # 权限规则/白名单持久化目录

    # ---- 工作目录 ----
    cwd: str = field(default_factory=lambda: os.getcwd())

    # ---- 会话与记忆 ----
    data_dir: str = ""                       # 会话/记忆持久化根目录

    # ---- 行为开关 ----
    enable_stream: bool = True
    max_tool_rounds: int = 64                # 单轮对话内最大工具往返次数（防死循环）

    def __post_init__(self) -> None:
        # 应用环境变量覆盖（仅当字段未显式设置时）
        env_map = {
            "MINICLAUDE_PROVIDER": "provider",
            "MINICLAUDE_MODEL": "model",
            "MINICLAUDE_BASE_URL": "base_url",
            "MINICLAUDE_API_KEY": "api_key",
            "MINICLAUDE_PERMISSION_MODE": "permission_mode",
            "MINICLAUDE_CONTEXT_WINDOW": "context_window",
        }
        for env, attr in env_map.items():
            if os.environ.get(env):
                if attr == "context_window":
                    setattr(self, attr, int(os.environ[env]))
                else:
                    setattr(self, attr, os.environ[env])

        # 兼容常见环境变量别名
        if not self.api_key:
            self.api_key = os.environ.get("OPENAI_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        if self.provider == "anthropic" and not self.api_key:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        # 数据目录默认放在用户主目录，避免污染仓库
        if not self.data_dir:
            self.data_dir = str(Path.home() / ".miniclaudecode")
        if not self.permission_dir:
            self.permission_dir = str(Path(self.data_dir) / "permissions")

    @property
    def is_anthropic(self) -> bool:
        return self.provider == "anthropic"

    def ensure_dirs(self) -> None:
        """确保数据目录存在。"""
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.permission_dir).mkdir(parents=True, exist_ok=True)
