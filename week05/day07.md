# Day 07 — 综合实战：徒步路线知识库语义搜索

## 今日目标

把前六天所有模块组装成一个完整的**徒步路线知识库语义搜索系统**——FastAPI 后端 + 向量数据库 + 多维过滤检索 + 相似路线推荐 + Web UI。

**今天全程 Claude Code 结对编程。** 你做架构决策，Claude Code 出第一版代码，你审查修改。

---

## 项目定位

```
一个徒步路线智能检索后端，支持：
- 导入徒步路线数据（名称 / 地区 / 难度 / 海拔 / 里程 / 时长 / 描述）
- 语义搜索：用自然语言找路线（"有海的高海拔短线" → 匹配描述语义）
- 多维过滤：按地区 / 难度 / 海拔范围 / 里程范围过滤（metadata where）
- 相似路线推荐：给定一条路线，向量检索找最相似的 N 条
- SSE 流式推荐：逐条流式返回推荐结果
```

> **和 Week 04 文档问答的区别：** Week 04 是"文档 chunks → 问答"，本周是"结构化路线数据 → 检索推荐"。重点在向量库的多维过滤、相似检索、选型落地，而不是 RAG 生成。

---

## 项目结构

```
week05/day07/
├── main.py              # FastAPI 入口 + lifespan + CORS + 中间件
├── core/
│   ├── __init__.py
│   ├── config.py        # 配置（Embedding / 向量库 / 检索参数）
│   ├── database.py      # SQLAlchemy async 路线元数据表 + get_db
│   ├── embedding.py     # Embedding 客户端（复用 Week 04）
│   └── vector_store.py  # 向量库封装（复用 Day 03 AdvancedVectorStore）
├── rag/
│   ├── __init__.py
│   ├── indexer.py       # 路线数据 → Embedding → 入库
│   ├── retriever.py     # 语义检索 + 多维过滤 + 相似推荐
│   └── recommender.py   # 相似路线推荐 + SSE 流式
├── api/
│   ├── __init__.py
│   ├── router.py        # 路由汇总，注入 /api/v1 前缀
│   ├── routes.py        # 路线导入 / 列表 / 详情
│   ├── search.py        # 语义检索（含多维过滤）
│   └── recommend.py     # 相似推荐（普通 + SSE 流式）
├── schemas/
│   ├── __init__.py
│   ├── response.py      # 统一 APIResponse
│   └── models.py        # Pydantic 路线 / 检索请求模型
├── data/
│   └── routes_seed.json # 种子路线数据（20+ 条徒步路线）
├── web/
│   ├── index.html       # 检索 + 推荐 UI
│   ├── style.css
│   └── script.js
└── README.md
```

---

## 路线数据模型

### `schemas/models.py`

```python
from pydantic import BaseModel, Field
from typing import Literal


class RouteBase(BaseModel):
    """徒步路线基础模型"""
    name: str = Field(..., description="路线名称，如'四姑娘山二峰'")
    region: str = Field(..., description="地区，如'川西'、'滇西北'")
    difficulty: Literal["休闲", "进阶", "硬核"] = Field(..., description="难度")
    altitude: int = Field(..., ge=0, description="最高海拔（米）")
    distance: float = Field(..., ge=0, description="总里程（公里）")
    duration: str = Field(..., description="建议时长，如'2天'")
    description: str = Field(..., description="路线描述，用于语义检索")


class RouteCreate(RouteBase):
    """导入路线"""
    pass


class RouteOut(RouteBase):
    """返回路线（含 id 和相似度）"""
    id: str
    similarity: float | None = None


class SearchRequest(BaseModel):
    """语义检索请求"""
    query: str = Field(..., description="自然语言查询，如'有海的高海拔短线'")
    top_k: int = Field(5, ge=1, le=50)
    # 多维过滤
    region: str | None = Field(None, description="按地区过滤")
    difficulty: Literal["休闲", "进阶", "硬核"] | None = None
    altitude_min: int | None = Field(None, ge=0)
    altitude_max: int | None = Field(None, ge=0)
    distance_max: float | None = Field(None, ge=0, description="里程上限（公里）")


class RecommendRequest(BaseModel):
    """相似路线推荐请求"""
    route_id: str = Field(..., description="基准路线 id")
    top_k: int = Field(5, ge=1, le=50)
```

### 种子数据示例 `data/routes_seed.json`

