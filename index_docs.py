"""一键把文档目录索引进本地知识库（与 MiniClaudeCode 交互式程序共用同一份库）。

用法：
    python index_docs.py                 # 索引本目录下的 docs/ 目录（增量追加）
    python index_docs.py --clear         # 先清空知识库，再索引 docs/
    python index_docs.py <目录> [--clear]  # 索引指定目录

说明：
- 数据持久化在 ~/.miniclaudecode/rag.db，索引一次、跨会话可用。
- 有 MINICLAUDE_API_KEY 时自动走 GLM 语义向量；否则退回词元嵌入。
- 切换嵌入方式（词元 ↔ GLM）后建议加 --clear 重建，避免新旧向量混用导致评分失真。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    # 显式加载项目根目录的 .env，保证从任意工作目录运行都能读到密钥
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

from miniclaudecode.config import Config
from miniclaudecode.rag import RagEngine
from miniclaudecode.rag.glm_embedding import build_embedding_fn

# 跳过的二进制/大型后缀（与 rag_tools.py 保持一致）
_SKIP_EXT = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".exe", ".dll", ".so",
             ".dylib", ".pdf", ".woff", ".woff2", ".ttf", ".ico", ".mp3", ".mp4",
             ".bin", ".jar", ".class", ".o", ".a", ".obj", ".db", ".sqlite", ".lock"}
_MAX_FILE_BYTES = 1_000_000   # 单文件超过 1MB 跳过，控制入库体积


def collect_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() in _SKIP_EXT:
            continue
        try:
            if p.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把文档目录索引进知识库")
    parser.add_argument("dir", nargs="?", default="docs", help="要索引的目录（默认 docs）")
    parser.add_argument("--clear", action="store_true", help="索引前清空知识库")
    args = parser.parse_args(argv)

    root = Path(args.dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parent / root
    if not root.is_dir():
        print(f"目录不存在: {root}", file=sys.stderr)
        return 2

    files = collect_files(root)
    if not files:
        print(f"目录下没有可索引的文本文件: {root}")
        return 0

    config = Config()  # 已通过 load_dotenv 读取 .env
    embed_fn = build_embedding_fn(config.base_url, config.api_key)
    mode = "GLM 语义向量" if config.api_key else "词元嵌入（未配置 API Key）"

    db_path = Path(config.data_dir) / "rag.db"
    rag = RagEngine(str(db_path), embedding_fn=embed_fn)
    try:
        if args.clear:
            rag.clear()
            print("已清空知识库")
        ok = 0
        for f in files:
            try:
                rag.index_file(str(f))
                ok += 1
                print(f"  已索引: {f.relative_to(root)}")
            except Exception as exc:  # noqa: BLE001
                print(f"  跳过 {f}: {exc}", file=sys.stderr)
        print(f"\n完成：索引 {ok}/{len(files)} 个文件 · 嵌入方式 {mode} · 知识库 {db_path}")
    finally:
        rag.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
