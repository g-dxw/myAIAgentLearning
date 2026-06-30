# Day 07 — 综合实战：多步推理 Agent

## 今日目标

把前六天所有模块组装成一个完整的**多步推理 Agent**——用 LangGraph 编排"路线推荐 → 天气查询 → 装备清单 → 出行建议"的完整推理链，再服务化成 FastAPI 后端 + Web UI。

**今天全程 Claude Code 结对编程。** 你做架构决策，Claude Code 出第一版代码，你审查修改。

---

## 项目定位

```
一个徒步出行规划 Agent，输入"我想去川西 3 天的进阶路线"，
Agent 自主完成多步推理：
  1. 调用路线检索工具（复用 Week 05 向量库）→ 推荐 2-3 条路线
  2. 调用天气查询工具 → 查目标地区天气
  3. 调用装备生成工具 → 根据路线难度+天气生成装备清单
  4. 综合以上信息 → 给出出行建议
全程用 LangGraph 状态图编排，支持多轮对话（Checkpointer 记忆）和流式输出。
```

> **和 Week 05 的区别：** Week 05 是"单步检索"（一次查询返回结果）；本周是"多步推理"（Agent 自己决定查什么、查几步、怎么综合）。和 Week 03 的区别：Week 03 手写循环，本周用 LangGraph 图编排 + 持久化 + 流式。

---

## 项目结构

```
week06/day07/
├── main.py              # FastAPI 入口 + lifespan + CORS + 中间件
├── core/
│   ├── __init__.py
│   ├── config.py        # 配置（模型 / Embedding / 向量库 / Checkpointer）
│   ├── database.py      # SQLAlchemy async（路线元数据，复用 Week 05）
│   ├── embedding.py     # Embedding 客户端（复用 Week 04/05）
│   └── vector_store.py  # 路线向量库（复用 Week 05 AdvancedVectorStore）
├── tools/
│   ├── __init__.py
│   ├── route_tools.py   # @tool 路线检索工具（调向量库）
│   ├── weather_tools.py # @tool 天气查询工具（mock 或调 API）
│   └── gear_tools.py    # @tool 装备生成工具
├── agent/
│   ├── __init__.py
│   ├── state.py         # Agent State 定义（TypedDict + reducer）
│   ├── graph.py         # LangGraph 状态图编排（本周核心）
│   └── nodes.py         # 图节点函数（agent / tools / summarize）
├── api/
│   ├── __init__.py
│   ├── router.py        # 路由汇总
│   └── chat.py          # 对话端点（普通 + SSE 流式）
├── schemas/
│   ├── __init__.py
│   ├── response.py      # 统一 APIResponse
│   └── models.py        # Pydantic 请求/响应模型
├── web/
│   ├── index.html       # 对话 UI
│   ├── style.css
│   └── script.js
└── README.md
```

---

## Agent State 设计

### `agent/state.py`

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages


class PlannerState(TypedDict):
    """多步推理 Agent 的状态。"""
    # 消息历史（用 add_messages reducer 自动追加）
    messages: Annotated[list, add_messages]
    # 推理过程中积累的中间结果
    recommended_routes: list[dict]   # 推荐的路线
    weather_info: dict | None        # 目标地区天气
    gear_list: list[str]             # 装备清单
    # 最终输出
    final_plan: str | None           # 出行建议
```

> **State 设计是 LangGraph 的灵魂。** 把推理过程的中间结果显式存进 State，而不是全塞进 messages——这样每个节点能精准读取上游结果，也便于 get_state 调试。

---

## 工具定义

### `tools/route_tools.py` — 复用 Week 05 向量库

```python
from langchain_core.tools import tool
from core.vector_store import RouteVectorStore
from core.embedding import embed_text

_store = RouteVectorStore()


@tool
def search_routes(query: str, top_k: int = 3) -> str:
    """根据自然语言查询推荐徒步路线。query 描述用户想要的路线特征，
    如'川西 3 天进阶路线'。返回匹配的路线名称、地区、难度、海拔、描述。"""
    vec = embed_text(query)
    results = _store.query(query_embedding=vec, top_k=top_k)
    if not results:
        return "未找到匹配路线"
    lines = []
    for r in results:
        m = r["metadata"]
        lines.append(
            f"- {m.get('name','?')}（{m.get('region','?')}，"
            f"{m.get('difficulty','?')}，海拔{m.get('altitude','?')}m）"
            f"相似度{r['similarity']:.2f}"
        )
    return "\n".join(lines)
```

### `tools/weather_tools.py`

```python
from langchain_core.tools import tool


