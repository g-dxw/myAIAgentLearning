# Day 07 — 综合实战：文档问答系统

## 今日目标

把前六天所有模块组装成一个完整的**文档问答系统**——FastAPI 后端 + RAG 引擎 + SSE 流式 + Web UI。

**今天全程 Claude Code 结对编程。** 你做架构决策，Claude Code 出第一版代码，你审查修改。

---

## 项目定位

```
一个文档智能问答后端，支持：
- 上传 PDF / Markdown / TXT → 自动分割 → Embedding → 入库
- 单轮问答：提问 → 检索 top_k → 拼接 Prompt → 生成答案 + 引用
- SSE 流式问答：逐字返回 + 末尾追加来源引用
- 多文档检索：可同时对多份文档提问
- 对话管理：多轮对话 + 问题重写 + 历史消息
```

---

## 项目结构

```
week04/day07/
├── main.py              # FastAPI 应用入口 + lifespan + CORS + 中间件
├── core/
│   ├── __init__.py
│   ├── config.py        # 全局配置（LLM/Embedding/Chroma/分割参数）
│   ├── database.py      # SQLAlchemy async 表定义 + get_db 依赖
│   ├── embedding.py     # Embedding 客户端（调 Ollama / OpenAI）
│   └── splitter.py      # 文档分割器（递归字符分割 + PDF 加载）
├── rag/
│   ├── __init__.py
│   ├── vector_store.py  # Chroma 操作封装（init / upsert / query / delete）
│   ├── retriever.py     # 检索器（语义检索 + Query Rewrite）
│   ├── generator.py     # LLM 生成器（非流式 + SSE 流式）
│   └── pipeline.py      # RAG Pipeline 主入口（index / query / stream）
├── api/
│   ├── __init__.py
│   ├── router.py        # 汇总所有子路由，注入 /api/v1 前缀
│   ├── documents.py     # 文档上传 / 列表 / 详情 / 删除
│   ├── conversations.py # 对话管理（创建 / 列表 / 查消息 / 删除）
│   └── qa.py            # 问答接口（普通 + SSE 流式）
├── schemas/
│   ├── __init__.py
│   ├── response.py      # 统一 APIResponse
│   └── models.py        # Pydantic 请求/响应模型
├── web/
│   ├── index.html       # 上传 + 对话 UI
│   ├── style.css
│   └── script.js
└── uploads/             # 上传文件存储目录
```

---

## 核心模块设计

### 1. `core/config.py`

```python
import os

# LLM
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:1.5b")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))

# Embedding
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text:latest")

# Chroma
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "chroma_db")

# 分割
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))

# 检索
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))

# 上传
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".md", ".txt", ".html"}

# 数据库
DATABASE_URL = "sqlite+aiosqlite:///./rag_agent.db"
```

### 2. `core/database.py` — 数据表

三张表：

```
documents               conversations         messages
├── id                  ├── id                ├── id
├── filename            ├── title             ├── conversation_id (FK)
├── saved_as            ├── created_at        ├── role
├── file_type                                 ├── content
├── size_bytes                                ├── sources (JSON)
├── chunk_count                               └── created_at
└── created_at
```

### 3. `rag/pipeline.py` — 主入口

```python
class RAGPipeline:
    async def index_document(self, file_path, filename, file_type) -> dict:
        """索引文档 → 返回 {doc_id, chunk_count}"""

    async def query(self, question, conv_id=None) -> dict:
        """非流式问答 → 返回 {answer, sources, usage}"""

    async def query_stream(self, question, conv_id=None):
        """SSE 流式问答 → 生成器 yield data: {...}"""
```

### 4. `rag/retriever.py` — 检索器

```python
class Retriever:
    async def retrieve(self, question, top_k=5) -> list[dict]:
        """检索：Embedding → VectorStore.query"""

    async def rewrite_query(self, question, history=None) -> str:
        """Query Rewriting：补全指代"""
```

### 5. `rag/generator.py` — 生成器

```python
class Generator:
    def build_prompt(self, question, contexts) -> str:
        """构建 RAG Prompt"""

    async def generate(self, question, contexts) -> dict:
        """非流式生成 → {answer, sources, usage}"""

    async def generate_stream(self, question, contexts):
        """SSE 流式生成 → 逐 token yield"""
```

