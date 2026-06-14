# Day 07 — 综合实战：文档问答系统

## 今日目标
把前六天所有模块组装成一个完整的 **文档问答系统**——FastAPI 后端 + RAG 引擎 + SSE 流式 + Web UI。

**今天全程 Claude Code 结对编程。** 你做架构决策，Claude Code 出第一版代码，你审查修改。

---

## 项目定位

```
一个文档智能问答后端，支持：
- 上传 PDF / Markdown / TXT → 自动分割 → Embedding → 入库
- 单轮问答：提问 → 检索 top_k → 拼接 Prompt → 生成答案 + 引用
- SSE 流式问答：逐字返回 + 最后追加来源
- 多文档会话：可同时对多份文档提问
- 对话管理：创建会话 → 多轮对话 → 查看历史
```

---

## 项目结构

```
week04/day07/
├── main.py              # FastAPI 应用入口 + lifespan + CORS + 中间件
├── core/
│   ├── config.py        # 全局配置（LLM/Embedding/Chroma/分割参数）
│   ├── database.py      # SQLAlchemy async 表定义 + get_db 依赖
│   ├── embedding.py     # Embedding 客户端（调 Ollama / OpenAI）
│   └── splitter.py      # 文档分割器（字符/递归/语义 + overlap）
├── rag/
│   ├── vector_store.py  # Chroma 操作封装（init/upsert/query/delete）
│   ├── retriever.py     # 检索器（语义 + Re-rank + Query Rewrite）
│   ├── generator.py     # LLM 生成器（非流式 + 流式 SSE）
│   └── pipeline.py      # RAG Pipeline 主入口（index / query / stream）
├── api/
│   ├── router.py        # 汇总所有子路由，注入 /api/v1 前缀
│   ├── documents.py     # 文档上传/列表/删除
│   ├── conversations.py # 对话管理（创建/列表/查消息）
│   └── qa.py            # 问答接口（普通 + SSE 流式）
├── web/
│   ├── index.html       # 上传 + 对话 UI
│   ├── style.css
│   └── script.js
└── uploads/             # 上传文件存储目录
```

---

## 核心模块设计（自己写）

### 1. `core/splitter.py` — 文档分割器

```python
class DocumentSplitter:
    def __init__(self, chunk_size=800, chunk_overlap=100): ...

    def split_pdf(self, file_path) -> list[dict]:
        """返回 [{"page": 1, "text": "...", "metadata": {...}}, ...]"""

    def split_text(self, text, source) -> list[dict]:
        """递归字符分割，保留自然段落边界"""

    def split(self, file_path, file_type) -> list[dict]:
        """统一入口"""
```

### 2. `rag/vector_store.py` — 向量库

```python
class VectorStore:
    def __init__(self, persist_path): ...

    async def add_chunks(self, doc_id, chunks, embeddings): ...
    async def query(self, query_embedding, top_k=5, doc_ids=None) -> list[dict]:
        """返回 [{"id":..., "text":..., "metadata":..., "distance":...}, ...]"""
    async def delete_document(self, doc_id): ...
    async def count(self) -> int: ...
```

### 3. `rag/retriever.py` — 检索器

```python
class Retriever:
    async def retrieve(self, question, top_k=5, conversation_id=None) -> list[dict]: ...
    async def rewrite_query(self, question) -> str: ...
    async def multi_query(self, question) -> list[dict]:
        """Multi-Query: 多条查询 → 合并去重"""
```

### 4. `rag/generator.py` — 生成器

```python
class Generator:
    async def generate(self, question, contexts, history=None) -> dict:
        """非流式，返回 {"answer":..., "sources":[...], "usage":{...}}"""

    async def generate_stream(self, question, contexts, history=None):
        """SSE 流式生成器，逐条 yield data: {...}"""
```

### 5. `rag/pipeline.py` — 主流水线

```python
class RAGPipeline:
    def __init__(self): ...
    
    async def index_document(self, file_path, filename, file_type) -> dict:
        """文档入库：split → embed → store → 返回 {doc_id, chunk_count}"""

    async def query(self, question, conv_id=None) -> dict:
        """非流式问答"""

    async def query_stream(self, question, conv_id=None):
        """SSE 流式问答"""
```

---

## API 路由设计