@tool
def get_weather(region: str) -> str:
    """查询指定地区未来 3 天天气。region 为地区名，如'川西'、'滇西北'。"""
    # 实际可接天气 API，这里 mock
    mock = {
        "川西": "晴转多云，5~18°C，风力 3 级，夜间低温注意保暖",
        "滇西北": "多云有阵雨，8~20°C，高原天气多变，带雨具",
    }
    return mock.get(region, f"{region}：晴，10~22°C")
```

### `tools/gear_tools.py`

```python
from langchain_core.tools import tool


@tool
def generate_gear_list(difficulty: str, weather: str) -> str:
    """根据路线难度和天气生成装备清单。difficulty 为'休闲/进阶/硬核'，
    weather 为天气描述。返回建议携带的装备列表。"""
    base = ["登山鞋", "背包", "水壶", "头灯", "急救包", "防晒霜"]
    if difficulty == "硬核":
        base += ["冰爪", "安全带", "绳索", "头盔"]
    elif difficulty == "进阶":
        base += ["登山杖", "护膝"]
    if "雨" in weather:
        base += ["雨衣", "防水袋"]
    if "低温" in weather or "保暖" in weather:
        base += ["羽绒服", "抓绒", "保温杯"]
    return "建议装备：" + "、".join(base)
```

---

## LangGraph 图编排（本周核心）

### `agent/graph.py`

```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.tools import tool

from agent.state import PlannerState
from agent.nodes import call_model, summarize
from tools.route_tools import search_routes
from tools.weather_tools import get_weather
from tools.gear_tools import generate_gear_list

# 所有工具
TOOLS = [search_routes, get_weather, generate_gear_list]
TOOL_MAP = {t.name: t for t in TOOLS}


def build_graph(model):
    """构建多步推理 Agent 图。

    结构：
        START → agent ⇄ tools（循环）→ summarize → END
                     ↑_______|
    """
    # 给模型绑定工具
    model_with_tools = model.bind_tools(TOOLS)

    graph = StateGraph(PlannerState)

    # 节点
    graph.add_node("agent", lambda state: call_model(state, model_with_tools))
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_node("summarize", lambda state: summarize(state, model))

    # 边
    graph.add_edge(START, "agent")

    # agent → 条件分支：有 tool_calls 去 tools，没有去 summarize
    graph.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", "__end__": "summarize"},
    )

    # tools → agent（循环：工具结果回传后继续推理）
    graph.add_edge("tools", "agent")

    # summarize → END（汇总成最终出行建议）
    graph.add_edge("summarize", END)

    # 编译，带 checkpointer 实现多轮记忆
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)
```

### `agent/nodes.py`

```python
def call_model(state, model_with_tools):
    """agent 节点：调模型决定下一步（调用工具 or 给出结论）。"""
    response = model_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def summarize(state, model):
    """summarize 节点：模型不再调用工具后，汇总成出行建议。"""
    summary_prompt = (
        "根据以上对话中检索到的路线、天气和装备信息，"
        "为用户生成一份完整的出行建议，包含：推荐路线、天气提醒、装备清单、注意事项。"
    )
    messages = state["messages"] + [{"role": "user", "content": summary_prompt}]
    response = model.invoke(messages)
    return {"messages": [response], "final_plan": response.content}
```

**图结构（ASCII）：**

```
            ┌─────────────────────────────┐
            ▼                             │
START → [agent] ──tool_calls──→ [tools] ──┘
            │
          无 tool_calls
            ▼
       [summarize] → END
```

---

## API 路由设计

```
# 对话
POST   /api/v1/chat/            普通对话（阻塞，等 Agent 跑完）
POST   /api/v1/chat/stream      流式对话（SSE，逐 token + 工具调用事件）

# 会话管理
GET    /api/v1/chat/{thread_id}/history   获取某会话历史（读 Checkpointer 状态）

# 系统
GET    /health                    健康检查
```

---

## 统一响应格式

```json
// 成功
{"success": true, "data": {...}, "meta": {"thread_id": "user-001"}}

// 失败
{"success": false, "error": "模型调用失败", "data": null}
```

---

## 对话请求/响应示例

```json
// 请求 POST /api/v1/chat/
{
  "message": "我想去川西 3 天的进阶路线，帮我规划一下",
  "thread_id": "user-001"
}

