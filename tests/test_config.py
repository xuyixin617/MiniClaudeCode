"""config.py 单元测试：默认值、环境变量覆盖、api_key 回退、目录创建。"""
from __future__ import annotations

from miniclaudecode.config import Config


def test_defaults(monkeypatch):
    # 隔离环境变量，避免外部环境干扰断言
    for name in ("MINICLAUDE_PROVIDER", "MINICLAUDE_MODEL", "MINICLAUDE_PERMISSION_MODE"):
        monkeypatch.delenv(name, raising=False)
    c = Config(api_key="k")
    assert c.provider == "openai"
    assert c.permission_mode == "default"
    assert c.model == "gpt-4o-mini"


def test_env_override(monkeypatch):
    monkeypatch.setenv("MINICLAUDE_MODEL", "glm-4-flash")
    monkeypatch.setenv("MINICLAUDE_CONTEXT_WINDOW", "9999")
    c = Config()
    assert c.model == "glm-4-flash"
    assert c.context_window == 9999


def test_api_key_empty_when_no_env(monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MINICLAUDE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert Config().api_key == ""


def test_api_key_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MINICLAUDE_API_KEY", raising=False)  # 隔离 .env 注入的密钥
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert Config().api_key == "sk-openai"


def test_is_anthropic(monkeypatch):
    monkeypatch.delenv("MINICLAUDE_PROVIDER", raising=False)  # 隔离 .env 注入的 provider
    assert Config(provider="anthropic").is_anthropic is True
    assert Config(provider="openai").is_anthropic is False


def test_ensure_dirs(tmp_path):
    c = Config(data_dir=str(tmp_path / "d"))
    c.ensure_dirs()
    assert (tmp_path / "d").exists()
    assert (tmp_path / "d" / "permissions").exists()
