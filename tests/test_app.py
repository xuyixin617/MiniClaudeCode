"""应用装配测试：验证全部子系统能正确装配，不发网络请求。"""
from __future__ import annotations

import asyncio


def test_app_assembly(config):
    from miniclaudecode.cli.app import MiniClaudeApp

    app = MiniClaudeApp(config)
    try:
        assert len(app.tools.names()) == 16
        assert app.loop is not None
        assert app.permissions is not None
        assert app.memory is not None
        # ctx 依赖已回填
        assert app.ctx.tools is app.tools
        assert app.ctx.permissions is app.permissions
        assert app.ctx.backend is app.backend
    finally:
        try:
            asyncio.run(app.backend.close())
        except Exception:
            pass