// 响应
{
  "success": true,
  "data": {
    "answer": "为您推荐四姑娘山二峰（川西，硬核，海拔5276m）...",
    "tool_calls": [
      {"name": "search_routes", "args": {"query": "川西 3 天进阶"}},
      {"name": "get_weather", "args": {"region": "川西"}},
      {"name": "generate_gear_list", "args": {"difficulty": "进阶", "weather": "晴转多云 5~18°C"}}
    ],
    "final_plan": "## 出行建议\n### 推荐路线\n四姑娘山二峰...\n### 天气提醒\n...\n### 装备清单\n登山鞋、背包...\n### 注意事项\n..."
  },
  "meta": {"thread_id": "user-001", "steps": 6}
}
```

---

## SSE 流式事件格式

```
data: {"type":"tool_start","name":"search_routes","args":{"query":"川西 3 天进阶"}}

data: {"type":"tool_end","name":"search_routes","result":"- 四姑娘山二峰（川西...)"}

data: {"type":"text","content":"根据"}

data: {"type":"text","content":"查询结果"}

...

data: {"type":"done","final_plan":"..."}
```

---

## 开发顺序（自己写，Claude Code 辅助）

### 第一阶段：工具层（~30 min）
1. `tools/route_tools.py` — 复用 Week 05 向量库封装成 @tool
2. `tools/weather_tools.py` — 天气查询（可先 mock）
3. `tools/gear_tools.py` — 装备生成
4. 验证每个工具单独可调

### 第二阶段：Agent 图（~50 min，本周核心）
5. `agent/state.py` — 设计 PlannerState
6. `agent/nodes.py` — agent / summarize 节点
7. `agent/graph.py` — 编排图（agent⇄tools 循环 + summarize）
8. 本地 `app.invoke()` 跑通完整推理链
9. 用 `get_state` + `draw_mermaid` 调试

### 第三阶段：API 层（~40 min）
10. `api/chat.py` — 普通对话端点（invoke + 读 final_plan）
11. `api/chat.py` — SSE 流式端点（astream + stream_mode="updates"）
12. `api/router.py` — 路由汇总

### 第四阶段：组装（~30 min）
13. `main.py` — FastAPI 入口 + 路由注册 + 中间件 + 异常处理
14. `web/` — 对话 UI（显示工具调用过程 + 最终建议）

---

## main.py 骨架

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from langchain.chat_models import init_chat_model
import uuid, time, os

from agent.graph import build_graph
from api.router import register_routers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化模型 + 构建 Agent 图（应用级单例）
    model = init_chat_model("ollama:qwen2.5:1.5b")
    app.state.graph = build_graph(model)
    yield


app = FastAPI(
    title="徒步出行规划 Agent",
    version="1.0.0",
    description="Week 06 综合实战 — LangGraph 多步推理 Agent",
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
    return {"message": "徒步出行规划 Agent 已启动"}


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
```

---

## 对话端点示例 `api/chat.py`