```json
[
  {
    "name": "四姑娘山二峰",
    "region": "川西",
    "difficulty": "硬核",
    "altitude": 5276,
    "distance": 28,
    "duration": "3天",
    "description": "海拔5000米以上的雪山攀登，需要高海拔经验和专业技术，风景壮丽"
  },
  {
    "name": "雨崩徒步",
    "region": "滇西北",
    "difficulty": "进阶",
    "altitude": 3900,
    "distance": 60,
    "duration": "5天",
    "description": "梅里雪山脚下的世外桃源，神瀑冰湖，藏传佛教圣地，中高海拔长线"
  },
  {
    "name": "虎跳峡高路",
    "region": "滇西北",
    "difficulty": "进阶",
    "altitude": 2700,
    "distance": 22,
    "duration": "2天",
    "description": "金沙江峡谷悬崖栈道，世界级峡谷风光，低海拔但险峻的中长线"
  }
]
```

---

## 核心模块设计

### 1. `core/config.py`

```python
import os

# Embedding
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text:latest")

# 向量库（默认 Chroma；可切换 Milvus / Qdrant）
VECTOR_DB = os.getenv("VECTOR_DB", "chroma")  # chroma | milvus | qdrant
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "vector_db")
COLLECTION_NAME = "hiking_routes"

# 检索
SEARCH_TOP_K = int(os.getenv("SEARCH_TOP_K", "10"))
MIN_SIMILARITY = float(os.getenv("MIN_SIMILARITY", "0.2"))

# 数据库（路线元数据）
DATABASE_URL = "sqlite+aiosqlite:///./routes.db"
```

> **选型落地：** 这里用环境变量 `VECTOR_DB` 切换后端——这正是 Day 05 讲的"用抽象层降低迁移成本"。学习阶段用 Chroma，想试 Milvus 改个环境变量即可。

### 2. `core/vector_store.py` — 向量库抽象

复用 Day 03 的 `AdvancedVectorStore`，但补一个"按 id 取向量"的方法（相似推荐要用）：

```python
class RouteVectorStore:
    """路线向量库：在 AdvancedVectorStore 基础上加 get_vector"""

    def get_vector(self, route_id: str) -> list[float] | None:
        """按 id 取出一条路线的向量（用于相似推荐）"""
        result = self.collection.get(ids=[route_id], include=["embeddings"])
        embs = result.get("embeddings") or []
        return embs[0] if embs else None
```

### 3. `rag/indexer.py` — 索引器

```python
class RouteIndexer:
    async def index_route(self, route: dict) -> str:
        """路线 → 拼接检索文本 → Embedding → 入库 → 返回 route_id"""
        # 把结构化字段拼成一段语义文本
        doc = self._build_doc(route)
        vec = await embed_text(doc)
        route_id = f"route_{route['name']}"
        self.store.add_chunks(
            doc_id=route_id,
            chunks=[{"text": doc, "metadata": self._meta(route)}],
            embeddings=[vec],
        )
        return route_id

    def _build_doc(self, route: dict) -> str:
        """结构化字段 → 检索文本（决定语义检索质量）"""
        return (
            f"{route['name']}位于{route['region']}，"
            f"难度{route['difficulty']}，最高海拔{route['altitude']}米，"
            f"里程{route['distance']}公里，建议{route['duration']}。"
            f"{route['description']}"
        )
```

**关键设计：** `_build_doc` 决定语义检索质量。把结构化字段拼成自然语言，让 Embedding 模型能理解"高海拔短线"这类自然查询。

### 4. `rag/retriever.py` — 检索器

```python
class RouteRetriever:
    async def search(self, req: SearchRequest) -> list[dict]:
        """语义检索 + 多维过滤"""
        vec = await embed_text(req.query)

        # 把过滤条件翻译成 Chroma where
        where = self._build_where(req)

        results = self.store.query(
            query_embedding=vec,
            top_k=req.top_k,
            where=where,
            min_similarity=MIN_SIMILARITY,
        )
        return results

    def _build_where(self, req: SearchRequest) -> dict | None:
        """SearchRequest → Chroma where 子句（Day 03 学的元数据过滤）"""
        conditions = []
        if req.region:
            conditions.append({"region": req.region})
        if req.difficulty:
            conditions.append({"difficulty": req.difficulty})
        if req.altitude_min is not None:
            conditions.append({"altitude": {"$gte": req.altitude_min}})
        if req.altitude_max is not None:
            conditions.append({"altitude": {"$lte": req.altitude_max}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        # 多条件 AND
        return {"$and": conditions}
```

### 5. `rag/recommender.py` — 相似推荐 + SSE