---

## API 路由设计

```
# 文档管理
POST   /api/v1/documents/          上传文档（multipart/form-data）
GET    /api/v1/documents/          文档列表（?page=1&page_size=20）
GET    /api/v1/documents/{id}      文档详情
DELETE /api/v1/documents/{id}      删除文档（同时删向量库数据）

# 对话管理
POST   /api/v1/conversations/         创建对话
GET    /api/v1/conversations/         对话列表
GET    /api/v1/conversations/{id}    对话详情
GET    /api/v1/conversations/{id}/messages  消息列表
DELETE /api/v1/conversations/{id}    删除对话

# 问答
POST   /api/v1/qa/                非流式问答
POST   /api/v1/qa/stream          流式问答（SSE）

# 系统
GET    /health                    健康检查
```

---

## 统一响应格式

```json
// 成功
{"success": true, "data": {...}, "meta": {"page": 1, "total": 10}}

// 失败
{"success": false, "error": "描述", "data": null}
```

---

## 问答请求/响应格式

```json
// 请求 POST /api/v1/qa/
{
  "question": "RAG 的 chunk_size 应该设多大？",
  "conversation_id": 1,   // 可选：关联对话
  "top_k": 5              // 可选：检索数量
}

// 响应
{
  "success": true,
  "data": {
    "answer": "建议 chunk_size 设为 500-800 字符...",
    "sources": [
      {"source": "rag_guide.pdf", "page": "3", "similarity": 0.89}
    ],
    "usage": {"input_tokens": 1200, "output_tokens": 300}
  }
}
```

---

## SSE 流式问答事件格式

```
data: {"type": "text", "content": "根据"}

data: {"type": "text", "content": "文档"}

data: {"type": "text", "content": "记录"}

...

data: {"type": "sources", "data": [{"source": "a.pdf", ...}]}

data: {"type": "done"}
```

---

## 开发顺序（自己写，Claude Code 辅助）

### 第一阶段：基础设施（~30 min）
1. `core/config.py` — 所有配置集中
2. `core/database.py` — 表定义 + 异步引擎 + lifespan
3. `core/embedding.py` — Embedding HTTP 客户端
4. `core/splitter.py` — 文档分割器（复用 Day 02）
5. `schemas/response.py` — APIResponse
6. `schemas/models.py` — 请求/响应 Pydantic 模型

### 第二阶段：RAG 引擎（~45 min）
7. `rag/vector_store.py` — Chroma 封装（复用 Day 03）
8. `rag/retriever.py` — 检索 + Query Rewrite（复用 Day 05）
9. `rag/generator.py` — LLM 生成 + SSE（复用 Day 04）
10. `rag/pipeline.py` — Pipeline 主入口

### 第三阶段：API 层（~45 min）
11. `api/documents.py` — 文档上传 + CRUD
12. `api/conversations.py` — 对话管理
13. `api/qa.py` — 问答端点
14. `api/router.py` — 路由汇总

### 第四阶段：组装（~30 min）
15. `main.py` — FastAPI 应用入口 + 路由注册 + 中间件 + 异常处理
16. `web/` — 简单上传 + 问答 UI

---

## main.py 骨架

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uuid
import time
import os

from core.database import init_db
from api.router import register_routers


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="RAG 文档问答系统",
    version="1.0.0",
    description="Week 04 综合实战 — 上传文档，智能问答",
    lifespan=lifespan,
)