```
# 文档管理
POST   /api/v1/documents/          上传文档（multipart/form-data, file 字段）
GET    /api/v1/documents/          文档列表（分页）
GET    /api/v1/documents/{id}      文档详情
DELETE /api/v1/documents/{id}      删除文档（同时删向量库数据）

# 对话管理（可复用 Day 06 的 conversations 模块）
POST   /api/v1/conversations/          创建对话
GET    /api/v1/conversations/          对话列表
GET    /api/v1/conversations/{id}      对话详情
GET    /api/v1/conversations/{id}/messages  消息列表
DELETE /api/v1/conversations/{id}      删除对话

# 问答
POST   /api/v1/qa/                     非流式问答
POST   /api/v1/qa/stream               流式问答（SSE）

# 系统
GET    /health                         健康检查
```

---

## 统一响应格式

```python
# 成功
{"success": true, "data": {...}, "meta": {"page": 1, "total": 10}}

# 失败
{"success": false, "error": "描述信息", "data": null}
```

---

## 开发顺序（自己写，Claude Code 辅助）

### 第一阶段：基础设施（30 min）
1. `core/config.py` — 所有配置项集中管理
2. `core/database.py` — 表定义 + 异步引擎 + lifespan
3. `core/embedding.py` — Embedding HTTP 客户端
4. `core/splitter.py` — 文档分割器（先做 TXT/MD，再做 PDF）

### 第二阶段：RAG 引擎（45 min）
5. `rag/vector_store.py` — Chroma 封装
6. `rag/retriever.py` — 检索 + Query Rewrite
7. `rag/generator.py` — LLM 生成 + SSE
8. `rag/pipeline.py` — 串联所有模块

### 第三阶段：API 层（45 min）
9. `api/documents.py` — 文档上传 CRUD
10. `api/conversations.py` — 对话管理（可复用 Day 06）
11. `api/qa.py` — 问答端点
12. `api/router.py` — 路由汇总

### 第四阶段：组装 + 前端（30 min）
13. `main.py` — 应用入口 + 中间件 + 异常处理
14. `web/` — 简单上传 + 问答 UI

---

## 验证清单

- [ ] `python main.py` 或 `uvicorn main:app --reload` 正常启动
- [ ] `/docs` Swagger 页面能看到所有路由
- [ ] 上传一个 PDF，返回 `{doc_id, chunk_count}` 且 chunk_count > 0
- [ ] `/api/v1/documents/` 列出已上传文档
- [ ] POST `/api/v1/qa/` 传入问题，返回答案 + 引用来源
- [ ] POST `/api/v1/qa/stream` SSE 流式逐字输出
- [ ] 上传第二个文档后，问答能跨文档检索
- [ ] 删除文档后，相关问题不再引用该文档
- [ ] 问"文档里没有的内容"，模型回复"资料中未找到"
- [ ] 多轮对话能记住上下文
- [ ] 所有接口返回统一 `{success, data, error}` 格式

---

## 本周总结

```
☑ Embedding 原理：文本→向量→相似度计算
☑ 文档分割策略：chunk_size / overlap / 四种分法
☑ 向量数据库：Chroma 的 upsert + query + metadata filter
☑ RAG 完整流水线：Load→Split→Embed→Store→Retrieve→Generate
☑ 检索优化：Query Rewriting / Re-ranking / Multi-Query / HyDE
☑ 高级 RAG：Self-RAG / Agentic RAG / Corrective RAG
☑ 副线：自定义 Slash Command 封装工作流
☑ 产出：一个可用的文档问答系统（FastAPI + SSE + 多文档）

RAG = 把一个好问题 + 一段精准的资料 + 一个好 Prompt 交给 LLM
检索质量决定了 RAG 的上限，生成质量决定了用户体验
```

### 项目代码行数（填写）：________

### 最大的收获：
________________________________

### 踩过最大的坑 & 怎么解决的：
________________________________

### 还没搞懂的（诚实写）：
________________________________

### 这个项目接下来我想加的功能：
________________________________

### 用 Claude Code 的感觉（和不用有什么区别）：
________________________________

---

## 副线笔记

```
这一周你的 Claude Code 应该用得更顺手了：
- 你创建了几个自定义 Slash Command？
- 你有没有感到某些重复操作可以用 Hook 自动化？
- 列出 3 个你现在觉得 "要是 Claude Code 能自动做 XXX 就好了" 的场景：
  1.
  2.
  3.

下周 Week 05 会教你写 Hook，把这些愿望实现。
```

---

## 下周预告

Week 05 进入向量数据库专题：深入 Milvus/Qdrant、大规模向量检索优化、结合 Claude Code Hooks 自动化开发工作流。
