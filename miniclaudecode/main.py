"""命令行入口 —— 解析参数、构建配置、启动 CLI。"""
from __future__ import annotations

import argparse
import asyncio
import sys

from .config import Config
from .cli.app import MiniClaudeApp
from .cli.session import SessionStore


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="miniclaudecode", description="MiniClaudeCode 本地 Coding Agent CLI")
    p.add_argument("--model", help="模型名（如 gpt-4o-mini / glm-4 / deepseek-chat）")
    p.add_argument("--provider", choices=["openai", "anthropic"], help="后端协议，默认 openai（OpenAI 兼容）")
    p.add_argument("--base-url", help="API Base URL")
    p.add_argument("--api-key", help="API Key（也可用环境变量 MINICLAUDE_API_KEY）")
    p.add_argument("--mode", help="权限模式：default/plan/acceptEdits/bypassPermissions/dontAsk")
    p.add_argument("--cwd", help="工作目录，默认当前目录")
    p.add_argument("--context-window", type=int, help="上下文窗口 token 数")
    p.add_argument("--no-stream", action="store_true", help="关闭流式输出")
    p.add_argument("--resume", metavar="SESSION_ID", help="恢复指定会话")
    p.add_argument("--list-sessions", action="store_true", help="列出历史会话后退出")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config = Config()
    if args.model:
        config.model = args.model
    if args.provider:
        config.provider = args.provider
    if args.base_url:
        config.base_url = args.base_url
    if args.api_key:
        config.api_key = args.api_key
    if args.mode:
        config.permission_mode = args.mode
    if args.cwd:
        config.cwd = args.cwd
    if args.context_window:
        config.context_window = args.context_window
    if args.no_stream:
        config.enable_stream = False

    if args.list_sessions:
        store = SessionStore(config.data_dir)
        for s in store.list_sessions():
            print(f"{s['session_id']}  {s['title'][:40]}  {s['model']}")
        return 0

    if not config.api_key:
        print("未配置 API Key。请设置环境变量 MINICLAUDE_API_KEY（或 OPENAI_API_KEY / ANTHROPIC_API_KEY），"
              "或通过 --api-key 传入。", file=sys.stderr)
        return 1

    app = MiniClaudeApp(config)

    if args.resume:
        record = app.session_store.load(args.resume)
        if record:
            app.loop.restore_history(record.get("history", []))
            app.session_id = record.get("session_id", args.resume)
            app.title = record.get("title", "")
            if record.get("model"):
                app.config.model = record["model"]
            if record.get("mode"):
                app.permissions.set_mode(record["mode"])
            print(f"已恢复会话 {app.session_id} — {app.title}")
        else:
            print(f"会话 {args.resume} 不存在", file=sys.stderr)

    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
