# MiniClaudeCode

面向 **Harness Engineering** 的轻量级本地 Coding Agent CLI。聚焦三大核心问题：**工具可控调用、上下文可持续、权限安全可预期**。

技术栈：Python · Anthropic / OpenAI 兼容 API · 自定义 Agent Runtime · AsyncIO · Rich CLI。

---

## 特性

### 1. Agent 循环与工具系统
- 对接 Anthropic 原生协议 + OpenAI 兼容协议（GLM / DeepSeek / OpenAI 等），**流式输出**；
- **指数退避 + 抖动重试**处理 API 失败（429/5xx/网络抖动）；
- **16 个编码核心工具**（含 3 个 RAG 知识库工具），采用**延迟激活**策略，减少无关工具占用上下文 token；
- 多工具调用**并发执行**，失败自动**回退串行**；
- **read-before-edit** + **mtime 新鲜度校验**，防止误改文件。

### 2. CLI 交互 & 系统提示词管理
- Rich 终端交互，支持 **slash 命令**；
- **会话持久化与会话恢复**；
- **多层级 system prompt** 注入架构；
- **CLAUDE.md 层级加载**，支持 `@include` 递归解析，上下文开销约束在 **200 行以内**。

### 3. 权限与安全体系（四层管控）
- **5 种权限模式**：`default` / `plan` / `acceptEdits` / `bypassPermissions` / `dontAsk`；
- 声明式 **allow / deny** 规则；
- **18+ 类高危命令**正则检测；
- 用户交互确认 + **白名单机制**（"总是允许"沉淀为持久化规则）。

### 4. 上下文与记忆模块
- **4 级渐进式压缩流水线**：budget truncation → stale snip → microcompact → auto-compact；
- 利用率 **50%~70%** 收紧工具返回体积，**>85%** 触发 auto-compact 全量摘要；
- **sideQuery 语义召回**、异步预取、信息新鲜度提醒；
- **跨会话记忆**：多次会话间保留项目与用户认知，不完全依赖原始对话历史。

---

## 目录结构

```
MiniClaudeCode/
├── README.md
├── requirements.txt
├── .env.example
└── miniclaudecode/
    ├── __init__.py
    ├── __main__.py              # python -m miniclaudecode 入口
    ├── main.py                  # CLI 参数解析与启动
    ├── config.py                # 配置加载（env / .env / 默认值）
    ├── context.py               # 共享 AgentContext 容器
    ├── agent_runtime/           # Agent 运行时
    │   ├── backend.py           #   统一 LLM 后端（Anthropic/OpenAI 兼容 + 流式）
    │   ├── retry.py             #   指数退避 + 抖动重试
    │   ├── messages.py          #   规范化消息模型
    │   └── loop.py              #   Agent 主循环
    ├── tools/                   # 工具系统
    │   ├── base.py              #   工具基类 / ToolResult
    │   ├── registry.py          #   注册表（延迟激活 + 并发回退）
    │   ├── file_tools.py        #   read/write/edit（read-before-edit + mtime）
    │   ├── search_tools.py      #   glob / grep
    │   ├── shell_tools.py       #   bash
    │   ├── web_tools.py         #   web_fetch / web_search
    │   ├── meta_tools.py        #   todo / task / 记忆三件套
    │   ├── rag_tools.py         #   rag_index / rag_search / rag_list（RAG）
    │   └── defaults.py          #   16 工具装配
    ├── permission/              # 权限安全体系
    │   ├── modes.py             #   5 种权限模式
    │   ├── rules.py             #   声明式 allow/deny 规则
    │   ├── dangerous.py         #   18+ 危险命令正则
    │   └── manager.py           #   四层管控编排
    ├── context_compress/        # 上下文压缩 + 记忆
    │   ├── pipeline.py          #   4 级流水线编排
    │   ├── budget.py            #   budget truncation
    │   ├── snip.py              #   stale snip
    │   ├── micro.py             #   microcompact
    │   ├── auto.py              #   auto-compact（LLM 摘要）
    │   ├── memory.py            #   跨会话记忆存储
    │   └── sidequery.py         #   语义召回 / 预取 / 新鲜度
    ├── rag/                     # 存储层 + RAG 检索（新增）
    │   ├── store.py             #   SQLite 存储层（文档/分块）
    │   ├── embedding.py         #   嵌入抽象（词元 / 可注入向量）
    │   └── retriever.py         #   RagEngine（分块 + 检索）
    ├── prompt_loader/           # 系统提示词管理
    │   ├── loader.py            #   CLAUDE.md 层级加载 + @include
    │   └── system_prompt.py     #   多层级 system prompt
    └── cli/                     # CLI 交互
        ├── app.py               #   应用装配 + REPL
        ├── slash.py             #   slash 命令
        ├── session.py           #   会话持久化
        └── display.py           #   Rich 展示辅助
```

---

## 安装

```bash
cd MiniClaudeCode
pip install -r requirements.txt
```

> 提示：若你的用户名/路径包含中文导致某些包安装异常（如 editable install 的 `.pth` 崩溃），
> 请把项目移动到**无中文路径**（如 `D:\MiniClaudeCode`）。本项目直接 `python -m` 运行，不依赖 editable install。

---

## 配置 API Key

三种方式（优先级从高到低）：

**方式一：命令行参数**

```bash
python -m miniclaudecode --api-key sk-xxx --model glm-4-flash --base-url https://open.bigmodel.cn/api/paas/v4
```