```python
class RouteRecommender:
    async def recommend(self, route_id: str, top_k: int = 5) -> list[dict]:
        """相似路线推荐：取出基准路线向量 → 向量检索"""
        base_vec = self.store.get_vector(route_id)
        if base_vec is None:
            raise ValueError(f"路线 {route_id} 不存在")

        results = self.store.query(
            query_embedding=base_vec,
            top_k=top_k + 1,  # 多取一个，排除自己
        )
        # 排除基准路线本身
        return [r for r in results if r["id"] != route_id][:top_k]

    async def recommend_stream(self, route_id: str, top_k: int = 5):
        """SSE 流式推荐：逐条 yield"""
        results = await self.recommend(route_id, top_k)
        for r in results:
            yield f'data: {{"type":"route","data":{r}}}\n\n'
            await asyncio.sleep(0.1)  # 模拟流式节奏
        yield 'data: {"type":"done"}\n\n'
```

---

## API 路由设计

```
# 路线管理
POST   /api/v1/routes/import      导入种子数据 / 单条路线
GET    /api/v1/routes/            路线列表（?region=&difficulty=）
GET    /api/v1/routes/{id}        路线详情

# 语义检索
POST   /api/v1/search/            语义检索（支持多维过滤）

# 相似推荐
POST   /api/v1/recommend/         相似路线推荐
POST   /api/v1/recommend/stream   流式推荐（SSE）

# 系统
GET    /health                    健康检查
```

---

## 统一响应格式

```json
// 成功
{"success": true, "data": {...}, "meta": {"total": 8}}

// 失败
{"success": false, "error": "路线不存在", "data": null}
```

---

## 检索请求/响应示例

```json
// 请求 POST /api/v1/search/
{
  "query": "有海的高海拔短线",
  "top_k": 5,
  "difficulty": "进阶",
  "altitude_min": 3000
}

// 响应
{
  "success": true,
  "data": {
    "query": "有海的高海拔短线",
    "results": [
      {
        "id": "route_雨崩徒步",
        "name": "雨崩徒步",
        "region": "滇西北",
        "difficulty": "进阶",
        "altitude": 3900,
        "distance": 60,
        "description": "梅里雪山脚下...冰湖...",
        "similarity": 0.78
      }
    ]
  },
  "meta": {"total": 1}
}
```

---

## 开发顺序（自己写，Claude Code 辅助）

### 第一阶段：基础设施（~30 min）
1. `core/config.py` — 配置集中
2. `core/database.py` — 路线元数据表 + 异步引擎
3. `core/embedding.py` — 复用 Week 04 的 Embedding 客户端
4. `core/vector_store.py` — 复用 Day 03 的 AdvancedVectorStore + get_vector
5. `schemas/response.py` + `schemas/models.py` — 响应与数据模型
6. `data/routes_seed.json` — 准备 20+ 条种子路线

### 第二阶段：检索引擎（~45 min）
7. `rag/indexer.py` — 路线索引（`_build_doc` 是重点）
8. `rag/retriever.py` — 语义检索 + `_build_where` 多维过滤
9. `rag/recommender.py` — 相似推荐 + SSE 流式

### 第三阶段：API 层（~40 min）
10. `api/routes.py` — 路线导入 / 列表 / 详情
11. `api/search.py` — 语义检索端点
12. `api/recommend.py` — 推荐端点（普通 + SSE）
13. `api/router.py` — 路由汇总

### 第四阶段：组装（~30 min）
14. `main.py` — FastAPI 入口 + 路由注册 + 中间件 + 异常处理
15. `web/` — 检索 + 推荐 UI

---

## main.py 骨架

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uuid, time, os

from core.database import init_db
from core.vector_store import RouteVectorStore
from api.router import register_routers


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # 启动时初始化向量库
    app.state.vector_store = RouteVectorStore()
    yield


