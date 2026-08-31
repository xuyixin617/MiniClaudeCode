# MiniClaudeCode 全方位知识指南

> 这份指南面向「想读懂并二次开发本项目」的你。它不重复 README 的安装说明，而是讲清楚：
> **每一块代码为什么存在、它们怎么连起来、一次对话在系统里到底经历了什么、以及我是按什么顺序一步步把它搭起来的。**
>
> 建议配合源码边读边看。阅读路径：先读「全景图」和「核心设计思想」，再按「分模块精讲」逐层下钻，
> 最后看「一步步搭建」复盘整体施工顺序。

---

## 目录

1. [这个项目到底在解决什么](#1-这个项目到底在解决什么)
2. [全景图：架构与数据流](#2-全景图架构与数据流)
3. [核心设计思想](#3-核心设计思想)
4. [地基：Config 与 AgentContext](#4-地基config-与-agentcontext)
5. [数据协议：消息模型](#5-数据协议消息模型)
6. [对外接口：统一 LLM 后端](#6-对外接口统一-llm-后端)
7. [工具系统](#7-工具系统)
8. [权限安全体系](#8-权限安全体系)
9. [上下文压缩与记忆](#9-上下文压缩与记忆)
10. [系统提示词管理](#10-系统提示词管理)
11. [Agent 主循环：把一切串起来](#11-agent-主循环把一切串起来)
12. [CLI 外壳](#12-cli-外壳)
13. [关键机制专题](#13-关键机制专题)
14. [一步步搭建的完整过程](#14-一步步搭建的完整过程)
15. [学习路线与练习建议](#15-学习路线与练习建议)

---

## 1. 这个项目到底在解决什么

一个 Coding Agent（比如 Claude Code）本质上是一个循环：

```
拿到用户输入 → 让 LLM 决定"说话还是调用工具" → 执行工具 → 把结果喂回 LLM → 循环 → 直到 LLM 给出最终答复
```

这个循环看起来简单，但一落地到真实工程就会冒出三大难题，本项目就是围绕这三点设计的：

| 难题 | 表现 | 本项目的解法 |
|---|---|---|
| **工具可控调用** | 工具太多挤爆上下文、LLM 乱调工具、改了不该改的文件 | 延迟激活 + 16 个精挑工具 + read-before-edit + mtime 校验 |
| **上下文可持续** | 长任务越聊越长、token 超限、上下文被历史垃圾淹没 | 4 级渐进式压缩流水线 + 利用率触发 + 跨会话记忆 |
| **权限安全可预期** | 自动执行危险命令、删库跑路、行为不可预测 | 四层管控（模式→规则→危险检测→交互确认） |

**设计哲学**：不追求大而全，而是「轻量 + 可预期」。每个子系统都可独立替换，核心数据流清晰到能用一张图画出来。

---

## 2. 全景图：架构与数据流

### 2.1 模块依赖图

```
                        ┌─────────────────────────────────────┐
                        │        main.py / __main__.py        │   ← 入口：解析参数、装配、启动
                        └──────────────────┬──────────────────┘
                                           │
                        ┌──────────────────▼──────────────────┐
                        │          cli/app.py (MiniClaudeApp)  │   ← 装配器 + REPL 循环
                        │   cli/slash.py · session.py · display│
                        └───────┬──────────────────┬───────────┘
                                │                  │
                 ┌──────────────▼─────┐   ┌────────▼────────────┐
                 │ agent_runtime/loop │   │  context_compress/   │
                 │   (AgentLoop)      │   │   pipeline / auto    │
                 └──────┬─────────────┘   └─────────┬───────────┘
                        │                           │
     ┌──────────────────┼───────────────┐           │
     │                  │               │           │
┌────▼─────┐   ┌────────▼───────┐  ┌────▼──────┐    │
│ tools/   │   │ permission/    │  │ agent_    │    │
│ registry │   │ manager        │  │ runtime/  │    │
│ + 16工具 │   │ + 4层管控      │  │ backend   │    │
└────┬─────┘   └────────┬───────┘  └────┬──────┘    │
     │                  │               │           │
     └──────────┬───────┴───────────────┘           │
                │                                   │
        ┌───────▼──────────────────────────┐        │
        │   context.py (AgentContext)      │◄───────┘
        │   config.py (Config)             │
        │   prompt_loader/ (system prompt) │
        └──────────────────────────────────┘
```

**关键点**：`AgentContext` 是唯一的「共享依赖容器」。`loop.py`（编排核心）依赖 tools、permission、backend、compressor 四样东西，而这四样又都只依赖 `config` / `context` / `messages`。这样就没有循环导入，任何一块都能单独拆出来测试。

### 2.2 一次对话的完整时序

用户输入 `"帮我在 src 下找所有 TODO 注释"` 后，系统经历了：

```
① cli/app._handle_message(text)
     └─► loop.run(text, stream_cb, on_event)

② loop：工具延迟激活        tools.lazy_activate_by_text(text)   # 命中关键词才激活 web/记忆等
③ loop：sideQuery 召回      side_query(ctx, text)               # 从跨会话记忆捞相关上下文
④ loop：组装 system prompt  build_system_prompt(...)            # 基础层+CLAUDE.md+记忆+动态层

⑤ loop：append 用户消息 → history.append(user_message(text))

⑥ 进入工具往返循环（最多 max_tool_rounds 轮）：
   ├─ 软压缩            compressor.maybe_soft(messages)          # 利用率≥70% 剪枝/微压缩
   ├─ 调模型            backend.chat(messages, tools, stream_cb) # 流式把文本增量推到终端
   ├─ 累计 token        ctx.token_used += result.usage.total
   ├─ 若无 tool_calls → 得到最终答复 → break
   └─ 若有 tool_calls：
        ├─ 记录 assistant 消息 + 触发 on_event("tool_call")
        ├─ 权限预检（串行）  permissions.check(name, args)        # 逐工具判定 allow/deny
        ├─ 并发执行工具（失败回退串行） tools.run_tool_calls(...) # 内部 asyncio.gather
        ├─ 把工具结果拼成 tool 消息，触发 on_event("tool_result")
        └─ 硬压缩检查     compressor.maybe_hard(...)              # 利用率>85% LLM 摘要

⑦ cli：流式收尾 / Markdown 渲染 → _autosave() 自动保存会话
```

> 记住这条主链：**`loop.run` 是心脏，`backend.chat` 是神经元，`permissions.check` 是免疫系统，`compressor` 是消化系统。** 后面所有模块精讲都是这条链上的一个环节。

---

## 3. 核心设计思想

在深入代码前，先理解五个贯穿全局的约定，它们决定了代码长什么样：

1. **统一规范化数据协议**：整个系统内部只认 OpenAI 风格的消息和工具 schema（`{"role", "content", "tool_calls", "tool_call_id"}`）。Anthropic 的差异被 `backend.py` 翻译层吸收掉。好处：换模型厂商只改 backend，不动上层。

2. **依赖倒置 + 容器注入**：`loop` 不直接 `import` 具体工具/权限实现，而是接收 `tools` / `permissions` 对象，通过 `AgentContext` 共享运行时状态。好处：可测试、可替换。

3. **渐进式降级（fail-soft）**：每一层都「先做便宜的事，再做贵的事」。压缩先截断后摘要；工具并发失败就回退串行；记忆召回无结果就返回空串不报错。系统永不因一个非关键环节失败而崩。

4. **安全默认拒绝**：权限判定里，凡是拿不准的（危险命令、写操作、非交互环境）默认 `deny`，而不是默认 `allow`。宁可多问一次，不冒删库风险。

5. **token 是稀缺资源**：延迟激活、200 行 CLAUDE.md 上限、工具输出截断、4 级压缩——全在围绕「省 token」做文章。理解这点，很多看似多余的代码就都有了理由。

---

## 4. 地基：Config 与 AgentContext

### 4.1 `config.py` —— 一切可调参数的单一来源

```python
@dataclass
class Config:
    provider: str = "openai"          # 后端协议
    model: str = "gpt-4o-mini"
    base_url: str = "..."
    api_key: str = ""
    context_window: int = 128_000     # 上下文窗口（压缩阈值的分母）
    compact_soft_ratio: float = 0.70  # >70% 触发微压缩
    compact_hard_ratio: float = 0.85  # >85% 触发 auto-compact
    permission_mode: str = "default"
    data_dir: str = ""                # 会话/记忆/权限持久化根目录
    max_tool_rounds: int = 64         # 防死循环
    ...
```

**设计要点**：
- 用 `dataclass` 而不是 dict，能拿到类型提示和字段默认值。
- `__post_init__` 里做**环境变量覆盖**：`MINICLAUDE_MODEL` → `config.model`。这样 CLI 参数、`.env`、默认值三层优先级统一在构造后收敛。
- `ensure_dirs()` 惰性创建数据目录，避免启动时到处 `mkdir`。

**为什么它是第一步**：所有模块都要读配置，先定下「配置长什么样」，后面才有共同的参照系。

### 4.2 `context.py` —— 共享运行时状态容器

```python
@dataclass
class AgentContext:
    config: Config
    tools: Any = None          # ToolRegistry
    permissions: Any = None    # PermissionManager
    memory: Any = None         # MemoryStore
    token_used: int = 0        # 累计 token（压缩利用率的分母）
    tool_call_count: int = 0
    aborted: bool = False      # Ctrl+C 中断标志
    file_states: dict          # read-before-edit 的新鲜度记录（运行时动态添加）
```

**核心价值：打破循环导入。** 工具要访问记忆、权限要访问配置、loop 要访问一切——如果都用 `import`，必然环。解法是：所有模块只依赖 `AgentContext` 这个「插线板」，运行时把各子系统插上去（`ctx.tools = registry`），需要时 `getattr` 取。

> 注意 `file_states` 是**运行时动态挂在 ctx 上的**（`ctx.file_states = {...}`），而不是 dataclass 字段。这是 Python 动态性的活用，也提醒你：`ctx` 是一个「可以随时往里塞东西」的共享背包。

---

## 5. 数据协议：消息模型

`agent_runtime/messages.py` 定义了整个系统的「通用货币」。

### 5.1 三种消息

| 角色 | 格式 | 何时产生 |
|---|---|---|
| `system` | `{"role":"system","content":...}` | 每轮组装，不存进 history |
| `user` | `{"role":"user","content":...}` | 用户输入 / sideQuery 摘要 / auto-compact 摘要 |
| `assistant` | `{"role":"assistant","content":...,"tool_calls":[..]}` | LLM 回复 |
| `tool` | `{"role":"tool","tool_call_id":...,"name":...,"content":...}` | 工具执行结果 |

### 5.2 关键数据结构

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = "{}"     # 原始 JSON 字符串（模型给的）
    parsed: dict = {}         # 解析好的参数 dict（工具实际用的）
```

**为什么同时存 `arguments` 和 `parsed`**：`arguments` 是 LLM 返回的原始字符串，回传模型时必须原样（保证 `tool_call_id` 能对上）；`parsed` 是给工具函数用的 dict。`from_openai` 在解析时做了容错——JSON 坏掉也能优雅降级为 `{}`。

### 5.3 token 估算

```python
def estimate_tokens(text: str) -> int:
    cjk = len(re.findall(r"[一-鿿]", text))
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4) + 1
```

**不引入 tiktoken 的原因**：那是重依赖。压缩系统只需要「相对大小」判断，不需要精确值。中文约 1.5 字/token、英文约 4 字符/token 的启发式够用且零成本。

---

## 6. 对外接口：统一 LLM 后端

`agent_runtime/backend.py` 是唯一跟外部世界说话的地方。

### 6.1 设计：一个入口，两种协议

```python
class LLMBackend:
    async def chat(self, messages, tools=None, stream_cb=None) -> LLMResult:
        # 内部按 config.provider 分派到 _chat_openai 或 _chat_anthropic
```

- **OpenAI 兼容**（默认）：`POST /chat/completions`，几乎全行业通用（GLM/DeepSeek/OpenAI…）。
- **Anthropic 原生**：`POST /v1/messages`，需要 `_to_anthropic_messages` 把 OpenAI 风格消息翻译过去。

### 6.2 流式输出（SSE 解析）

流式的本质：响应体是 `data: {...}\n\n` 一条条推过来的，不能等全部收完再解析。

```
OpenAI SSE:
data: {"choices":[{"delta":{"content":"你"}}]}
data: {"choices":[{"delta":{"content":"好"}}]}
data: [DONE]

Anthropic SSE:
event: content_block_delta
data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"你好"}}
```

`_stream_openai` / `_stream_anthropic` 各写了一个解析器，核心动作是：**收到 text 增量 → 调 `stream_cb(text)`**（把字符实时推到终端），同时把增量攒进 `content_parts` 供最终组装。工具调用的 `arguments` 是分片到达的，所以要按 `index` 累加拼接。

> 学习重点：`_assemble` 把「分片的内容 + 分片的工具调用」重组成完整的 `LLMResult`。这是流式编程最经典的模式——**边收边攒，收完组装**。

### 6.3 重试机制（`retry.py`）

```python
async def retry_async(func, cfg, retryable):
    for attempt in range(cfg.max_retries + 1):
        try:
            return await func()
        except Exception as exc:
            if attempt >= cfg.max_retries or not retryable(exc):
                raise
            await asyncio.sleep(backoff_delay(attempt, cfg))
```

- **指数退避**：`base_delay * 2^attempt`，封顶 `max_delay`。
- **全抖动**：`delay * (0.5 + random())`，把重试时间随机打散，避免多客户端「惊群」同时重试。
- **可重试判定**：超时、网络错误、`{408,429,500,502,503,504}` 才重试；4xx 业务错误不重试（重试也没用）。

`backend.chat` 把整个「构造请求 + 发请求 + 解析」包成一个闭包丢给 `retry_async`，这样重试就是「重新完整执行一次」，幂等且干净。

---

## 7. 工具系统

### 7.1 分层结构

```
tools/base.py       Tool 基类 + ToolResult        ← 约定工具长什么样
tools/registry.py   ToolRegistry                   ← 注册、延迟激活、执行、并发回退
tools/file_tools.py  read/write/edit               ← 文件三件套
tools/search_tools.py glob/grep                    ← 搜索
tools/shell_tools.py bash                          ← 命令执行
tools/web_tools.py   web_fetch/web_search          ← 联网（延迟）
tools/meta_tools.py  todo/task/记忆三件套           ← 元能力
tools/defaults.py    build_default_registry()      ← 装配 16 个工具
```

### 7.2 工具基类契约

```python
class Tool:
    name: str
    description: str
    parameters: dict          # JSON Schema（properties + required）
    lazy: bool = False        # True = 延迟激活
    keywords: list[str] = []  # 命中即激活的触发词

    def schema(self) -> dict:      # 转成 OpenAI function 格式喂给 LLM
    async def run(self, args, ctx) -> ToolResult:  # 子类实现
```

**一个工具 = 一段描述 + 一个 JSON Schema + 一个 async 函数**。`schema()` 决定 LLM「看不看得懂、能不能正确传参」，`run()` 决定「实际做什么」。

### 7.3 16 个工具与激活策略

| 常驻工具（lazy=False） | 延迟工具（lazy=True） | 延迟工具触发关键词举例 |
|---|---|---|
| read_file | web_fetch | "抓取/url/http/资料" |
| write_file | web_search | "搜索/查一下/最新" |
| edit_file | task | "子任务/分派/并行" |
| glob | memory_save | "记住/以后记得" |
| grep | memory_recall | "回忆/之前/上次" |
| bash | list_memory | "列出记忆" |
| todo_write | | |
|  | rag_index | "索引/入库/知识库" |
|  | rag_search | "检索/查资料/查文档" |
|  | rag_list | "列出知识库/索引列表" |

**延迟激活的意义**：工具 schema 本身占 token（一个工具的 name+description+schema 可能几百 token）。如果 16 个全注入，光工具描述就吃掉几千 token。延迟工具只在「用户输入命中关键词」或「显式 /activate」时才注入，其余时候白省 token。

```python
# registry.py
def lazy_activate_by_text(self, user_text) -> list[str]:
    for tool in self._tools.values():
        if tool.lazy and tool.name not in self._active:
            if any(kw in user_text.lower() for kw in tool.keywords):
                self._active.add(tool.name)
```

### 7.4 并发执行 + 回退（`run_tool_calls`）

```python
if len(tool_calls) == 1:
    return [await self.run_tool(...)]           # 单工具直接跑
try:
    return list(await asyncio.gather(*[...]))   # 多工具并发
except Exception:
    # 并发失败 → 串行回退
    for tc in tool_calls: results.append(await self.run_tool(...))
```

**为什么并发**：LLM 一次可能调 3 个工具（读 3 个文件），串行是 3 倍耗时，`gather` 并发就是 1 倍。**为什么回退**：某些工具可能共享文件句柄或 shell 状态，并发有风险；失败时降级串行保证「至少能完成」。

### 7.5 read-before-edit + mtime 新鲜度（`file_tools.py`）

这是工具系统里**最值得学的安全机制**：

```python
# read_file 时记录文件指纹
def _file_state(ctx, path):
    st = path.stat()
    state = {"mtime": st.st_mtime, "hash": sha256(path.read_bytes())}
    ctx.file_states[str(path)] = state

# edit_file 时校验
if str(path) not in ctx.file_states:
    return error("必须先 read_file（read-before-edit 保护）")
if abs(current_mtime - recorded_mtime) > 1e-6:
    return error("文件已被外部改动，请重新 read_file")
```

- **read-before-edit**：防止 LLM「闭着眼睛改一个它根本没读过的文件」。
- **mtime 校验**：防止「用户读完后，别的进程改了文件，Agent 还基于旧内容去编辑」导致覆盖别人的改动。
- `edit_file` 用的是**精确字符串替换**（`old_string → new_string`），并要求 old 唯一或显式 `replace_all`，把「改错地方」的风险降到最低。

---

## 8. 权限安全体系

### 8.1 四层管控的判定顺序

`permission/manager.py` 的 `check()` 是核心，判定顺序即优先级：

```
① bypassPermissions 模式？            → 直接 allow（最顶层开关）
② 命中 deny 规则？                    → deny（规则里 deny 永远优先）
③ 命中 allow 规则？                   → allow
④ 危险检测（bash 命令 / 写路径越界）  → 标记危险，走确认
⑤ plan 模式 且非只读？               → deny
⑥ acceptEdits 且是文件编辑且不危险？  → allow
⑦ 只读工具？                         → allow
⑧ dontAsk 模式？                     → deny（绝不询问）
⑨ 走到这里 → 交互确认（allow/deny/allow_always）
```

### 8.2 五个文件的分工

| 文件 | 职责 |
|---|---|
| `modes.py` | 5 种模式的定义 + `resolve_mode` 归一化 |
| `rules.py` | `Rule`/`RuleSet`，声明式 allow/deny，JSON 持久化 |
| `dangerous.py` | 18 类危险命令正则 + `detect_danger` |
| `manager.py` | 编排上述三层 + 交互确认 + 白名单 |

### 8.3 5 种权限模式

| 模式 | 语义 | 适用场景 |
|---|---|---|
| `default` | 读放行、写/命令确认、危险拦截 | 日常开发 |
| `plan` | 纯只读，拒绝一切副作用 | 先出方案不落地 |
| `acceptEdits` | 自动接受文件编辑，命令仍确认 | 信任文件操作、防命令误伤 |
| `bypassPermissions` | 全放开 | 受信任沙箱/自动化 |
| `dontAsk` | 绝不询问，只认显式 allow | 无人值守 CI |

### 8.4 危险命令检测

`dangerous.py` 里 18 条正则，覆盖：递归删除 `rm -r`、提权 `sudo`、格式化 `mkfs`、写块设备 `dd of=/dev/`、关机、`curl|sh` 管道执行、`git push --force`、`git reset --hard`、`drop database`、覆写系统文件、杀进程、清防火墙、读密钥、导凭证……

```python
def detect_danger(command: str) -> list[DangerousPattern]:
    hits = [p for p in DANGEROUS_PATTERNS if re.search(p.pattern, command, re.I)]
```

**关键设计**：危险检测只做「标记」，不做「判决」。它给 `check()` 提供一个 `danger_reason`，最终判 allow/deny 还是由模式+规则+交互决定。这样检测逻辑和决策逻辑解耦。

### 8.5 交互确认 + 白名单

```python
# 回调返回 "allow" | "deny" | "allow_always"
answer = await self.ask_callback(tool_name, args, reason)
if answer == "allow_always":
    self.whitelist.add_allow(tool_name, re.escape(subject), ...)
    self.whitelist.save()   # 持久化为规则，下次自动放行
```

- `ask_callback` 由 CLI 注入（`app._ask_permission`），非交互环境没注入时默认 `deny`——**安全默认拒绝**。
- 「总是允许」会把当前操作 `re.escape` 后存成 allow 规则，落到 `~/.miniclaudecode/permissions/whitelist.json`。这就是「白名单机制」的落地。

---

## 9. 上下文压缩与记忆

### 9.1 4 级流水线（`pipeline.py`）

| 级别 | 文件 | 成本 | 触发 | 动作 |
|---|---|---|---|---|
| budget truncation | `budget.py` | 零 | 始终兜底 | 超预算 FIFO 丢最旧消息 |
| stale snip | `snip.py` | 零 | ≥70% | 剪短过期工具返回（留 200 字） |
| microcompact | `micro.py` | 零 | ≥70% | 单条消息截断到 4k（工具 2k） |
| auto-compact | `auto.py` | LLM 调用 | >85% | 全量 LLM 摘要 |

**核心思想：渐进增强。** 先做免费的（截断/剪枝），实在扛不住了才花钱（LLM 摘要）。阈值分三档：

```python
TIGHTEN_RATIO = 0.50   # ≥50%：ctx.tight_output=True，工具输出从 30000 收紧到 8000
compact_soft_ratio = 0.70
compact_hard_ratio = 0.85
```

### 9.2 每一级做了什么

**budget_truncate**：从最旧的非 system 消息开始丢，system prompt 永不丢。这是最后的保险丝。

**stale_snip**：工具返回通常是体积大头，但「很久以前」的工具结果对当前决策价值已衰减。保留最近 6 条完整，更早的只留开头 200 字 + 一句「已剪枝」。

**microcompact**：不调 LLM，纯字符串操作——折叠空白、头尾截断。廉价但能实打实省 token。

**auto_compact**：唯一动用 LLM 的一级。把较早的历史喂给模型，让它提炼出「目标/决策/文件改动/错误/进度」的结构化摘要，替换掉原始历史，只留最近 6 条 + system。`_SUMMARY_PROMPT` 精心列了 5 个必须保留的要点，这是压缩质量的保证。

### 9.3 跨会话记忆（`memory.py`）

```python
class MemoryStore:
    async def save(content, tags) -> entry_id   # 写 JSON
    async def recall(query, limit) -> [entry]   # 词元重叠 + 标签加权打分
    async def list_all() -> [entry]
```

- 持久化在 `~/.miniclaudecode/memory.json`，**不依赖对话历史**——下次开新会话，记忆还在。
- `recall` 的「语义召回」是轻量实现：中文按字切、英文按词切，算 query 与 entry 的 token 重叠 + 标签命中加权。**预留了 `embedding_fn` 扩展点**，想升级成真正的向量召回只需传入一个 embedding 函数。
- `_tokenize` 同时把「每个汉字」和「每个英文单词」都当 token，这是中英混合场景的实用技巧。

### 9.4 sideQuery / 预取 / 新鲜度（`sidequery.py`）

```python
async def side_query(ctx, user_text, limit=3) -> str:
    entries = await ctx.memory.recall(user_text, limit)
    return "\n".join(f"[记忆召回] {e.content}" for e in entries)

async def prefetch_memory(ctx):      # 会话启动时后台预热
def freshness_reminder(ctx, path):   # 文件被外部改动时提醒重读
```

- `side_query` 每轮开始前跑一次，把召回的记忆**注入 system prompt**，让 Agent「记得」跨会话的上下文。
- `prefetch_memory` 在启动时预热，避免首轮召回阻塞。
- `freshness_reminder` 复用 read_file 存的 mtime，检测「读完后被外部改过」的文件并提醒。

---

## 10. 系统提示词管理

### 10.1 CLAUDE.md 层级加载（`loader.py`）

```python
def load_claude_md(start_dir, home_dir=None) -> str:
    # 1) 从工作目录向上逐级找 CLAUDE.md / .claude/CLAUDE.md
    # 2) 追加用户全局 ~/.claude/CLAUDE.md
    # 3) 展开 @include（递归 + 循环检测）
    # 4) _cap_lines 截断到 200 行
```

**层级语义**：越靠近工作目录的规则越具体、越优先（排前面）。全局 `~/.claude/CLAUDE.md` 是兜底。

### 10.2 @include 递归解析

```python
@include ./extra.md        # 相对当前文件所在目录解析
@include ../common/rules.md
@include "path with space.md"
```

实现要点：
- `_INCLUDE_RE` 匹配行首 `@include 路径`；
- 相对路径以「被 include 文件的目录」为基准（`_expand_includes(sub, p.parent, seen, depth+1)`）；
- `seen` 集合检测循环引用，`MAX_INCLUDE_DEPTH=10` 兜底防环；
- 找不到文件/读失败不崩，只留一行 `[未找到]` 占位。

### 10.3 200 行约束

`_cap_lines` 把合并后的内容硬截到 200 行，超出的部分换成一行「已截断」提示。**这是「CLAUDE.md 开销可控」的硬保证**——无论项目规则写多少，带入上下文的成本都有上限。

### 10.4 多层级 system prompt（`system_prompt.py`）

```python
def build_system_prompt(ctx, claude_content, memory_content) -> str:
    layers = [BASE_PROMPT]                    # ① 基础层：角色/工具纪律/安全底线
    if claude_content: layers.append("项目指令\n"+claude_content)   # ② 项目层
    if memory_content: layers.append("跨会话记忆\n"+memory_content)  # ③ 记忆层
    layers.append("运行环境\n(日期/目录/模式/模型)")   # ④ 动态层
    return "\n\n".join(layers)
```

**多层级注入的意义**：不同来源的指令按「通用性→具体性」排列，既保证了基础行为规范（工具纪律、安全底线），又允许项目规则和记忆动态叠加。改某一层不影响其他层。

---

## 11. Agent 主循环：把一切串起来

`agent_runtime/loop.py` 的 `AgentLoop` 是整个系统的心脏，前面所有模块在这里汇合。

```python
class AgentLoop:
    def __init__(self, ctx, backend, tools, permissions, compressor):
        self.history = []      # 对话历史（不含 system，system 每轮现组）
        self.system_prompt = ""

    async def run(self, user_text, stream_cb=None, on_event=None) -> str:
        # ① 延迟激活
        self.tools.lazy_activate_by_text(user_text)
        # ② 记忆召回
        memory_content = await side_query(ctx, user_text)
        # ③ 组装 system
        system = build_system_prompt(ctx, self.claude_content, memory_content)
        # ④ 追加用户消息
        self.history.append(user_message(user_text))

        for _ in range(ctx.config.max_tool_rounds):        # 防死循环上限
            messages = [system_message(system)] + self.history
            messages = self.compressor.maybe_soft(messages, ctx)   # 软压缩
            result = await self.backend.chat(messages, tools=self.tools.active_schemas(), stream_cb=stream_cb)
            ctx.token_used += result.usage.total

            if not result.tool_calls:          # 纯文本 → 结束
                self.history.append(assistant_message(result.content))
                return result.content

            self.history.append(assistant_message(result.content, result.tool_calls))

            # 权限预检（串行，避免交互式确认打架）
            for i, tc in enumerate(result.tool_calls):
                decision = await self.permissions.check(tc.name, tc.parsed)
                if decision.status == "deny":
                    tool_results[i] = tool_message(tc.id, tc.name, f"[权限拒绝] {decision.reason}")
                else:
                    runnable.append((i, tc))

            # 并发执行 + 回退
            outs = await self.tools.run_tool_calls([tc for _, tc in runnable], ctx)
            # ... 拼 tool 消息，触发 on_event("tool_result")

            self.history = await self.compressor.maybe_hard(self.history, ctx)  # 硬压缩
        return "(达到工具往返上限)"
```

### 11.1 逐层解读：一次往返的全貌

先把整个 `run` 压缩成一句话：

> **组装 system → 追加用户消息 → 反复「问模型 → 让模型决定要不要调工具 → 执行工具 → 把结果喂回去」，直到模型给出纯文本答案为止。**

**关于 `history` 为什么不含 system**：`history` 只存 user / assistant / tool 三类消息。system 每一轮都要根据记忆召回、权限模式、压缩状态**现组**，塞进 `history` 就「陈」了。所以它单独存 `system_prompt` 字段，每次 `chat` 前重新拼到最前面。

**预热四步（进入循环之前）**：

| 步 | 代码 | 作用 |
|---|---|---|
| ① 延迟激活 | `tools.lazy_activate_by_text(user_text)` | 不是 16 个工具全塞给模型，而是按用户这句话里的关键词动态激活（如出现「搜索」才激活 web 工具），省 token |
| ② 记忆召回 | `side_query(ctx, user_text)` | 用当前问题去跨会话记忆里捞相关内容，是「跨会话记忆」的入口 |
| ③ 组 system | `build_system_prompt(...)` | 基础层 + CLAUDE.md + 召回记忆，每轮现组保证新鲜 |
| ④ 追加消息 | `history.append(user_message(...))` | 用户这句话正式进入历史 |

**主循环五步（每一轮）**：

1. **软压缩 + 调模型**：`[system] + history` 拼好后先过 `maybe_soft`（**不调 LLM** 的轻量压缩：截断/剪枝），再 `backend.chat` 调模型，最后 `ctx.token_used += usage.total` 记账——这个计数是后面压缩流水线的**分母**（>50% 收紧、>85% 硬压缩）。
2. **判断是否调工具**：`result.tool_calls` 为空 = 模型直接给了最终答复 → 存进 history、返回。这是**唯一的正常出口**。
3. **权限预检（串行）**：逐工具调 `permissions.check`。注释点出精髓——**交互式确认必须串行**，否则多个确认框同时弹，用户会打架。被拒的工具**不执行**，直接回填一条 `[权限拒绝] 原因` 的 tool 消息。
4. **并发执行 + 回退**：只有通过预检的工具才进入 `run_tool_calls`，内部 `asyncio.gather` 并发跑，失败回退串行。
5. **硬压缩**：`maybe_hard` 检查利用率，**>85% 才调用 LLM 做全量摘要**，把臃肿历史压成精炼摘要，再进入下一轮。

**两个出口**：正常出口（模型不再调工具，返回答复）和兜底出口（`for` 循环跑满 `max_tool_rounds`，返回 `"(达到工具往返上限)"`）。外层 `for` 不是普通迭代，而是**死循环保险丝**——模型可能反复「再改一下」，这个上限防止它无限烧 token。

**软 / 硬压缩的分工**：软压缩「无 LLM、便宜、每轮做」，硬压缩「有 LLM、贵、只在超阈值时做」——这是「上下文可持续」成本与效果之间的平衡点。

**几个值得注意的设计决策**：

1. **system 每轮现组、不存 history**：因为记忆召回、权限模式可能每轮变化，system 是动态的，所以每次 `chat` 前重新拼。
2. **权限预检串行、工具执行并发**：交互式确认是串行的（多个弹窗没法同时问），但确认通过后工具执行可并发（省时）。这是「串行决策 + 并行执行」的分层。
3. **被拒的工具不执行、直接返回 `[权限拒绝]` 消息**：让 LLM 知道「这条被拦了」，它才能换个方案或向用户解释，而不是傻等一个永远不会来的结果。
4. **`on_event` 回调**：把工具调用/结果「广播」给 CLI 展示，让 loop 保持纯净、不直接碰 Rich。

---

## 12. CLI 外壳

### 12.1 装配器（`app.py`）

`MiniClaudeApp` 唯一职责：**把 6 个子系统按正确顺序装配起来**。

```python
def __init__(self, config):
    self.ctx = AgentContext(config)
    self.backend = LLMBackend(config)
    self.tools = build_default_registry()
    self.permissions = PermissionManager(config)
    self.memory = MemoryStore(...)
    self.compressor = ContextCompressor(config, self.backend)
    self.session_store = SessionStore(config.data_dir)
    self.loop = AgentLoop(ctx, backend, tools, permissions, compressor)
    # 回填 ctx 依赖 + 注入权限回调 + 加载 CLAUDE.md
```

注意装配顺序：先造各子系统，再 `ctx.tools = ...` 回填，最后 `AgentLoop(...)` 把它们串起来。这个顺序就是依赖图的拓扑序。

### 12.2 REPL 主循环

```python
async def run(self):
    print_welcome(...)
    await prefetch_memory(self.ctx)
    while self.running:
        line = await asyncio.to_thread(self._read_line)   # input() 放线程池，不阻塞事件循环
        if line.startswith("/"):
            await self.slash.dispatch(line)
        else:
            await self._handle_message(line)
    await self.backend.close()
```

**关键技巧**：`input()` 是阻塞调用，直接放 async 里会卡死事件循环。用 `asyncio.to_thread` 把它丢到线程池，这样流式输出、后台预取等异步任务不受影响。

### 12.3 流式渲染（`display.py`）

```python
def make_stream_writer():
    state = {"started": False}
    def cb(text):
        if not state["started"]:
            console.print("[bold green]助手[/] ", end="")   # 首次先打标签
            state["started"] = True
        console.print(text, end="", markup=False)           # 增量不打换行
    return cb, state
```

`console.print(..., end="")` 是关键——不换行，让字符一个个「长」出来，实现打字机效果。`state["started"]` 标记避免重复打印「助手」标签。

### 12.4 会话持久化（`session.py`）

```python
class SessionStore:
    def save(session_id, history, meta)   # 写 sessions/<id>.json
    def load(session_id) -> dict          # 读回
    def list_sessions() -> [meta]         # 扫目录列元信息
```

会话就是一个 JSON 文件，含 `history`（消息列表）+ `meta`（标题/模型/模式/时间）。`app._autosave` 每轮结束自动保存，崩溃/中断后可 `/session load` 恢复。这是「上下文可持续」在**会话层面**的体现。

### 12.5 slash 命令（`slash.py`）

`SlashCommands.dispatch` 用「方法名映射」实现：`/model` → `cmd_model`。命令之间完全解耦，加新命令就是加一个 `cmd_xxx` 方法。命令通过 `self.app` 访问各子系统（切模型改 `config.model`、切模式改 `permissions.set_mode`、恢复会话改 `loop.history`）。

---

## 13. 关键机制专题

### 13.1 read-before-edit 完整链路

```
用户: "改一下 main.py 的日志"
  → LLM 决定调 read_file(path="main.py")     # ① 先读
  → read_file 记录 ctx.file_states["main.py"] = {mtime, hash}
  → LLM 决定调 edit_file(path="main.py", old="print(...)", new="logging.info(...)")
  → edit_file 校验: ① 是否读过 ② mtime 是否没变 ③ old_string 是否精确匹配
  → 通过才写盘，写完后刷新 file_states
```

三道闸门：**读过没？改过没？匹配不？** 任一不过都拒绝，绝不盲写。

### 13.2 一次工具调用的权限全链路

```
LLM 想调 bash(command="rm -rf /tmp")
  → loop 调 permissions.check("bash", {"command":"rm -rf /tmp"})
  → 规则层：无 deny/allow 命中
  → 危险层：detect_danger 命中 rm_recursive
  → 模式层：default 模式，bash 属命令类，需确认
  → 交互层：弹出「危险命令：rm_recursive(递归删除目录)」，等用户 y/a/n
  → 用户选 a(总是允许) → whitelist.json 写入 allow 规则 → allow
  → loop 执行 bash 工具
```

下次同样命令直接命中 whitelist，不再弹窗。

### 13.3 上下文压缩的触发节奏

```
token 用量 0%────────50%────────70%────────85%───────100%
              │          │          │           │
              │     tighten     micro      auto-compact
              │     工具输出收紧  snip+micro  LLM 摘要
              └──── 始终 budget_truncate 兜底 ────┘
```

利用率越高，手段越「贵」越「狠」。`ctx.token_used` 是唯一的分母依据，`ContextCompressor.utilization` 统一计算。

### 13.4 流式输出的数据流

```
后端 httpx 收到 SSE 分片
  → _stream_openai 解析 data: 行
  → 取出 delta.content
  → stream_cb(text)  ────►  display 增量打印到终端（打字机效果）
  → 同时 content_parts.append(text)（攒着备用）
  → [DONE] 后 _assemble 组装完整 LLMResult 返回给 loop
```

「实时展示」和「最终组装」两条线并行，互不干扰。

---

## 14. 一步步搭建的完整过程

> 这一节复盘**我实际是怎么搭的**，以及**为什么是这个顺序**。核心原则：**先定数据协议和地基，再从「无依赖的叶子模块」往「有依赖的编排模块」搭，最后套外壳。**

### 第 1 步：地基 —— `config.py` + `context.py`

先写这两样，因为它们**零依赖**，且全项目都依赖它们。

- `config.py`：把「模型、后端、阈值、路径」这些散落的参数收敛成一个 dataclass。不先定这个，后面每个模块都要各自读环境变量，会乱。
- `context.py`：预见到「工具要访问记忆、权限要访问配置、loop 要访问一切」必然产生循环导入，于是先造一个 `AgentContext` 插线板。

> **为什么最先做**：它们是「协议之上的协议」。没有统一配置对象和共享容器，后面每写一个模块都得纠结「参数怎么传、状态放哪」。

### 第 2 步：数据协议 —— `messages.py`

定义了「消息长什么样」（`user/assistant/tool/system`）、「工具调用长什么样」（`ToolCall`）、「结果长什么样」（`LLMResult/Usage`），外加 `estimate_tokens`。

> **为什么第二步**：消息是 backend 和 loop 之间的「通用货币」。先把币种定义清楚，两端才能各自独立开发。

### 第 3 步：纯工具函数 —— `retry.py`

指数退避 + 抖动重试。它是**纯函数式**的（输入函数、返回结果），不依赖任何项目模块。

> **为什么第二步/三步之间可以并行走**：`messages` 和 `retry` 互相独立，谁先谁后都行。但它们在 backend 之前，因为 backend 要用它们。

### 第 4 步：对外接口 —— `backend.py`

统一 LLM 后端。这步是「最难也最独立」的一块，因为它要处理两种协议 + 流式 SSE 解析 + 重试封装。做完这步，项目第一次「能跟模型对话」了（哪怕还没有工具和权限）。

> **为什么这一步要先于工具/权限**：backend 是能力底座。可以先写个最小 demo 验证「能拿到模型回复」，再往上盖工具层，这叫「先跑通最小闭环」。

### 第 5 步：工具系统 —— `base.py` → `registry.py` → 各工具 → `defaults.py`

- 先 `base.py` 定工具契约（`schema`/`run`）；
- 再 `registry.py` 做注册、延迟激活、并发回退；
- 然后逐个写 6 个工具模块（文件→搜索→shell→web→meta）；
- 最后 `defaults.py` 统一装配 16 个。

> **为什么先 base 再 registry 再实现**：契约先行。定了 `Tool.run(args, ctx) -> ToolResult` 这个签名，写 16 个工具就是 13 次「填空」，注册表也能和具体工具解耦。

### 第 6 步：权限体系 —— `modes` → `dangerous` → `rules` → `manager`

四个文件从「纯定义」到「编排」：

- `modes.py`/`dangerous.py`/`rules.py` 都是**纯数据**（模式表、正则表、规则表），零依赖；
- `manager.py` 把它们编排成 `check()` 的判定链。

> **为什么放在工具之后**：权限管的是「工具的调用」，先有工具才有「管什么」。但 manager 本身不依赖工具实现，只依赖「工具名 + 参数」这个抽象，所以可以和工具并行写。

### 第 7 步：上下文压缩 + 记忆 —— `memory` → `budget/snip/micro` → `auto` → `pipeline`

- `memory.py` 先独立（记忆不依赖压缩）；
- `budget/snip/micro` 三个纯函数式压缩（不调 LLM）；
- `auto.py` 需要 backend（LLM 摘要），所以排在 backend 之后；
- `pipeline.py` 最后编排成 `maybe_soft/maybe_hard`。

> **为什么这一堆要拆成 6 个文件**：每种压缩策略是独立可替换的算法。拆开的好处是「单独测某一种压缩」，也能单独升级某一种（比如把 auto 的摘要换成更强的模型）。

### 第 8 步：提示词管理 —— `loader.py` + `system_prompt.py`

CLAUDE.md 层级加载 + @include，多层级 system prompt 组装。这两块**只依赖 config 和 context**，随时可插。

### 第 9 步：Agent 主循环 —— `loop.py`

**这是把 1~8 步全部串起来的「收口」**。到这一步，所有零件都齐了，loop 只做「编排」：延迟激活→记忆召回→组 system→调模型→权限预检→并发执行→压缩→循环。

> **为什么 loop 放最后（相对后端工具）**：loop 依赖 backend、tools、permissions、compressor 四样，必须是「被依赖者都就位」之后才能写。这体现了**依赖倒置**：loop 不实现任何具体能力，只调度。

### 第 10 步：CLI 外壳 —— `display` → `session` → `slash` → `app` → `main`

最后套壳：

- `display.py`（纯渲染）、`session.py`（纯持久化）可先写；
- `slash.py` 命令实现依赖 app 的各子系统；
- `app.py` 是装配器，把 loop 和各子系统接上，并注入权限回调、流式回调；
- `main.py` 解析 CLI 参数，`__main__.py` 提供 `python -m` 入口。

> **为什么 CLI 最后**：外壳是「最薄」的一层，只负责装配和交互，不能包含业务逻辑。如果先写 CLI，很容易把业务逻辑耦合进界面层，后面改不动。

### 完整依赖拓扑总结

```
config / context / messages / retry / modes / dangerous / rules
        │  │  │  │
        │  │  └──► backend ──────────────────────────┐
        │  └─────► tools(base→registry→16工具) ──────┤
        │         permission(manager) ───────────────┤
        └────────► context_compress(memory→...→pipeline)┤
                    prompt_loader ─────────────────────┤
                        └────────────────────────► loop ◄── 编排核心
                                                        │
                                                        ▼
                                            cli(app/slash/session/display)
                                                        │
                                                        ▼
                                            main.py / __main__.py
```

**一句话记住搭建方法论**：*先定协议与地基（config/context/messages），再从无依赖的叶子（retry/modes/dangerous/rules/memory/压缩算法）往上搭，最后用 loop 编排、用 cli 装配。*

---

## 15. 学习路线与练习建议

### 15.1 推荐阅读顺序（由浅入深）

1. **`config.py` + `context.py`**（30 分钟）：理解配置与共享容器。
2. **`messages.py` + `retry.py`**（30 分钟）：理解数据协议与重试。
3. **`backend.py`**（1 小时）：最硬的一块，重点看 SSE 解析和 Anthropic 翻译。
4. **`tools/base.py` + `registry.py` + `file_tools.py`**（1 小时）：工具契约、延迟激活、read-before-edit。
5. **`permission/manager.py`**（45 分钟）：四层判定链，边读边对照第 8.1 节的顺序。
6. **`context_compress/pipeline.py` + `auto.py`**（45 分钟）：压缩触发与 LLM 摘要。
7. **`agent_runtime/loop.py`**（1 小时）：串起一切，对照第 2.2 节时序图。
8. **`cli/app.py` + `main.py`**（30 分钟）：装配与入口。

### 15.2 动手练习（从易到难）

1. **加一个工具**：继承 `Tool` 写个 `read_lints`（跑 lint 返回结果），在 `defaults.py` 注册，看它出现在 `/tools` 里。
2. **加一条危险命令**：在 `dangerous.py` 的 `DANGEROUS_PATTERNS` 追加 `python -c ...` 这类危险项，测试 `detect_danger`。
3. **加一个 slash 命令**：在 `slash.py` 加 `cmd_status`，显示 `loop.current_tokens()` 和工具调用次数。
4. **改造语义召回**：给 `MemoryStore` 传入一个 `embedding_fn`，把词元打分换成向量相似度。
5. **加一种压缩级别**：在 `pipeline.py` 里插入一个「按消息类型优先级裁剪」的新级别，观察利用率变化。

### 15.3 三个最值得反复读的点

- **`backend.py` 的 `_stream_openai`**：流式 + 分片组装的经典范式，几乎所有 LLM 应用都会遇到。
- **`permission/manager.py` 的 `check`**：多条件优先级判定链，是「安全可预期」的灵魂。
- **`loop.py` 的 `run`**：把一个异步的多轮人机-工具协作循环写清楚，是 Agent 的核心。

---

*这份指南讲的是「为什么这样设计」和「怎么连起来」。真要精通，还是那句老话——读源码，改它，跑起来。*