**方式二：环境变量 / .env**

```bash
# 复制模板
cp .env.example .env
# 编辑 .env 填入密钥，然后直接启动
python -m miniclaudecode
```

**方式三：系统环境变量**

```bash
export MINICLAUDE_API_KEY=sk-xxx        # Linux/macOS
set MINICLAUDE_API_KEY=sk-xxx           # Windows CMD
```

### 常见后端配置

| 平台 | provider | base_url | 示例模型 |
|---|---|---|---|
| 智谱 GLM | openai | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| DeepSeek | openai | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenAI | openai | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Anthropic | anthropic | `https://api.anthropic.com` | `claude-sonnet-5` |

---

## 启动使用

```bash
python -m miniclaudecode \
  --model glm-4-flash \
  --base-url https://open.bigmodel.cn/api/paas/v4 \
  --mode default
```

启动后进入交互式 REPL，输入自然语言即可。示例：

```
› 帮我在 src 下找所有 TODO 注释
› 读取 main.py 并解释它的作用
› 用 edit_file 把 print 改成 logging
```

### 常用参数

```
--model MODEL        模型名
--provider openai|anthropic
--base-url URL       API 地址
--api-key KEY        密钥
--mode MODE          权限模式
--cwd DIR            工作目录
--context-window N   上下文窗口 token
--no-stream          关闭流式输出
--resume SESSION_ID  恢复会话
--list-sessions      列出历史会话
```

### Slash 命令

| 命令 | 说明 |
|---|---|
| `/help` | 帮助 |
| `/model <name>` | 切换模型 |
| `/mode <name>` | 切换权限模式 |
| `/session list/save/load` | 会话管理 |
| `/tokens` | 查看上下文用量 |
| `/compact` | 手动全量压缩 |
| `/memory` | 查看跨会话记忆 |
| `/tools` | 查看工具激活状态 |
| `/activate /deactivate <tool>` | 激活/停用工具 |
| `/clear` | 清空历史 |
| `/exit` | 退出 |

---

## 权限模式说明

| 模式 | 行为 |
|---|---|
| `default` | 读操作放行；写/命令操作确认；危险命令强制拦截 |
| `plan` | 只读，拒绝一切副作用操作（先规划不落地） |
| `acceptEdits` | 自动接受文件编辑；shell 命令仍需确认 |
| `bypassPermissions` | 完全放开（仅用于受信任沙箱） |
| `dontAsk` | 绝不询问，仅规则显式 allow 才放行 |

规则持久化在 `~/.miniclaudecode/permissions/`（`rules.json` 手动声明、`whitelist.json` 由"总是允许"自动沉淀）。

---

## 上下文压缩流水线

| 级别 | 触发 | 说明 |
|---|---|---|
| budget truncation | 始终兜底 | 按 token 预算 FIFO 丢弃最旧消息 |
| stale snip | 利用率 ≥ 70% | 剪短过期工具返回 |
| microcompact | 利用率 ≥ 70% | 单条消息体积收紧（无 LLM 调用） |
| auto-compact | 利用率 > 85% | LLM 全量摘要压缩 |

工具返回体积在利用率 ≥ 50% 时自动收紧（`ctx.tight_output`）。

---

## RAG 知识库检索（新增）

本地知识库检索，让 Agent 能对项目文档/资料做语义问答，而非只靠原始对话历史：

- **存储层**（`rag/store.py`）：基于标准库 `sqlite3` 持久化文档与分块，零新增依赖。
- **检索引擎**（`rag/retriever.py`）：`RagEngine` 负责「分块 → 嵌入 → 余弦相似度 → top-k」。
- **嵌入可升级**：默认词元嵌入开箱即用；注入 `embedding_fn`（返回向量）即升级为真语义检索。
- **三个延迟工具**：`rag_index`（索引入库）/ `rag_search`（语义检索）/ `rag_list`（列出文档）。

REPL 内示例：

```
› 把 docs/ 目录索引进知识库
› 这个项目的权限是怎么设计的？
```

知识库数据落在 `~/.miniclaudecode/rag.db`。

---

## 关键设计说明

- **工具延迟激活**：`web_fetch` / `web_search` / `task` / 记忆工具默认不注入上下文，命中用户输入关键词（或 `/activate`）时才激活，节省 token。
- **read-before-edit**：`edit_file` 要求先 `read_file`，且校验磁盘 mtime 未变，防止覆盖外部改动。
- **跨会话记忆**：`memory_save` 写入 JSON 持久化；`sideQuery` 每轮开始前用用户输入做召回，把相关记忆注入 system prompt。

---

## 运行测试

```bash
pip install -r requirements-dev.txt
python -m pytest
```

测试覆盖：配置加载、消息模型、重试退避、后端协议翻译（纯函数，不发网络）、
16 工具注册与 read-before-edit/mtime 校验、四层权限判定与白名单持久化、
4 级压缩、跨会话记忆、CLAUDE.md 的 @include/循环检测/200 行上限、会话持久化。

## 二次开发

- 新增工具：继承 `tools/base.py` 的 `Tool`，实现 `run`，在 `tools/defaults.py` 注册即可。
- 新增危险命令：在 `permission/dangerous.py` 的 `DANGEROUS_PATTERNS` 追加条目。
- 替换语义召回：给 `MemoryStore` 传入 `embedding_fn` 即可升级为向量召回。