app = FastAPI(
    title="徒步路线知识库语义搜索",
    version="1.0.0",
    description="Week 05 综合实战 — 语义检索 + 多维过滤 + 相似推荐",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def trace_requests(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    response.headers["X-Request-ID"] = rid
    print(f"[{rid}] {request.method:6} {request.url.path:30} → {response.status_code} ({elapsed:.0f}ms)")
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[ERROR] {request.method} {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"success": False, "error": "服务器内部错误"})


register_routers(app)
app.mount("/static", StaticFiles(directory="web", html=True), name="static")


@app.get("/")
async def read_index():
    index_path = os.path.join("web", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "徒步路线知识库已启动"}


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
```

---

## Web UI 设计

`web/index.html` 最简布局：

```
┌──────────────────────────────────────────────┐
│  🥾 徒步路线知识库                            │
├────────────────────┬─────────────────────────┤
│  🔍 语义检索        │  📋 路线列表            │
│  [输入: 有海的高...] │  ┌─────────────────────┐│
│                    │  │ 雨崩徒步  滇西北 进阶││
│  过滤:              │  │ 海拔3900  60km  5天  ││
│  地区[川西▾]        │  │ 相似度 0.78          ││
│  难度[进阶▾]        │  │ [相似推荐]           ││
│  海拔[3000-]        │  ├─────────────────────┤│
│  [搜索]             │  │ 四姑娘山 川西 硬核   ││
│                    │  │ ...                  ││
│  相似推荐(流式)      │  └─────────────────────┘│
│  选中一条 → [推荐]   │                         │
└────────────────────┴─────────────────────────┘
```

前端交互要点：
- 搜索支持自然语言 + 多维过滤组合
- 结果卡片显示相似度，点击"相似推荐"触发 SSE 流式逐条加载
- 导入按钮一键灌入种子数据

---

## 验证清单

- [ ] `uvicorn main:app --reload` 正常启动
- [ ] `/docs` Swagger 能看到所有路由
- [ ] `POST /api/v1/routes/import` 导入种子数据 → 返回导入数量
- [ ] `GET /api/v1/routes/` 列出所有路线
- [ ] `POST /api/v1/search/` 查"有海的高海拔短线" → 返回语义匹配结果
- [ ] 加上 `region=川西` 过滤后，结果只剩川西路线
- [ ] 加上 `altitude_min=4000` 后，结果都是 4000 米以上
- [ ] `POST /api/v1/recommend/` 传入一条路线 id → 返回相似路线（不含自己）
- [ ] `POST /api/v1/recommend/stream` SSE 逐条流式输出
- [ ] 查"完全不相关的内容" → 返回空或低相似度结果
- [ ] 所有接口返回统一 `{success, data, error}` 格式
- [ ] Web UI 搜索 + 推荐流程可用
- [ ] (加分) 把 `VECTOR_DB` 改成 milvus，重启后功能正常（验证抽象层）

---

## 本周总结

```
☑ 向量数据库原理：为什么暴力搜索慢，ANN 用精度换速度
☑ 三大索引算法：IVF（倒排）/ HNSW（分层图）/ PQ（量化）
☑ HNSW 深入：M / ef_construction / ef_search 参数调优
☑ Chroma 深入：多集合 / 元数据过滤 / 距离函数 / 批量 / 持久化
☑ Milvus 生产级：存算分离架构 / Docker 部署 / 索引选型 / 分区
☑ 四库横向对比：Chroma / Milvus / Qdrant / Pinecone + 选型决策树
☑ 量化压缩：SQ / PQ / Binary 省内存 + 两阶段检索
☑ 副线：Claude Code Hooks 自动化 + CLAUDE.md 进阶知识库管理
☑ 产出：徒步路线知识库语义搜索（FastAPI + 向量库 + 多维过滤 + Web UI）

向量数据库 = 索引算法（快） + 距离度量（准） + 量化压缩（省） + 选型落地（稳）
懂了内部，你才知道为什么慢、为什么召回低、什么时候该换库。
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
- 你写了第一个 Hook 吗？它帮你自动化了什么？
- CLAUDE.md 从单文件升级到分层 + @ 引用后，上下文管理是否更省 token？
- 对比四库时，你让 Claude Code 帮你做了哪些选型分析？

列出 3 个本周最值得记住的向量数据库决策：
  1.
  2.
  3.

Week 06 进入 LangChain + LangGraph，你会用框架重写 Agent——
但记住：手写过 Agent Loop（Week 03）和向量库（本周）后，你用框架才不是黑盒。
```

---

## 技能覆盖（对照 Week 01 / Week 04 复习）

| 已学知识点 | Week 05 项目中的复用 |
|---------------|--------------------|
| Pydantic v2 + Field | RouteBase / SearchRequest / RecommendRequest 模型 |
| FastAPI 路由 + Query/Body | routes / search / recommend 路由 |
| Depends + 异常处理 + 中间件 | get_vector_store / 全局异常 / 请求追踪 |
| async/await + 异步数据库 | SQLAlchemy async + 异步 Embedding |
| SSE 流式 | recommend/stream 逐条流式推荐 |
| 统一响应格式 APIResponse | 所有接口统一 `{success, data, error}` |
| Week 04 Embedding / Chroma | 复用 Embedding 客户端 + AdvancedVectorStore |

Week 01 的 FastAPI 底座 + Week 04 的 RAG 经验，在 Week 05 项目中全部复现并升级——这就是"不做 Demo、做底座"的意义。

---

## 下周预告

Week 06 进入 LangChain + LangGraph：用框架重写 Agent Loop、用状态图编排多步推理。副线用 Claude Code 辅助调试 Agent 状态机。本周手写的向量库和 Agent 循环，将成为你理解框架内部的底座——用框架时不再是黑盒。