# CORS
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 请求追踪中间件
@app.middleware("http")
async def trace_requests(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    response.headers["X-Request-ID"] = rid
    print(f"[{rid}] {request.method:6} {request.url.path:30} → {response.status_code} ({elapsed:.0f}ms)")
    return response

# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[ERROR] {request.method} {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"success": False, "error": "服务器内部错误"})

# 路由
register_routers(app)

# 静态文件
app.mount("/static", StaticFiles(directory="web", html=True), name="static")


@app.get("/")
async def read_index():
    index_path = os.path.join("web", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "RAG 文档问答系统已启动"}


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
```

---

## Web UI 设计

`web/index.html` 最简布局：

```
┌──────────────────────────────────────────────┐
│  📄 RAG 文档问答系统                          │
├────────────────────┬─────────────────────────┤
│  📤 上传文档        │  💬 问答                 │
│  [选择文件] [上传]  │  ┌─────────────────────┐│
│                    │  │                     ││
│  📚 已上传文档      │  │  AI 回答区域         ││
│  ├─ doc1.pdf ✅    │  │                     ││
│  ├─ doc2.md  ✅    │  │  (含来源引用)         ││
│  └─ 共 2 份文档    │  └─────────────────────┘│
│                    │                         │
│                    │  [输入问题...]   [发送]  │
│                    │  ☑ 流式输出              │
└────────────────────┴─────────────────────────┘
```

前端交互要点：
- 上传文档后刷新文档列表
- 问答支持普通模式和 SSE 流式模式切换
- 流式模式下答案逐字显示
- 答案下方显示引用来源

---

## 验证清单

- [ ] `uvicorn main:app --reload` 正常启动
- [ ] `/docs` Swagger 页面能看到所有路由
- [ ] 上传一个 PDF → 返回 `{success: true, doc_id, chunk_count > 0}`
- [ ] `GET /api/v1/documents/` 列出已上传文档
- [ ] `POST /api/v1/qa/` 传入问题 → 返回 `{answer, sources, usage}`
- [ ] 答案中包含来源引用（文件名 + 页码）
- [ ] `POST /api/v1/qa/stream` SSE 逐字输出
- [ ] 上传第二个文档后，问答能跨文档检索
- [ ] `DELETE /api/v1/documents/{id}` 后，相关问题不再引用该文档
- [ ] 问"文档中没有的内容" → "抱歉，资料中未找到..."
- [ ] 多轮对话：第二轮的指代（"它"、"这个"）能被正确改写
- [ ] 所有接口返回统一 `{success, data, error}` 格式
- [ ] Web UI 上传文档 → 问答流程可用

---

## 本周总结

```
☑ Embedding 原理：文本→向量→相似度计算
☑ 文档分割策略：chunk_size / overlap / 递归分割
☑ 向量数据库：Chroma upsert / query / delete / metadata filter
☑ RAG 流水线：Load→Split→Embed→Store→Retrieve→Generate
☑ 检索优化：Query Rewriting / Re-ranking / Multi-Query / HyDE
☑ 高级 RAG：Self-RAG / Agentic RAG / Corrective RAG
☑ 副线：自定义 Slash Command 封装工作流
☑ 产出：文档问答系统（FastAPI + Chroma + SSE + Web UI）

RAG = 好问题 + 精准资料 + 好 Prompt → 可靠答案
检索质量决定了 RAG 的上限，生成质量决定了用户体验。
```

### 项目代码行数（填）：________

### 最大的收获：
________________________________

### 踩过最大的坑 & 怎么解决的：
________________________________

### 还没搞懂的（诚实写）：
________________________________

### 这个项目接下来想加的功能：
________________________________

### 用 Claude Code 结对编程的体验：
________________________________

---

## 副线笔记

```
本周你的 Claude Code 应该用得更深了：
- 你创建了几个自定义 Slash Command？
- 有没有感到某些重复操作可以用 Hook 自动化？
- 列出 3 个你现在觉得 "要是 Claude Code 能自动做 XXX 就好了" 的场景：
  1.
  2.
  3.

Week 05 会教你写 Hook，把这些愿望实现。
```

---

## 技能覆盖（对照 Week 01 复习）

| Week 01 知识点 | Week 04 项目中的复用 |
|---------------|-------------------|
| Pydantic v2 + Field | Document / Message / ChatRequest 模型 |
| FastAPI 路由 + Path/Query/Body | documents / qa / conversations 路由 |
| Depends + 异常处理 + 中间件 | get_db / get_embedding_client / 统一异常 |
| async/await + 异步数据库 | SQLAlchemy async + Chroma + httpx |
| SSE 流式 + 文件上传 | qa/stream + documents upload |
| 统一响应格式 APIResponse | 所有接口统一 {success, data, error} |

Week 01 学的所有东西在 Week 04 项目中全部复现——这就是"不做 Demo、做底座"的意义。

---

## 下周预告

Week 05 进入向量数据库专题：深入 Milvus/Qdrant 的生产级特性、大规模向量检索优化、结合 Claude Code Hooks 自动化开发工作流。
