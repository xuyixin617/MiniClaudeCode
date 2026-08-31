# RAG 知识库检索模块指南

> 这份指南面向「想读懂并二次开发本项目 RAG 模块」的你。它不重复 README 的功能清单，而是讲清楚：
> **这个模块为什么存在、每一层怎么分工、一次检索在系统里到底经历了什么、以及怎么以最小侵入的方式把它接进既有 Agent。**
>
> 建议配合 `miniclaudecode/rag/`（store / embedding / retriever）与 `tools/rag_tools.py` 源码边读边看。
> 阅读路径：先读「全景图」和「核心设计思想」，再按「嵌入 → 存储 → 检索引擎 → 工具接入」逐层下钻，
> 最后看「一步步搭建」复盘整体施工顺序。

---

## 目录

1. [RAG 到底在解决什么](#1-rag-到底在解决什么)
2. [全景图：分层与数据流](#2-全景图分层与数据流)
3. [核心设计思想](#3-核心设计思想)
4. [嵌入抽象层：embedding.py](#4-嵌入抽象层embeddingpy)
5. [存储层：store.py](#5-存储层storepy)
6. [分块与检索引擎：retriever.py](#6-分块与检索引擎retrieverpy)
7. [工具接入：rag_tools.py](#7-工具接入rag_toolspy)
8. [如何接入既有 Agent（最小侵入改造）](#8-如何接入既有-agent最小侵入改造)
9. [关键机制专题](#9-关键机制专题)
10. [一步步搭建的完整过程](#10-一步步搭建的完整过程)
11. [学习路线与练习建议](#11-学习路线与练习建议)

---

## 1. RAG 到底在解决什么

一个 Coding Agent 的知识来源通常只有两条：**对话历史**和**临时塞进上下文的文件**。这带来三个真实痛点：

| 痛点 | 表现 | RAG 模块的解法 |
|---|---|---|
| **上下文装不下** | 项目文档几十个文件，全塞进 system prompt 会挤爆 token | 只把「与当前问题最相关」的几个分块捞进来 |
| **知识不跨会话** | 上次索引过的资料，下次开会话就没了 | SQLite 持久化，文档入库一次、长期可查 |
| **检索无语义** | 靠关键词 `grep` 只能命中字面，换个说法就搜不到 | 余弦相似度排序，按语义相关度返回 top-k |

**它和跨会话记忆（`memory.py`）的区别**：记忆是「Agent 自己沉淀的少量认知片段」，RAG 是「外部资料库的结构化检索」——体量大、可批量入库、按文档分块管理。两者都是「往 system prompt 里注入额外上下文」，但 RAG 解决的是**大规模资料的按需检索**。

---

## 2. 全景图：分层与数据流

### 2.1 模块分层图

```
                        ┌─────────────────────────────────────┐
                        │        tools/rag_tools.py           │   ← 延迟激活三件套
                        │  rag_index / rag_search / rag_list  │      (经 ctx.rag 访问引擎)
                        └──────────────────┬──────────────────┘
                                           │ getattr(ctx, "rag", None)
                        ┌──────────────────▼──────────────────┐
                        │      rag/retriever.py (RagEngine)    │   ← 门面：分块 + 索引 + 检索
                        └───┬──────────────────────┬──────────┘
                            │                      │
              ┌─────────────▼──────────┐  ┌────────▼─────────────┐
              │ rag/embedding.py       │  │ rag/store.py          │
              │ Embedder / lexical_embed│  │ SqliteStorage         │
              │ cosine                 │  │ documents + chunks    │
              └────────────────────────┘  └───────────────────────┘
```

**关键点**：`RagEngine` 是唯一对外门面。它把「嵌入（embedding）」「存储（store）」「分块（chunking）」串成一条链路，上层工具只知道 `ctx.rag`，不关心底下是 SQLite 还是向量库。

### 2.2 一次检索的完整时序

用户问 `"这个项目的权限是怎么设计的？"`，命中 `rag_search` 后经历了：

```
① 工具激活        registry.lazy_activate_by_text(text)   # 命中关键词 "检索/查文档/rag..." 才激活
② RagSearchTool.run(args, ctx)
     └─► rag = ctx.rag                                  # 取引擎
         └─► hits = rag.search(query, limit)

③ search 内部：
   ├─ q_emb = embedder.embed(query)                     # 查询向量（词元 or embedding_fn）
   ├─ 遍历 storage.list_chunks()                        # 所有分块
   │     └─ s = cosine(q_emb, chunk.embedding)          # 逐个算余弦相似度
   ├─ 按 s 降序排序，取 top-k（limit，默认 5）
   ├─ 一次性加载 list_documents() 建 doc_meta 映射       # 避免逐条查库
   └─ 组装 SearchHit(doc_id/source/title/chunk_index/text/score)

④ RagSearchTool 把结果拼成 Markdown 文本返回给模型
```

> 记住这条主链：**`embed(query)` 是提问的编码，`cosine` 是相关度的标尺，`store.list_chunks` 是被检索的语料，`top-k` 是「只喂最相关的」这一目的的实现。** 后面每层精讲都是这条链上的一个环节。

---

## 3. 核心设计思想

四个词概括本模块的取舍：

1. **最小侵入**——不修改 `loop / backend / permission / context_compress` 任何一行。RAG 以「延迟激活工具」的形式存在，通过 `ctx.rag` 访问，`AgentContext` 里只多了一个可选字段。核心编排对 RAG **零感知**，删掉 RAG 也不影响主流程。

2. **可升级**——嵌入被抽象成 `EmbeddingFn`。默认词元嵌入开箱即用；想换成真正的语义检索，只需注入一个「文本 → 向量」的函数，引擎自动切换到稠密向量余弦相似度，**其余代码一行不改**。

3. **零新增依赖**——存储层用标准库 `sqlite3`，刻意避开 Chroma / FAISS 等重依赖。既能持久化、又能跨线程访问，代价是检索在内存里线性扫描（语料不大时完全够用）。

4. **分层可替换**——`StorageBackend` 是抽象接口，`SqliteStorage` 是默认实现。未来换向量库只需实现同一接口，上层 `RagEngine` 无感知。

---

## 4. 嵌入抽象层：embedding.py

这一层回答「文本怎么变成可以算相似度的向量」。

### 4.1 词元嵌入 `lexical_embed`

```python
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[一-鿿]")

def lexical_embed(text: str) -> dict:
    vec: dict = {}
    for tok in _TOKEN_RE.findall((text or "").lower()):
        vec[tok] = vec.get(tok, 0.0) + 1.0
    return vec
```

- 返回 **稀疏向量** `dict[str, float]`：键是词元，值是词频。
- **中英混合技巧**：`[一-鿿]` 匹配每个汉字（中文按字切），`[a-zA-Z0-9_]+` 匹配每个英文单词/数字串（英文按词切）。这条正则和跨会话记忆 `MemoryStore._tokenize` 一脉相承，但这里输出的是「真正的向量」而不是「命中计数」。
- 词元嵌入没有「苹果 ≈ 梨」这种语义联想，它靠的是**字面重叠**：query 和 chunk 用词越像，得分越高。对中文文档这通常够用，因为中文的信息密度高、同义改写相对少。

### 4.2 余弦相似度 `cosine`

```python
def cosine(a, b) -> float:
    na, nb = _norm(a), _norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return _dot(a, b) / (na * nb)
```

- `_dot` / `_norm` 同时兼容 **稠密 `list[float]`** 和 **稀疏 `dict[str, float]`** 两种形态；两种形态混用（如 query 是稠密、chunk 是稀疏）会安全降级为 0。
- 稀疏 dict 的点积只遍历 `a`（query）的键，`b.get(k, 0.0)` 补零——这正是稀疏向量点积的标准写法，避免遍历整个词表。

### 4.3 嵌入器 `Embedder`

```python
class Embedder:
    def __init__(self, embedding_fn=None):
        self.embedding_fn = embedding_fn
    def embed(self, text):
        if self.embedding_fn is not None:
            return self.embedding_fn(text)
        return lexical_embed(text)
```

一个「要么用注入的 embedding_fn、要么退回词元嵌入」的分发器。**升级点就在 `embedding_fn` 这一个参数**——传进来的是返回 `list[float]` 的任意函数即可。

---

## 5. 存储层：store.py

这一层回答「文档和分块怎么可靠落盘、怎么增删查」。

### 5.1 两个数据结构

```python
@dataclass
class Document:
    doc_id: str        # uuid4().hex[:12]
    source: str        # 来源路径或标识（"inline" 表示内联文本）
    title: str = ""    # 展示名，缺省退回 source
    content: str = ""  # 原始全文（用于 list 时显示长度）
    created_at: float = 0.0
    chunks: list = field(default_factory=list)   # 1 个 Document → N 个 Chunk

@dataclass
class Chunk:
    chunk_id: str      # f"{doc_id}:{index}"
    doc_id: str        # 外键，关联所属文档
    index: int         # 在文档内的序号
    text: str          # 分块正文（检索最小单元）
    embedding: object = None   # list[float] 或 dict[str, float]，落盘时 JSON 序列化
    metadata: dict = field(default_factory=dict)
```

**核心关系**：`1 个 Document → N 个 Chunk`。文档是「入库单位」，分块是「检索单位」。检索命中的是某个分块，但返回时带上所属文档的 `source` / `title`，让模型知道这段来自哪个文件。

### 5.2 统一接口 `StorageBackend`

```python
class StorageBackend:
    def upsert_document(self, doc) -> None: ...
    def get_document(self, doc_id) -> Document: ...
    def delete_document(self, doc_id) -> bool: ...
    def list_documents(self) -> list: ...
    def list_chunks(self) -> list: ...
    def clear(self) -> None: ...
    def count_documents(self) -> int: ...
    def close(self) -> None: ...
```

把「存储」抽象成一个接口，是为了让 `RagEngine` 不绑定具体实现。**换库 = 实现同一接口**。

### 5.3 默认实现 `SqliteStorage`

```python
def __init__(self, path: str):
    self.path = Path(path)
    self.path.parent.mkdir(parents=True, exist_ok=True)     # 自动建目录
    self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
    self._lock = threading.Lock()
    self._init_schema()
```

三张表结构（`_init_schema`）：

```sql
documents(doc_id TEXT PRIMARY KEY, source TEXT, title TEXT, content TEXT, created_at REAL)
chunks(chunk_id TEXT PRIMARY KEY, doc_id TEXT, idx INTEGER, text TEXT, embedding TEXT, metadata TEXT)
-- 索引：idx_chunks_doc ON chunks(doc_id)
```

三个值得注意的实现决策：

1. **`check_same_thread=False` + `threading.Lock`**——允许跨线程访问（asyncio 回调、并发工具执行等场景），同时用锁串行化写操作，避免 SQLite 连接被多线程同时写坏。
2. **embedding / metadata 用 TEXT 列存 JSON**——`json.dumps(..., ensure_ascii=False)` 序列化、`json.loads` 反序列化（包在 try/except 里，损坏数据安全降级）。稀疏 dict 和稠密 list 都是 JSON 可表示的，所以这一层对「词元嵌入 / 稠密向量」一视同仁。
3. **幂等 upsert**——`INSERT OR REPLACE` 写文档，分块则「先 `DELETE` 后 `INSERT`」。这样同一 `doc_id` 重复入库时不会残留旧分块，`upsert` 语义干净。

---

## 6. 分块与检索引擎：retriever.py

这一层回答「怎么把长文档切成适合检索的块，以及怎么把上面两层串成一次检索」。

### 6.1 分块 `chunk_text`

```python
def chunk_text(text, size=500, overlap=100) -> list:
    # 1) 空文本直接返回 []
    # 2) 长度 ≤ size 直接返回 [text]（不切）
    # 3) 按空行切段落（re.split(r"\n\s*\n")），逐段累积
    # 4) 单段超长则硬切，块间保留 overlap 重叠
```

设计要点：

- **段落感知**：优先按空行（段落边界）切，而不是无脑按 `size` 字符硬切，避免把一句话劈成两半、破坏语义。
- **overlap 重叠**：超长段落硬切时，下一块从 `size - overlap` 处开始，让跨块边界的信息两边都保留一份，缓解「关键信息恰好被切开」的问题。
- 返回值是「分块正文」列表，`RagEngine` 再为每块编号、嵌入、落盘。

### 6.2 检索结果 `SearchHit`

```python
@dataclass
class SearchHit:
    doc_id: str
    source: str
    title: str
    chunk_index: int   # 命中块在文档内的序号
    text: str          # 命中的分块正文
    score: float       # 余弦相似度
```

### 6.3 门面 `RagEngine`

```python
class RagEngine:
    def __init__(self, path, embedding_fn=None, chunk_size=500, chunk_overlap=100):
        self.storage = SqliteStorage(path)
        self.embedder = Embedder(embedding_fn)
        ...
```

**索引侧**：

```python
def index_text(source, text, title="", metadata=None) -> str:   # 返回 doc_id
def index_file(path, title="", metadata=None) -> str:           # 读文件后转 index_text
def _build_chunks(doc_id, source, text, metadata) -> list:      # chunk_text → embed → Chunk
```

- `index_text` 生成 `doc_id = uuid.uuid4().hex[:12]`，分块 id 用 `f"{doc_id}:{i}"`。
- `index_file` 用 `read_text(encoding="utf-8", errors="replace")` 读文件，坏字节不会让入库崩溃。
- `title` 缺省退回 `source`（`index_file` 则退回文件名 `p.name`）。

**检索侧**（核心）：

```python
def search(query, limit=5, min_score=0.0) -> list:
    q_emb = self.embedder.embed(query)
    scored = []
    for c in self.storage.list_chunks():
        if c.embedding is None: continue
        s = cosine(q_emb, c.embedding)
        if s > min_score:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    top = scored[:limit]
    ...
    doc_meta = {d.doc_id: d for d in self.storage.list_documents()}   # 批量取文档元信息
    ...  # 组装 SearchHit
```

- **线性扫描全库打分**——语料不大时这是最直观正确的做法；换向量库时这一行会被替换成 ANN 索引。
- **`min_score` 过滤**——默认 0.0，只保留有字面重叠的分块（词元嵌入下无重叠即 0 分）。
- **批量加载文档元信息**——先 `list_documents()` 建映射再组装，避免 top-k 里逐条 `get_document` 查库。

**管理侧**：`list_indexed()` / `delete(doc_id)` / `clear()` / `close()`，全是 `storage` 的透传。

---

## 7. 工具接入：rag_tools.py

这一层回答「怎么让 Agent 能调 RAG，又不让它占着上下文」。

### 7.1 三个延迟激活工具

| 工具 | 作用 | 触发关键词（节选） |
|---|---|---|
| `rag_index` | 索引入库（文件/目录/内联文本） | 索引 / 入库 / 知识库 / 建库 / index / rag |
| `rag_search` | 语义检索 | 检索 / 查资料 / 知识库查询 / 查文档 / rag / search |
| `rag_list` | 列出已索引文档 | 列出知识库 / 有哪些文档 / 索引列表 |

三者都设 `lazy = True`——**默认不注入上下文**，命中用户输入关键词（或 `/activate rag_search`）才激活。理由和 `web_fetch` / 记忆工具一致：不常用的能力不该挤占每个请求的 token 预算。

### 7.2 解耦方式：`getattr(ctx, "rag", None)`

```python
async def run(self, args, ctx) -> ToolResult:
    rag = getattr(ctx, "rag", None)
    if rag is None:
        return ToolResult.error("RAG 引擎未初始化")
    ...
```

工具**不含任何检索逻辑**，只做「参数校验 → 调 `ctx.rag` → 拼结果」三件事。这样：

- 工具与引擎解耦，引擎可单独替换/单测；
- 若引擎未初始化（比如未来拆成可选插件），工具优雅报错而非崩溃。

### 7.3 入库的防呆 `_collect_files`

目录入库时（`rag_index` 的 `path` 指向目录）会：

- `_SKIP_EXT` 跳过二进制/大后缀（`.pyc/.png/.zip/.exe/.db/...`），避免误索引 `node_modules` 或构建产物；
- `_MAX_FILE_BYTES = 1_000_000` 跳过超过 1MB 的单文件，控制入库体积；
- 相对路径以 `ctx.config.cwd` 为基准解析；单个文件读失败不中断整批（`try/except: continue`）。

---

## 8. 如何接入既有 Agent（最小侵入改造）

这是本模块「最小侵入」承诺的落地清单。共改了 **3 个文件、各 1~3 行**，核心编排零改动：

**① `context.py`——加一个可选字段**

```python
class AgentContext:
    ...
    rag: Any = None   # RagEngine（知识库检索，可选）
```

放在 `memory` 字段旁，语义一致：都是「可选的跨会话/外部知识来源」。

**② `cli/app.py`——初始化 + 注入 + 关闭**

```python
from ..rag import RagEngine
...
self.rag = RagEngine(str(Path(config.data_dir) / "rag.db"))   # 初始化
...
self.ctx.rag = self.rag                                       # 注入共享容器
...
self.rag.close()                                              # 退出时关闭连接
```

**③ `tools/defaults.py`——注册工具**

```python
from ..tools.rag_tools import RagIndexTool, RagSearchTool, RagListTool
# 注册后 total 从 13 → 16，lazy 从 6 → 9
```

### 8.1 三种接入深度（按需升级）

| 模式 | 做法 | 代价 | 适用 |
|---|---|---|---|
| **延迟工具（现状）** | Agent 命中关键词才调 `rag_search` | 零额外 token | 通用默认 |
| **自动注入 system prompt** | 在 `loop.run` 的 `side_query` 旁加一句 `rag.search(user_text)`，把 top-1 拼进 `memory_content` | 每轮多几次余弦计算 | 想「无感」获得检索增强 |
| **混合** | 保持工具 + 把检索命中数写进动态层（如「知识库已命中 N 条」） | 少量 token | 让模型知道「该去查库」 |

**推荐从现状的「延迟工具」起步**：它把「要不要检索」的决策权交给模型，且不污染每一轮上下文。

---

## 9. 关键机制专题

### 9.1 检索打分全链路（一次 `search` 的生命周期）

```
query ──embed──► q_emb
                    │
所有 chunk.embedding ──cosine──► [(score, chunk), ...]   # 线性扫描
                    │
          sort(score 降序) → top-k
                    │
          min_score 过滤（默认 0.0，剔除零相关）
                    │
   批量取文档元信息 → SearchHit 列表
```

词元嵌入下，`cosine` 本质是「query 与 chunk 的**字面重叠度**归一化」。所以「查询词在块里出现得多、且该块本身短」的块得分最高——这是 TF（词频）与 IDF（长度归一）的自然近似。

### 9.2 幂等 upsert 与分块重写

`SqliteStorage.upsert_document` 用 `INSERT OR REPLACE` 写文档、`DELETE + INSERT` 重写分块。**意义**：同一 `doc_id` 重复入库是安全的，不会出现「文档更新了但旧分块还赖在表里」的脏数据。这也是 `rag_index` 能放心对同一文件反复索引的基础。

### 9.3 跨线程安全

SQLite 默认连接绑定创建它的线程；Agent 的并发工具执行（`asyncio.gather`）可能从不同线程碰同一个引擎。`check_same_thread=False` 放开限制 + `threading.Lock` 串行化写操作，是「够用且不引入连接池复杂度」的折中。

### 9.4 从词元到稠密向量：`embedding_fn` 升级

```python
# 默认：零依赖词元嵌入
eng = RagEngine("rag.db")

# 升级：注入任意「文本 → list[float]」函数（如本地/云端 embedding 模型）
def emb(text: str) -> list:
    return model.encode(text).tolist()          # 伪代码
eng = RagEngine("rag.db", embedding_fn=emb)
```

注入后，`Embedder.embed` 自动走 `embedding_fn`，`cosine` 自动按稠密向量计算，**检索/存储/工具代码全部无需改动**。这就是「开箱即用、可升级」设计的落点。

### 9.5 中英混合分词

`_TOKEN_RE = r"[a-zA-Z0-9_]+|[一-鿿]"` 的巧妙处：一个正则同时吃下「英文单词/数字串」和「单个汉字」。中文没有空格分词，按字切是最稳妥的零依赖方案；英文按词切则避免「每个字母当 token」造成的噪音。这与 `memory.py` 的 `_tokenize` 是同一套技巧，两处可互为印证。

---

## 10. 一步步搭建的完整过程

> 这一节复盘**实际施工顺序**，以及**为什么是这个顺序**。核心原则仍是全项目一致的：**先从「无依赖的纯函数叶子」往上搭，最后做「最小侵入接线」。**

### 第 1 步：嵌入层 `embedding.py`（纯函数叶子）

先写 `lexical_embed` / `cosine` / `Embedder`，因为它**零依赖**（只 import `math` / `re`），且是后面存储和检索都要用的底座。

> **为什么最先做**：嵌入是「文本 ↔ 向量」的协议。先定清楚向量长什么样（`dict` 稀疏 / `list` 稠密）、怎么算相似度，存储层才知道「该存什么」，检索引擎才知道「该怎么算」。

### 第 2 步：存储层 `store.py`（接口 + SQLite 实现）

定义 `Chunk` / `Document` 两个数据结构，再定 `StorageBackend` 接口，最后写 `SqliteStorage`。

> **为什么先接口后实现**：接口让「存储」成为可替换件。先写接口再写 SQLite，等于给自己留了「换向量库」的后门，也让 `RagEngine` 可以对着接口开发。

### 第 3 步：检索引擎 `retriever.py`（门面）

写 `chunk_text`（分块）和 `RagEngine`（把 store + embedding + chunking 串成 `index_text / search` 两个入口）。

> **为什么这一步是收口**：前两步都是「零件」，这一步才拼出「能入库、能检索」的完整能力。`RagEngine` 只做编排，不实现具体嵌入或落盘——依赖倒置。

### 第 4 步：工具接入 `rag_tools.py`

写 `RagIndexTool` / `RagSearchTool` / `RagListTool`。它们只依赖 `base.Tool` 契约和 `ctx.rag`，**不 import 任何 rag 内部实现**，天然与引擎解耦。

> **为什么工具最后、且与引擎解耦**：工具是「Agent 与引擎之间的适配层」，属于外壳性质。先有引擎，工具才有东西可调；解耦则保证引擎坏了、工具也能优雅报错。

### 第 5 步：最小侵入接线

`context.py` 加字段 → `app.py` 初始化/注入/关闭 → `defaults.py` 注册。三处各 1~3 行，核心编排零改动。

### 完整依赖拓扑总结

```
embedding.py (纯函数，零依赖)
      │
      ├──► store.py (StorageBackend + SqliteStorage)
      │          │
      └──────────┴──► retriever.py (RagEngine，门面)
                          │
                          ▼
                  tools/rag_tools.py (经 ctx.rag)
                          │
                          ▼
              context.py + app.py + defaults.py (最小侵入接线)
```

**一句话记住搭建方法论**：*先定「向量协议」（embedding）与「存储接口」（store），再拼「引擎」（retriever），最后用「延迟工具」（rag_tools）接进 Agent，接线只动三个文件的边角。*

---

## 11. 学习路线与练习建议

### 11.1 推荐阅读顺序（由浅入深）

1. **`rag/embedding.py`**（20 分钟）：词元嵌入 + 余弦，全文最短的一块，先看懂「向量」和「相似度」。
2. **`rag/store.py`**（30 分钟）：两张表 + 幂等 upsert + 跨线程锁，重点看 `upsert_document`。
3. **`rag/retriever.py`**（30 分钟）：`chunk_text` 的分块策略和 `search` 的打分链路。
4. **`tools/rag_tools.py`**（20 分钟）：延迟激活 + `getattr(ctx, "rag")` 解耦。
5. **`cli/app.py` 的 rag 三行 + `context.py` 字段**（10 分钟）：体会「最小侵入接线」怎么做到。

### 11.2 动手练习（从易到难）

1. **注入一个 embedding_fn**：写个「按 `ord(ch) % N` 分桶」的假向量函数传给 `RagEngine`，对比它与词元嵌入的检索排序差异。
2. **加 metadata 过滤**：在 `search` 里加一个 `filter_meta` 参数，只检索 `metadata` 匹配的分块，并在 `RagSearchTool` 暴露对应参数。
3. **自动注入 system prompt**：在 `loop.run` 的 `side_query` 旁加一句 `rag.search(user_text, limit=1)`，把 top-1 拼进 `memory_content`，观察 Agent 是否「无感」获得了检索增强。
4. **加一个 RAG 评估脚本**：准备几个「问题 → 期望命中文档」对，写脚本算 `search` 的 top-k 命中率，作为升级 embedding_fn 前后的对照。
5. **换存储后端**：实现一个 `StorageBackend`（比如基于 `json` 文件），替换 `RagEngine` 里的 `SqliteStorage`，验证接口抽象是否足够。

### 11.3 三个最值得反复读的点

- **`retriever.py` 的 `search`**：一条「embed → 打分 → 排序 → top-k」的经典检索链，几乎所有 RAG 系统的骨架。
- **`store.py` 的 `upsert_document`**：`INSERT OR REPLACE` + 分块 `DELETE + INSERT` 的幂等写法，是「可重复入库」的保障。
- **`embedding.py` 的 `_TOKEN_RE`**：一行正则同时处理中英文分词的零依赖技巧，值得背下来。

---
