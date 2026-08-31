"""pytest 全局夹具。

把项目根目录加入 sys.path，保证 `import miniclaudecode` 在任意工作目录下都可用；
并提供 `config` / `ctx` 两个常用夹具（基于 tmp_path 的隔离环境）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保项目根目录可被导入（conftest 先于测试模块加载）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from miniclaudecode.config import Config
from miniclaudecode.context import AgentContext


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """一个隔离的 Config：cwd 指向 tmp_path，context_window 设为 10000 便于利用率断言。"""
    return Config(
        cwd=str(tmp_path),
        data_dir=str(tmp_path / "data"),
        api_key="test-key",
        context_window=10000,
    )


@pytest.fixture
def ctx(config: Config) -> AgentContext:
    """基于 config 夹具的共享上下文容器。"""
    return AgentContext(config)
