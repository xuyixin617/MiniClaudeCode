# MiniClaudeCode 项目约定

本地 Coding Agent CLI（面向 Harness Engineering），Anthropic/OpenAI 兼容 API + 自定义 Agent Runtime + AsyncIO + Rich。

## 运行环境

- Python 3.11+（当前 3.11.9）
- 入口：`python -m miniclaudecode`（不依赖 editable install）
- 运行时依赖：rich / httpx / python-dotenv（见 `requirements.txt`）
- 开发依赖：pytest（见 `requirements-dev.txt`）

## 必须遵守的流程

- **改完代码必须跑 `python -m pytest`，全绿才算完成**（当前 85 个测试，约 2 秒）。
- **修改文件前先 read_file**（read-before-edit）；用 edit_file 做精确替换，不要整文件重写。
- 先搜索定位（glob/grep）再阅读再改，不要凭猜测动代码。

## 代码风格

- **注释、docstring、提交信息一律用中文**。
- 用类型注解（文件头 `from __future__ import annotations`）；数据结构优先 `@dataclass`。
- 异步代码用 `async/await`；工具的执行入口是 `async def run(args, ctx)`。

## 依赖原则

- **能用标准库就不用第三方包**。典型例子：RAG 存储层用 `sqlite3` 而非 Chroma/FAISS。
- 新增运行时依赖前先确认无法用标准库替代，并同步更新 `requirements.txt`。
- 注意 `requirements*.txt` 只写 ASCII 注释（中文注释会在中文 Windows 上触发 pip 的 GBK 解码崩溃）。

## 架构原则（最小侵入）

- `AgentContext` 是唯一共享容器，各模块经它互相访问，**避免循环导入**。
- 新增能力（如 RAG）不要改动 `loop / backend / permission / context_compress` 的既有逻辑；
  优先通过「延迟激活工具」+ `ctx` 上的可选字段接入。
- 工具基类契约：`Tool.name / description / parameters / lazy / keywords / async run(args, ctx) -> ToolResult`。

## 权限与安全

- 不要绕过四层权限管控；工具行为要「安全可预期」。
- 危险命令、写路径越界必须被权限系统拦截，测试里要有对应断言。

## 路径注意

- 项目在 `D:\MiniClaudeCode`（无中文路径）。中文用户名/路径会导致 editable install 的 `.pth` 崩溃，
  所以运行、打包、安装都要用无中文路径。
- 数据目录在 `~/.miniclaudecode/`（会话、记忆、权限规则、RAG 知识库 `rag.db`），与代码位置无关。