```python
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import json, asyncio

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("/")
async def chat(req: ChatRequest, request: Request):
    """普通对话：阻塞等待 Agent 跑完，返回最终建议。"""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": req.thread_id}, "recursion_limit": 30}

    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": req.message}]},
        config=config,
    )

    return {
        "success": True,
        "data": {
            "answer": result["messages"][-1].content,
            "final_plan": result.get("final_plan"),
        },
        "meta": {"thread_id": req.thread_id},
    }


@router.post("/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """SSE 流式：逐 token 输出 + 工具调用事件。"""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": req.thread_id}, "recursion_limit": 30}

    async def event_stream():
        async for event in graph.astream(
            {"messages": [{"role": "user", "content": req.message}]},
            config=config,
            stream_mode="updates",
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        yield 'data: {"type":"done"}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

---

## Web UI 设计

`web/index.html` 最简布局：

```
┌──────────────────────────────────────────────┐
│  🥾 徒步出行规划 Agent                        │
├──────────────────────────────────────────────┤
│  💬 对话区                                    │
│  ┌────────────────────────────────────────┐  │
│  │ 用户：我想去川西 3 天的进阶路线        │  │
│  │                                        │  │
│  │ 🔧 调用工具: search_routes("川西...")   │  │
│  │ 🔧 调用工具: get_weather("川西")        │  │
│  │ 🔧 调用工具: generate_gear_list(...)    │  │
│  │                                        │  │
│  │ 🤖 Agent：为您规划如下：                │  │
│  │    ## 推荐路线                          │  │
│  │    四姑娘山二峰...                      │  │
│  │    ## 天气提醒                          │  │
│  │    ...                                 │  │
│  │    ## 装备清单                          │  │
│  │    登山鞋、背包...                      │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  [输入消息...]                    [发送]      │
│  会话: user-001   ☑ 显示工具调用             │
└──────────────────────────────────────────────┘
```

前端交互要点：
- 流式模式下实时显示工具调用过程（工具名 + 参数 + 结果）
- 最终建议用 Markdown 渲染（路线/天气/装备/注意事项分段）
- 同 thread_id 支持多轮对话（Agent 记得上文）

---

## 验证清单

- [ ] `uvicorn main:app --reload` 正常启动
- [ ] `/docs` Swagger 能看到所有路由
- [ ] `POST /api/v1/chat/` 问"川西 3 天进阶路线" → Agent 依次调用 3 个工具 → 返回出行建议
- [ ] 响应中包含路线推荐 + 天气 + 装备清单
- [ ] `POST /api/v1/chat/stream` SSE 流式，能看到工具调用事件逐个出现
- [ ] 用同一个 thread_id 追问"那条路线需要什么装备" → Agent 记得上文（Checkpointer 生效）
- [ ] 换一个 thread_id → Agent 不记得上文（会话隔离）
- [ ] 问完全不相关的问题（如"你好"）→ Agent 不乱调工具
- [ ] `recursion_limit` 触发时给出友好错误，不堆栈
- [ ] 所有接口返回统一 `{success, data, error}` 格式
- [ ] Web UI 对话 + 工具调用过程 + 最终建议展示正常
- [ ] (加分) 用 `draw_mermaid()` 导出图结构，确认和设计一致

---

## 本周总结

```
☑ LangChain 基础：init_chat_model / ChatPromptTemplate / LCEL 管道链 / Output Parser
☑ LangChain 工具调用：@tool 装饰器 / bind_tools / ToolMessage 完整循环
☑ LangGraph 入门：StateGraph / State(TypedDict+reducer) / Node / Edge / START/END
☑ LangGraph 进阶：条件边路由 / 循环实现 Agent Loop / create_react_agent 高层 API
☑ 持久化与 HITL：Checkpointer 状态存档 / thread_id 多轮记忆 / interrupt 人机交互
☑ 高级模式：子图 / 并行 fan-out / stream 流式 / Mermaid 可视化
☑ 副线：Claude Code 审查 LCEL、画状态机草图、调试卡死节点
☑ 产出：多步推理 Agent（LangGraph 图编排 + 工具 + 持久化 + FastAPI + Web UI）

框架 = 把手写的 while True 变成显式的图，把手动 messages 管理交给 State，
把重启即丢交给 Checkpointer。手写过，所以用框架不是黑盒。
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
本周你用框架重写了 Agent，对比 Week 03 的手写版：
- LangChain 把 50 行手写压成 10 行，底层逻辑没变
- LangGraph 把 while True 变成显式图，可可视化可持久化
- Checkpointer 让 Agent 有了"记忆"，interrupt 让 Agent 有了"刹车"

列出 3 个本周最值得记住的 LangGraph 设计：
  1. State + reducer：节点返回 partial state，reducer 决定怎么合并
  2. 条件边 + 循环边：图能表达任何控制流，包括 Agent Loop
  3. Checkpointer + thread_id：持久化和多轮记忆的基石

Week 07 进入多 Agent 协作：多个 Agent 怎么分工、怎么通信、怎么避免死锁。
本周的单 Agent 图，将成为多 Agent 系统的子图。
```

---

## 技能覆盖（对照 Week 01 / Week 03 / Week 05 复习）

| 已学知识点 | Week 06 项目中的复用 |
|---------------|--------------------|
| Pydantic v2 + Field | PlannerState / ChatRequest 模型 |
| FastAPI 路由 + Query/Body | chat / stream / history 路由 |
| Depends + 异常处理 + 中间件 | app.state.graph 单例 / 全局异常 |
| async/await | graph.ainvoke / astream 异步 |
| SSE 流式 | chat/stream 用 astream + stream_mode |
| 统一响应格式 APIResponse | 所有接口统一 `{success, data, error}` |
| Week 03 Function Calling / Agent Loop | 换成 bind_tools + LangGraph 图循环 |
| Week 05 向量库检索 | 作为 search_routes 工具被 Agent 调用 |

Week 01 的 FastAPI 底座 + Week 03 的 Agent 手写经验 + Week 05 的向量库能力，在 Week 06 项目中全部复现并升级——这就是"不做 Demo、做底座"的意义。

---

## 下周预告

Week 07 进入多 Agent 协作：多个 Agent 分工（规划者/执行者/审查者）、Agent 间通信、避免死锁与循环。本周的单 Agent 图将成为多 Agent 系统的子图，LangGraph 的子图与并行能力将大放异彩。副线对比 Claude Code / Cursor / Aider 三个工具，建立"什么时候用哪个"的判断力。
