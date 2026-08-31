"""提示词管理测试：@include 展开、循环检测、200 行上限、层级顺序、多层级 system prompt。"""
from __future__ import annotations

from miniclaudecode.prompt_loader.loader import load_claude_md
from miniclaudecode.prompt_loader.system_prompt import build_system_prompt


def test_include(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("主规则\n@include ./extra.md\n", encoding="utf-8")
    (tmp_path / "extra.md").write_text("额外规则\n", encoding="utf-8")
    c = load_claude_md(str(tmp_path), home_dir=str(tmp_path / "no_home"))
    assert "主规则" in c
    assert "额外规则" in c


def test_include_cycle_detected(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("@include ./a.md\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("@include ./CLAUDE.md\n内容A\n", encoding="utf-8")
    c = load_claude_md(str(tmp_path), home_dir=str(tmp_path / "no_home"))
    assert "循环引用" in c
    assert "内容A" in c


def test_include_missing_graceful(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("@include ./not_exist.md\n主规则\n", encoding="utf-8")
    c = load_claude_md(str(tmp_path), home_dir=str(tmp_path / "no_home"))
    assert "未找到" in c
    assert "主规则" in c


def test_200_line_cap(tmp_path):
    big = "\n".join(f"规则{i}" for i in range(500))
    (tmp_path / "CLAUDE.md").write_text(big, encoding="utf-8")
    c = load_claude_md(str(tmp_path), home_dir=str(tmp_path / "no_home"))
    assert "截断" in c
    assert "规则0" in c
    assert "规则499" not in c


def test_hierarchical_closest_first(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("ROOT_RULE\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "CLAUDE.md").write_text("SUB_RULE\n", encoding="utf-8")
    c = load_claude_md(str(sub), home_dir=str(tmp_path / "no_home"))
    assert "SUB_RULE" in c
    assert "ROOT_RULE" in c
    assert c.index("SUB_RULE") < c.index("ROOT_RULE")  # 就近优先


def test_build_system_prompt_layers(ctx):
    sp = build_system_prompt(ctx, claude_content="项目规则X", memory_content="记忆Y")
    assert "项目规则X" in sp
    assert "记忆Y" in sp
    assert "运行环境" in sp
    assert "工作纪律" in sp  # 基础层存在


def test_build_system_prompt_empty_optional(ctx):
    sp = build_system_prompt(ctx, claude_content="", memory_content="")
    assert "运行环境" in sp


def test_include_relative_to_claude_file_not_cwd(tmp_path):
    """父目录 CLAUDE.md 的 @include 应相对「该文件所在目录」解析，而非启动目录。"""
    (tmp_path / "CLAUDE.md").write_text("@include ./extra.md\n", encoding="utf-8")
    (tmp_path / "extra.md").write_text("父目录规则\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "CLAUDE.md").write_text("子目录规则\n", encoding="utf-8")

    # 从子目录启动，但父目录 CLAUDE.md 里的 ./extra.md 应指向父目录
    c = load_claude_md(str(sub), home_dir=str(tmp_path / "no_home"))
    assert "父目录规则" in c  # 修复前：会去找 sub/extra.md → 未找到


def test_include_diamond_not_misreported_as_cycle(tmp_path):
    """两个文件都 include 同一公共文件，不应被误报为循环引用。"""
    (tmp_path / "CLAUDE.md").write_text("@include ./a.md\n@include ./b.md\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("@include ./common.md\nA规则\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("@include ./common.md\nB规则\n", encoding="utf-8")
    (tmp_path / "common.md").write_text("公共规则\n", encoding="utf-8")

    c = load_claude_md(str(tmp_path), home_dir=str(tmp_path / "no_home"))
    assert "公共规则" in c
    assert "循环引用" not in c  # 修复前：common.md 第二次被 include 时报循环


def test_include_depth_limit_marks_unexpanded(tmp_path):
    """include 嵌套超过上限时，残留的 @include 行应标占位，且更深层不再展开。"""
    # 链：CLAUDE.md -> c0 -> c1 -> ... -> c10（c10 再 include c11，触发超限）
    for i in range(11):
        (tmp_path / f"c{i}.md").write_text(f"@include ./c{i + 1}.md\n", encoding="utf-8")
    (tmp_path / "c11.md").write_text("末尾\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("@include ./c0.md\n", encoding="utf-8")

    c = load_claude_md(str(tmp_path), home_dir=str(tmp_path / "no_home"))
    assert "嵌套过深" in c      # 修复前：超限静默返回，无任何提示
    assert "末尾" not in c      # 超限后更深层的内容不该被展开
