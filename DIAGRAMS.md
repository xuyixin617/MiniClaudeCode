# MiniClaudeCode 流程图

> 本文档用 [Mermaid](https://mermaid.js.org) 绘制项目的核心流程图，覆盖架构、主循环、时序、权限、压缩与搭建顺序。
>
> **如何查看**：在 GitHub / GitLab 中打开本文件即可自动渲染；VS Code 安装
> 「Markdown Preview Mermaid Support」插件后可在预览中查看；也可用
> `npx -y @mermaid-js/mermaid-cli -i DIAGRAMS.md -o out.svg` 导出为图片。

---

## 1. 系统架构图

模块分层与依赖关系（数据流自顶向下，`AgentContext` 是共享容器）。

```mermaid
flowchart LR
    subgraph 入口层
        MAIN["main.py / __main__.py<br/>参数解析·装配·启动"]
    end

    subgraph 交互层
        APP["MiniClaudeApp<br/>装配器 + REPL"]
        SLASH["slash.py<br/>斜杠命令"]
        SESSION["session.py<br/>会话持久化"]
        DISPLAY["display.py<br/>Rich 展示"]
    end

    subgraph 核心编排
        LOOP["AgentLoop<br/>agent_runtime/loop.py"]
    end

    subgraph 能力子系统
        BACKEND["LLM Backend<br/>OpenAI兼容 + Anthropic + 流式"]
        TOOLS["工具系统<br/>16工具 + 延迟激活"]
        PERM["权限体系<br/>四层管控"]
        COMPRESS["上下文压缩<br/>4级流水线"]
    end

    subgraph 基础设施
        CTX["AgentContext<br/>共享容器"]
        CFG["Config<br/>配置"]
        PROMPT["prompt_loader<br/>system prompt + CLAUDE.md"]
        MEMORY["MemoryStore<br/>跨会话记忆"]
    end

    MAIN --> APP
    APP --> LOOP
    APP --> SLASH
    APP --> SESSION
    APP --> DISPLAY

    LOOP --> BACKEND
    LOOP --> TOOLS
    LOOP --> PERM
    LOOP --> COMPRESS

    TOOLS --> CTX
    PERM --> CTX
    COMPRESS --> MEMORY
    COMPRESS --> BACKEND
    PROMPT --> LOOP

    CTX --> CFG
    MEMORY --> CTX
```

---

## 2. Agent 主循环流程图

一条用户消息从进入到产出答复的完整决策循环（对应 `loop.py` 的 `run`）。

```mermaid
flowchart TD
    START(["用户输入"]) --> LAZY["工具延迟激活<br/>lazy_activate_by_text"]
    LAZY --> SIDE["sideQuery 记忆召回"]
    SIDE --> SP["组装多层级 system prompt<br/>基础层 + CLAUDE.md + 记忆 + 动态层"]
    SP --> APPEND["history.append(user 消息)"]

    APPEND --> LOOP{"第 N 轮<br/>N < max_tool_rounds ?"}
    LOOP -->|"是"| SOFT["软压缩 maybe_soft<br/>收紧/剪枝/微压缩/预算"]
    SOFT --> CHAT["调模型 backend.chat<br/>流式输出到终端"]
    CHAT --> TOKENS["累计 ctx.token_used"]
    TOKENS --> HAS{"是否有 tool_calls ?"}

    HAS -->|"无"| FINAL["append assistant 消息"]
    FINAL --> RETURN(["返回最终答复"])

    HAS -->|"有"| RECORD["append assistant(tool_calls)"]
    RECORD --> PRECHECK["权限预检（串行）<br/>permissions.check 逐工具判定"]
    PRECHECK --> DENIED{"被拒绝 ?"}
    DENIED -->|"是"| DENYMSG["返回 tool 消息<br/>[权限拒绝] 原因"]
    DENIED -->|"否"| RUN["并发执行工具<br/>run_tool_calls<br/>失败回退串行"]
    DENYMSG --> HARD
    RUN --> HARD["硬压缩 maybe_hard<br/>利用率 >85% 触发 LLM 摘要"]
    HARD --> LOOP

    LOOP -->|"否"| LIMIT(["达到工具往返上限"])
```

---

## 3. 一次对话的时序图

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant C as cli/app
    participant L as AgentLoop
    participant B as LLM Backend
    participant P as 权限管理器
    participant T as 工具注册表
    participant M as 压缩/记忆

    U->>C: 输入问题
    C->>L: run(text, stream_cb, on_event)
    L->>L: 工具延迟激活
    L->>M: side_query 记忆召回
    L->>L: 组装 system prompt
    L->>B: chat(messages, tools, stream_cb)
    B-->>C: 流式文本增量（打字机渲染）

    loop 工具往返（最多 max_tool_rounds 轮）
        B-->>L: LLMResult（含 tool_calls）
        L->>P: check(tool, args) 串行预检
        P-->>L: allow / deny
        L->>T: run_tool_calls 并发执行
        T-->>L: ToolResult
        L->>M: maybe_hard 硬压缩
    end

    B-->>L: 最终答复（无 tool_calls）
    L-->>C: 返回答案
    C-->>U: 渲染答案
    C->>C: _autosave 自动保存会话
```

---

## 4. 权限判定流程图

四层管控的完整判定链（对应 `permission/manager.py` 的 `check`，顺序即优先级）。

```mermaid
flowchart TD
    START(["工具调用请求"]) --> M0{"bypassPermissions ?"}
    M0 -->|"是"| ALLOW0(["allow · 绕过模式"])
    M0 -->|"否"| R1{"命中 deny 规则 ?"}
    R1 -->|"是"| DENY0(["deny · 规则拦截"])
    R1 -->|"否"| R2{"命中 allow 规则 ?"}
    R2 -->|"是"| ALLOW1(["allow · 规则放行"])
    R2 -->|"否"| R3{"命中白名单 ?"}
    R3 -->|"是"| ALLOW2(["allow · 白名单"])
    R3 -->|"否"| DANGER["危险检测<br/>bash 高危命令正则 / 写路径越界"]

    DANGER --> RO{"只读工具 ?"}
    RO -->|"是"| ALLOW3(["allow · 只读默认"])
    RO -->|"否"| PLAN{"plan 模式 ?"}
    PLAN -->|"是"| DENY1(["deny · 只读原则"])
    PLAN -->|"否"| AE{"acceptEdits 且<br/>文件编辑 且 无危险 ?"}
    AE -->|"是"| ALLOW4(["allow · 自动接受编辑"])
    AE -->|"否"| DA{"dontAsk 模式 ?"}
    DA -->|"是"| DENY2(["deny · 禁止询问"])
    DA -->|"否"| ASK["交互确认<br/>（附 danger_reason）"]

    ASK --> CHOICE{"用户选择"}
    CHOICE -->|"允许"| ALLOW5(["allow"])
    CHOICE -->|"总是允许"| WL["写入白名单并持久化"]
    WL --> ALLOW6(["allow · 白名单"])
    CHOICE -->|"拒绝"| DENY3(["deny"])
```

---

## 5. 上下文压缩流水线

4 级渐进式压缩，按上下文利用率分级触发（对应 `pipeline.py`）。

```mermaid
flowchart LR
    U(["上下文利用率<br/>token_used / context_window"])

    U -->|"0% ~ 50%"| B["budget truncation<br/>FIFO 预算截断"]
    U -->|"≥ 50%"| T["收紧工具输出<br/>tight_output=True"]
    U -->|"≥ 70%"| S["stale snip<br/>剪短过期工具返回"]
    U -->|"≥ 70%"| M["microcompact<br/>单条消息体积收紧"]
    U -->|"> 85%"| A["auto-compact<br/>LLM 全量摘要压缩"]

    B --> DONE(["上下文回到安全水位"])
    T --> DONE
    S --> DONE
    M --> DONE
    A --> DONE
```

---

## 6. read-before-edit + mtime 校验流程

编辑文件的安全闸门（对应 `tools/file_tools.py` 的 `edit_file`）。

```mermaid
flowchart TD
    R["read_file 读取文件"] --> REC["记录 file_state<br/>mtime + 内容哈希"]
    REC --> E{"edit_file 编辑"}

    E --> C1{"已读过该文件 ?<br/>file_states 有记录"}
    C1 -->|"否"| X1(["拒绝 · read-before-edit"])
    C1 -->|"是"| C2{"磁盘 mtime 未变 ?<br/>未被外部改动"}
    C2 -->|"否"| X2(["拒绝 · 文件被外部改动<br/>需重新 read_file"])
    C2 -->|"是"| C3{"old_string 精确匹配 ?"}
    C3 -->|"否"| X3(["拒绝 · 未找到原文"])
    C3 -->|"是"| OK(["执行替换并写盘<br/>刷新 file_state"])
```

---

## 7. 搭建顺序图

从零搭建本项目的依赖驱动施工顺序（详见 `GUIDE.md` 第 14 章）。

```mermaid
flowchart LR
    S1["① config + context<br/>地基与共享容器"]
    S2["② messages + retry<br/>数据协议与重试"]
    S3["③ backend<br/>统一 LLM 后端"]
    S4["④ tools<br/>16 工具 + 延迟激活"]
    S5["⑤ permission<br/>四层权限"]
    S6["⑥ 压缩 + 记忆<br/>4级流水线 + MemoryStore"]
    S7["⑦ prompt_loader<br/>system prompt + CLAUDE.md"]
    S8["⑧ loop<br/>Agent 主循环"]
    S9["⑨ cli<br/>装配器 + REPL"]
    S10["⑩ main<br/>入口"]

    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7 --> S8 --> S9 --> S10
```
