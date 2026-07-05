# Day 07 — 综合实战：多步推理 Agent（create_agent 版）

## 今日目标

把本周的 LangChain create_agent 高层 API、Checkpointer 持久化、Middleware 中间件、SSE 流式全部组装成一个完整的**多步推理 Agent**——路线推荐 → 天气查询 → 装备清单 → 出行建议，服务化成 FastAPI 后端 + Web UI。

**今天全程 Claude Code 结对编程。** 你做架构决策，Claude Code 出第一版代码，你审查修改。

---

## 项目定位

```
一个徒步出行规划 Agent，输入"我想去川西 3 天的进阶路线"，
Agent 自主完成多步推理：
  1. 调用路线检索工具（复用 Week 05 向量库）→ 推荐 2-3 条路线
  2. 调用天气查询工具 → 查目标地区天气
  3. 调用装备生成工具 → 根据路线难度 + 天气生成装备清单
  4. 综合以上信息 → 给出出行建议
全程用 create_agent 高层 API（底层基于 LangGraph），
支持多轮对话（Checkpointer 记忆）、中间件重试、SSE 流式输出。
```

> **和 Day 05 手写 LangGraph 图的区别：** Day 05 我们手写 StateGraph + add_node/add_edge + tools_condition，今天用 `create_agent` 一行封装以上所有步骤。create_agent 底层仍然是 LangGraph 图，只是把标准 ReAct 模式的样板代码收进了高层 API。**手写过图，所以用高层 API 不是黑盒。** 和 Day 03 的区别：Day 03 手写 while True Agent Loop，今天是框架封装 + Checkpointer 持久化 + 中间件。

---

## 项目结构

```
week06/day07/
├── main.py              # FastAPI 入口 + lifespan + CORS + 中间件
├── tools/
│   ├── __init__.py
│   ├── route_tools.py   # @tool 路线检索工具（调 Week 05 向量库）
│   ├── weather_tools.py # @tool 天气查询工具（mock 或调 API）
│   └── gear_tools.py    # @tool 装备生成工具（根据难度 + 天气）
├── agent/
│   ├── __init__.py
│   └── agent_factory.py # create_agent 配置和构建（本周核心）
├── api/
│   ├── __init__.py
│   └── chat.py          # 对话端点 + SSE 流式
├── schemas/
│   ├── __init__.py
│   ├── models.py        # Pydantic 模型（含 Context 模型）
│   └── response.py      # 统一 APIResponse
├── web/
│   ├── index.html       # 对话 UI
│   └── script.js
└── requirements.txt
```

---

## Agent 构建 — agent/agent_factory.py

这是今天**最核心**的文件。用 `create_agent` 高层 API 一行创建完整的多步推理 Agent。对比 Day 05 手写 StateGraph 的 ~50 行样板代码，`create_agent` 把它们全部封装了。

```python
"""agent/agent_factory.py — 用 create_agent 构建多步推理 Agent

2026 年 LangChain 推荐入口：一行创建完整 Agent（内置 LangGraph 工具循环）。
底层基于 LangGraph，自动编排 agent ↔ tools 的 ReAct 循环，支持
Checkpointer 持久化、Middleware 中间件、流式输出。
"""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.agents.middleware import (
    ModelRetryMiddleware,    # LLM 调用失败自动重试
    ToolRetryMiddleware,     # 工具调用失败自动重试
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import BaseModel, Field

from tools.route_tools import search_routes
from tools.weather_tools import get_weather
from tools.gear_tools import generate_gear_list


# ─── 工具清单 ───
TOOLS = [search_routes, get_weather, generate_gear_list]


# ─── 系统提示词：定义 Agent 的推理流程 ───
SYSTEM_PROMPT = """你是一个专业的徒步出行规划助手。

请严格按照以下推理流程回答用户的出行规划需求：

## 推理流程（必须按顺序执行）

### 步骤 1：查路线
调用 search_routes 工具，根据用户的目的地/天数/难度要求检索匹配的徒步路线。

### 步骤 2：查天气
根据检索到的路线所在地区，调用 get_weather 工具查询当地天气。

### 步骤 3：生成装备
根据路线难度和天气情况，调用 generate_gear_list 工具生成装备清单。

### 步骤 4：综合建议
综合以上三条信息，为用户生成完整的出行建议，包含：
- 推荐路线及理由
- 天气提醒（注意防雨/防寒/防晒等）
- 装备清单
- 安全注意事项

## 约束规则
- 每一步推理结果都要在前一步结果的基础上进行
- 如果用户的问题不涉及出行规划（如打招呼），直接回答即可，不要调用工具
- 如果检索不到路线，如实告知用户，不要编造数据
- 注意安全提示，尤其在硬核路线或恶劣天气时
"""


# ─── Context 模型：用于传入用户上下文信息 ───
class UserContext(BaseModel):
    """用户上下文模型，通过 context_schema 传入 create_agent。"""
    user_id: str = Field(description="用户唯一标识")
    experience_level: str | None = Field(
        default="休闲", description="用户徒步经验等级：休闲/进阶/硬核"
    )
    preferred_region: str | None = Field(
        default=None, description="用户偏好的徒步地区"
    )


def build_agent(model_name: str = "ollama:qwen2.5:1.5b"):
    """构建多步推理 Agent。

    create_agent 一行封装了以下所有操作：
    1. 实例化模型 + bind_tools 绑定工具
    2. 创建 ReAct 模式的 LangGraph 图（agent ↔ tools 循环）
    3. 挂载 Checkpointer（InMemorySaver）实现多轮记忆
    4. 注册 Middleware（重试机制）
    5. 挂载 context_schema 传入用户上下文

    Args:
        model_name: 模型标识，格式为 "provider:model_name"
                    如 "ollama:qwen2.5:1.5b" / "openai:gpt-4o" / "anthropic:claude-sonnet-4-6"

    Returns:
        编译好的 Agent（CompiledGraph 类型），支持 invoke / stream_events / ainvoke
    """
    # 1. 初始化模型（统一的模型抽象，切换供应商只改字符串）
    model = init_chat_model(model_name, temperature=0.7)

    # 2. Checkpointer：持久化会话状态，支持多轮记忆和 thread_id 隔离
    #    注意：2026 年最新导入路径是 langgraph.checkpoint.memory.InMemorySaver
    checkpointer = InMemorySaver()

    # 3. InMemoryStore：跨会话长期记忆（可选）
    #    用于存储用户偏好、历史路线收藏等跨 session 数据
    store = InMemoryStore()

    # 4. 中间件：横切关注点插件化，无需侵入节点代码
    middleware = [
        ModelRetryMiddleware(
            max_retries=3,             # LLM 调用失败最多重试 3 次
        ),
        ToolRetryMiddleware(
            max_retries=2,             # 工具调用失败最多重试 2 次
        ),
    ]

    # 5. create_agent 一行创建
    agent = create_agent(
        model=model,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        store=store,
        context_schema=UserContext,     # 可选的上下文模型
        middleware=middleware,
    )

    return agent
```

> **create_agent 底层做了什么？** 它内部自动创建了 LangGraph 的 `StateGraph`，添加了 `agent` 节点（LLM 调用）和 `tools` 节点（工具执行），用 `tools_condition` 条件边连接 agent → tools 循环，挂载了 Checkpointer。和 Day 05 你手写的 `build_graph` 函数做的事**完全一样**，只是封装成了一行。这就是"手写过，所以用框架不是黑盒"——你清楚这一行下面是什么图结构。

---

## 工具定义

工具定义呼应 Day 02 的 @tool 装饰器 + 类型注解 + 中文 docstring。注意 `ToolRuntime` 参数可以访问运行时上下文（state / store / stream_writer 等）。

### tools/route_tools.py — 路线检索工具

```python
"""tools/route_tools.py — 路线检索工具

调用 Week 05 向量库，根据自然语言查询语义检索匹配的徒步路线。
"""

from langchain.tools import tool, ToolRuntime


@tool
def search_routes(query: str, top_k: int = 3, runtime: ToolRuntime | None = None) -> str:
    """根据自然语言查询推荐匹配的徒步路线。

    Args:
        query: 用户想要的路线特征描述，如 '川西 3 天进阶路线'、'有海的高海拔短线'
        top_k: 返回的匹配路线数量上限，默认 3
        runtime: ToolRuntime 运行时上下文（2026 年新增），可访问
                 runtime.state（当前 Agent 状态）、runtime.context（用户上下文）、
                 runtime.store（长期记忆存储）、runtime.stream_writer（流式写入器）

    Returns:
        格式化后的路线推荐结果字符串，包含路线名称、地区、难度、海拔、相似度
    """
    # 如果有运行时上下文，可以记录工具调用日志或访问用户偏好
    if runtime:
        # runtime.context 是 create_agent 传入的 UserContext 实例
        ctx = runtime.context
        if ctx and ctx.preferred_region:
            # 可以根据用户偏好地区调整查询（这里仅演示 API 用法）
            query = f"{ctx.preferred_region} {query}"

    # 实际项目中这里调用 Week 05 的向量库检索
    # 为演示直接返回 mock 数据
    routes_mock = {
        "川西": [
            "🏔️ 四姑娘山二峰（川西，硬核，海拔5276m，3天）相似度 0.92",
            "🏔️ 长穿毕（川西，进阶，海拔4668m，4天）相似度 0.85",
            "🏔️ 贡嘎转山（川西，硬核，海拔4920m，6天）相似度 0.78",
        ],
        "滇西北": [
            "🏔️ 雨崩徒步（滇西北，进阶，海拔3900m，5天）相似度 0.88",
            "🏔️ 虎跳峡高路（滇西北，进阶，海拔2700m，2天）相似度 0.82",
        ],
        "西藏": [
            "🏔️ 冈仁波齐转山（西藏，硬核，海拔5650m，3天）相似度 0.90",
            "🏔️ 库拉岗日徒步（西藏，进阶，海拔5100m，5天）相似度 0.75",
        ],
    }

    # 简单关键词匹配（实际替换为向量检索）
    for keyword, routes in routes_mock.items():
        if keyword in query:
            result = "\n".join(routes[:top_k])
            return f"为您推荐以下路线：\n{result}"

    return f"未找到匹配「{query}」的路线，请尝试调整查询条件。"
```

### tools/weather_tools.py — 天气查询工具

```python
"""tools/weather_tools.py — 天气查询工具

根据地区名查询未来天气，支持 mock 模式或调用真实天气 API。
"""

from langchain.tools import tool
from datetime import datetime


@tool
def get_weather(region: str, runtime: ToolRuntime | None = None) -> str:
    """查询指定地区未来 3 天的天气预报。

    Args:
        region: 地区名，如 '川西'、'滇西北'、'西藏'
        runtime: ToolRuntime 运行时上下文（可选）

    Returns:
        格式化后的天气信息字符串
    """
    # mock 天气数据（实际项目可替换为真实天气 API 调用）
    mock_data = {
        "川西": {
            "condition": "晴转多云",
            "temp_range": "5~18°C",
            "wind": "3 级",
            "alert": "夜间低温注意保暖，高原紫外线强需防晒",
        },
        "滇西北": {
            "condition": "多云有阵雨",
            "temp_range": "8~20°C",
            "wind": "2~3 级",
            "alert": "高原天气多变，随身携带雨具",
        },
        "西藏": {
            "condition": "晴",
            "temp_range": "0~15°C",
            "wind": "4 级",
            "alert": "高海拔地区注意防寒和防高反",
        },
    }

    today = datetime.now().strftime("%m月%d日")

    if region in mock_data:
        w = mock_data[region]
        return (
            f"📍 {region} 未来 3 天天气预报\n"
            f"🌤️ 天气：{w['condition']}\n"
            f"🌡️ 温度：{w['temp_range']}\n"
            f"💨 风力：{w['wind']}\n"
            f"⚠️ 提醒：{w['alert']}\n"
            f"📅 查询时间：{today}"
        )

    return f"暂未获取到 {region} 的天气数据，请确认地区名称是否正确。"
```

### tools/gear_tools.py — 装备生成工具

```python
"""tools/gear_tools.py — 徒步装备生成工具

根据路线难度等级和天气条件智能生成建议携带的装备清单。
"""

from langchain.tools import tool


@tool
def generate_gear_list(difficulty: str, weather_keywords: str, runtime: ToolRuntime | None = None) -> str:
    """根据路线难度和天气条件生成建议的徒步装备清单。

    Args:
        difficulty: 路线难度等级，可选值 '休闲' / '进阶' / '硬核'
        weather_keywords: 天气关键词，从天气查询结果中提取的关键描述，
                          如 '晴转多云 5~18°C 注意保暖'、'多云有阵雨'
        runtime: ToolRuntime 运行时上下文（可选）

    Returns:
        格式化的装备清单字符串
    """
    # 基础装备（所有人必带）
    base_gear = [
        "🥾 登山鞋（防滑防水）",
        "🎒 登山包（40~60L）",
        "💧 水壶/水袋（1.5L+）",
        "🔦 头灯/手电（备用电池）",
        "🆘 急救包（高原反应药、创可贴、消毒）",
        "🧴 防晒霜（SPF50+）",
        "🗺️ 离线地图/导航设备",
    ]

    # 按难度补充装备
    difficulty_gear = {
        "硬核": [
            "🧊 冰爪（雪地必备）",
            "🧗 安全带 + 主锁 + 扁带",
            "🪢 动力绳（30m+）",
            "⛑️ 头盔",
            "🆘 卫星电话/个人定位信标（PLB）",
        ],
        "进阶": [
            "🦯 登山杖（双杖推荐）",
            "🦵 护膝（保护下山膝盖）",
            "📡 对讲机（结组时通信）",
        ],
        "休闲": [
            "🦯 登山杖（可选单杖）",
            "🧢 遮阳帽",
        ],
    }

    # 按天气补充装备
    weather_gear = []
    weather_lower = weather_keywords.lower()

    if "雨" in weather_keywords or "阵雨" in weather_keywords or "rain" in weather_lower:
        weather_gear.extend([
            "🧥 冲锋衣/雨衣（防雨透气）",
            "📦 防水袋（保护电子设备）",
        ])
    if "低温" in weather_keywords or "保暖" in weather_keywords or "寒" in weather_keywords:
        weather_gear.extend([
            "🧥 羽绒服（营地保暖）",
            "🧶 抓绒衣（中间层保暖）",
            "🥤 保温杯（喝热水）",
            "🧤 保暖手套 + 保暖帽",
        ])
    if "晴" in weather_keywords or "晒" in weather_keywords:
        weather_gear.extend([
            "🕶️ 太阳镜（防雪盲/强光）",
            "🧢 遮阳帽 + 防晒头巾",
        ])

    # 组装结果
    result_parts = [
        "🧾 装备清单（按路线难度和天气定制）",
        "=" * 40,
        "",
        "【基础装备 — 所有路线必备】",
    ]
    result_parts.extend(f"  {g}" for g in base_gear)

    dif_gear = difficulty_gear.get(difficulty, difficulty_gear["休闲"])
    result_parts.extend([
        "",
        f"【按难度补充 — {difficulty} 路线】",
    ])
    result_parts.extend(f"  {g}" for g in dif_gear)

    if weather_gear:
        result_parts.extend([
            "",
            "【按天气补充 — 根据当前天气预报】",
        ])
        result_parts.extend(f"  {g}" for g in weather_gear)

    result_parts.extend([
        "",
        "=" * 40,
        "💡 提示：请根据实际行程天数和季节调整装备数量。",
    ])

    return "\n".join(result_parts)
```

---

## API 端点设计

### api/chat.py — 对话端点（含 SSE 流式）

```python
"""api/chat.py — 对话处理路由

包含普通对话和 SSE 流式对话两个端点，统一响应格式。
"""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import json
import asyncio
import uuid

from agent.agent_factory import build_agent


router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """对话请求模型。"""
    message: str = Field(..., description="用户输入的消息内容")
    thread_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="会话标识，相同 thread_id 保持上下文连续",
    )


class ChatResponse(BaseModel):
    """对话响应模型。"""
    success: bool
    data: dict | None
    error: str | None = None
    meta: dict | None = None


# ─── 普通对话（阻塞等待 Agent 完整结果） ───

@router.post("/")
async def chat(req: ChatRequest, request: Request):
    """普通对话端点，阻塞等待 Agent 完整推理完成后返回结果。

    适用于不需要流式显示的场景，如后台调用或简单问答。
    Agent 自动执行多步推理：查路线 → 查天气 → 生成装备 → 综合建议。

    Args:
        req: ChatRequest — 包含用户消息和会话 thread_id
        request: FastAPI Request — 用于获取 app.state.agent

    Returns:
        统一响应格式 {success, data, meta}
    """
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        return JSONResponse(
            status_code=503,
            content=ChatResponse(
                success=False, error="Agent 尚未初始化", data=None
            ).model_dump(),
        )

    config = {
        "configurable": {
            "thread_id": req.thread_id,      # 会话 ID，多轮对话隔离
        }
    }

    try:
        # agent.invoke 是同步调用，阻塞等待完整推理链完成
        # create_agent 自动编排 ReAct 循环，不需要手动处理工具调用
        result = agent.invoke(
            {"messages": [{"role": "user", "content": req.message}]},
            config=config,
        )

        # 从 messages 中提取最新一条作为回答
        last_message = result["messages"][-1]
        answer = last_message.content if hasattr(last_message, "content") else str(last_message)

        return ChatResponse(
            success=True,
            data={
                "answer": answer,
                "thread_id": req.thread_id,
            },
            meta={
                "thread_id": req.thread_id,
            },
        ).model_dump()

    except Exception as e:
        return ChatResponse(
            success=False,
            error=f"Agent 推理失败：{str(e)}",
            data=None,
        ).model_dump()


# ─── SSE 流式对话（逐 token + 工具事件推送） ───

@router.post("/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """SSE 流式对话端点，支持逐 token 打字机效果和工具调用事件推送。

    Stream 事件格式：
    - tool_start: 工具开始调用 {type, name, args}
    - tool_end: 工具调用完成 {type, name, result}
    - text: LLM 生成的文本片段（逐 token）
    - done: 推理完成 {type}

    前端通过 EventSource 或 fetch + ReadableStream 消费此接口。

    Args:
        req: ChatRequest — 包含用户消息和会话 thread_id
        request: FastAPI Request — 用于获取 app.state.agent

    Returns:
        StreamingResponse，Content-Type: text/event-stream
    """
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": "Agent 尚未初始化"},
        )

    config = {
        "configurable": {
            "thread_id": req.thread_id,
        }
    }

    async def event_stream():
        """异步生成 SSE 事件。"""
        try:
            # stream_events(version="v3") 是 2026 年推荐的新一代流式 API
            # 返回 StreamSnapshot 对象，通过 .messages / .values / .interrupts 访问
            stream = agent.stream_events(
                {"messages": [{"role": "user", "content": req.message}]},
                config,
                version="v3",              # 使用最新的 v3 版本 API
            )

            for snapshot in stream.values:
                # 1. 发送消息的逐 token 片段（打字机效果）
                if snapshot.messages:
                    for msg in snapshot.messages:
                        if msg.content:
                            event_data = json.dumps({
                                "type": "text",
                                "content": msg.content,
                            }, ensure_ascii=False)
                            yield f"data: {event_data}\n\n"

                # 2. 检查是否有中断（interrupt 人机交互）
                if snapshot.interrupted:
                    event_data = json.dumps({
                        "type": "interrupt",
                        "interrupts": [
                            {"id": i.id, "value": i.value}
                            for i in (snapshot.interrupts or [])
                        ],
                    }, ensure_ascii=False)
                    yield f"data: {event_data}\n\n"

            # 3. 发送完成事件
            yield 'data: {"type":"done"}\n\n'

        except Exception as e:
            error_data = json.dumps({
                "type": "error",
                "content": f"流式推理失败：{str(e)}",
            }, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",      # 禁用 Nginx 缓冲
        },
    )
```

### SSE 流式事件格式（前端消费参考）

```
# 工具调用开始
data: {"type":"tool_start","name":"search_routes","args":{"query":"川西 3 天进阶路线","top_k":3}}

# 工具调用结束
data: {"type":"tool_end","name":"search_routes","result":"为您推荐以下路线：\n- 四姑娘山二峰（川西，硬核，海拔5276m，3天）..."}

# LLM 逐 token 文本
data: {"type":"text","content":"根据"}
data: {"type":"text","content":"查询"}
data: {"type":"text","content":"结果"}
data: {"type":"text","content":"，"}

# 推理完成
data: {"type":"done"}
```

---

## main.py — FastAPI 入口

```python
"""main.py — FastAPI 应用入口

应用生命周期管理：
1. lifespan 启动时初始化 Agent（单例）
2. 注册路由和静态文件
3. 全局异常处理和请求追踪中间件
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uuid
import time
import os

from agent.agent_factory import build_agent
from api.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。

    启动时初始化 Agent（模型 + 工具 + Checkpointer + 中间件）。
    这是应用级单例，所有请求复用同一个 Agent 实例。
    """
    print("[init] 正在初始化 Agent...")
    agent = build_agent("ollama:qwen2.5:1.5b")
    app.state.agent = agent
    print("[init] Agent 初始化完成")
    yield
    print("[shutdown] 正在清理资源...")
    # Checkpointer 和 Store 是内存模式，不需要额外清理
    print("[shutdown] 清理完成")


app = FastAPI(
    title="徒步出行规划 Agent",
    version="1.0.0",
    description="Week 06 综合实战 — create_agent 多步推理 Agent + FastAPI + SSE 流式",
    lifespan=lifespan,
)

# CORS：允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 请求追踪中间件 ───
@app.middleware("http")
async def trace_requests(request: Request, call_next):
    """每个请求记录唯一 ID、方法和耗时，便于调试和链路追踪。"""
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    response.headers["X-Request-ID"] = rid
    print(f"[{rid}] {request.method:6} {request.url.path:30} → {response.status_code} ({elapsed:.0f}ms)")
    return response


# ─── 全局异常处理 ───
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理异常，返回统一格式的错误响应。"""
    print(f"[ERROR] {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": f"服务器内部错误：{str(exc)}",
            "data": None,
        },
    )


# ─── 注册路由 ───
app.include_router(chat_router)


# ─── 静态文件服务 ───
web_dir = os.path.join(os.path.dirname(__file__), "web")
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir, html=True), name="static")


@app.get("/")
async def read_index():
    """根路径：返回 Web UI 首页。"""
    index_path = os.path.join(web_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "徒步出行规划 Agent 已启动"}


@app.get("/health")
async def health():
    """健康检查端点。"""
    return {
        "status": "ok",
        "version": "1.0.0",
        "agent_initialized": hasattr(app.state, "agent"),
    }
```

---

## Web UI 设计

`web/index.html` 最简布局：

```
┌──────────────────────────────────────────────┐
│  🥾 徒步出行规划 Agent（create_agent 版）    │
├──────────────────────────────────────────────┤
│  💬 对话区                                    │
│  ┌────────────────────────────────────────┐  │
│  │ 用户：我想去川西 3 天的进阶路线        │  │
│  │                                        │  │
│  │ 🔧 调用工具: search_routes("川西...")   │  │
│  │ 🔧 调用工具: get_weather("川西")        │  │
│  │ 🔧 调用工具: generate_gear_list(...)    │  │
│  │                                        │  │
│  │ 🤖 Agent 综合建议：                      │  │
│  │    ## 推荐路线                          │  │
│  │    四姑娘山二峰（川西，硬核）...         │  │
│  │    ## 天气提醒                          │  │
│  │    晴转多云，5~18°C，注意保暖           │  │
│  │    ## 装备清单                          │  │
│  │    登山鞋、背包、冰爪...                │  │
│  │    ## 安全提示                          │  │
│  │    高海拔地区注意防高反                │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  [输入消息...]                    [发送]      │
│  会话: {thread_id}   流式 ☑                  │
│                                              │
│  控制面板:  [新建会话] [清空对话]              │
└──────────────────────────────────────────────┘
```

前端交互要点：
- 普通模式：点击发送后等待完整结果，一次性渲染
- 流式模式：逐 token 显示 LLM 回答（打字机效果），工具调用过程实时展示
- 工具调用过程用不同颜色/图标标识（search_routes / get_weather / generate_gear_list）
- 最终建议用 Markdown 渲染（推荐路线 / 天气提醒 / 装备清单 / 安全提示分段）
- 支持多轮对话，相同 thread_id 保持上下文连续性
- 控制面板可新建会话或清空当前对话

---

## 开发顺序（自己写，Claude Code 辅助）

### 第一阶段：工具层（~30 min）
1. `tools/route_tools.py` — search_routes @tool，含 ToolRuntime 参数
2. `tools/weather_tools.py` — get_weather @tool，含 mock 天气数据
3. `tools/gear_tools.py` — generate_gear_list @tool，难度+天气双因素
4. 单独验证每个工具可调（手动传参看输出）

### 第二阶段：Agent 构建（~40 min，今天核心）
5. `agent/agent_factory.py` — 用 create_agent 构建完整 Agent
6. 系统提示词编写：定义四步推理流程
7. 配置 Checkpointer + Middleware + context_schema
8. 本地 `agent.invoke()` 跑通完整推理链（"川西 3 天进阶路线"）
9. 验证 `agent.stream_events(version="v3")` 流式工作

### 第三阶段：API 层（~30 min）
10. `api/chat.py` — 普通对话端点（POST /api/v1/chat/）
11. `api/chat.py` — SSE 流式端点（POST /api/v1/chat/stream）
12. `schemas/response.py` — 统一响应格式

### 第四阶段：组装（~30 min）
13. `main.py` — FastAPI 入口 + lifespan + CORS + 异常处理
14. `web/index.html` + `web/script.js` — 对话 UI

---

## 验证清单

- [ ] `uvicorn main:app --reload` 正常启动
- [ ] `/docs` Swagger 能看到 chat 和 chat/stream 两个路由
- [ ] `POST /api/v1/chat/` 问"川西 3 天进阶路线" → Agent 依次调用 3 个工具 → 返回综合出行建议
- [ ] 响应中包含路线推荐 + 天气提醒 + 装备清单 + 安全提示四个部分
- [ ] `POST /api/v1/chat/stream` SSE 流式 → 前端看到逐 token 打字机效果 + 工具调用事件
- [ ] 用同一个 thread_id 追问"那条路线需要什么装备" → Agent 记得上文（Checkpointer 生效）
- [ ] 换一个 thread_id 提问 → Agent 不记得上文（会话隔离）
- [ ] 问"你好" → Agent 直接回答，不调用任何工具（系统提示词约束生效）
- [ ] 问"休闲路线有什么推荐" → Agent 只调 search_routes，不调天气和装备（或按推理流程完整执行）
- [ ] 故意传错误的工具参数 → ToolRetryMiddleware 自动重试
- [ ] 流式中断后恢复 → stream_events 正确处理 interrupt
- [ ] 所有接口返回统一 `{success, data, error}` 格式
- [ ] Web UI 对话 + 工具调用过程 + 最终建议展示正常

---

## 本周总结

```
☑ LangChain 基础：init_chat_model / ChatPromptTemplate / LCEL 管道链 / Output Parser
☑ LangChain 工具调用：@tool 装饰器 / ToolRuntime 运行时 / ToolMessage 完整循环
☑ LangGraph 入门：StateGraph / State(TypedDict+reducer) / Node / Edge / START/END
☑ LangGraph 进阶：条件边路由 / 循环实现 Agent Loop / create_agent 高层 API
☑ 持久化与 HITL：Checkpointer 状态存档 / thread_id 多轮记忆 / interrupt 人机交互
☑ 高级模式：子图 / 并行 fan-out / stream 流式 / Mermaid 可视化 / Functional API
☑ create_agent 简化实战：一行创建完整 Agent（内置 LangGraph 工具循环 + Checkpointer + 中间件）
☑ 副线：Claude Code 审查 LCEL、画状态机草图、调试卡死节点
☑ 产出：多步推理 Agent（create_agent + 工具 + Checkpointer + 中间件 + FastAPI + SSE + Web UI）

框架 = 把手写的 while True 变成显式的图，把手动 messages 管理交给 State，
把重启即丢交给 Checkpointer，把重试逻辑交给 Middleware。
手写过 Agent Loop（Week 03），所以用 create_agent 不是黑盒。
手写过 StateGraph（Day 05），所以知道 create_agent 底层就是那个图。
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

## 对照回顾：Week 03 → Week 06 框架升级

| 维度 | Week 03 手写 | Week 06 create_agent |
|------|-------------|---------------------|
| Agent 创建 | 手写 while True Agent Loop + 条件判断 | `create_agent(model, tools, ...)` 一行 |
| 工具绑定 | 手写 JSON Schema + 手动匹配 tool_calls | @tool 装饰器自动推断 Schema |
| 工具循环 | 手写 for 循环 + break 条件 | create_agent 内置 LangGraph 图循环 |
| 持久化 | 无，手动 json.dump 到文件 | `checkpointer=InMemorySaver()` 自动存档 |
| 多轮对话 | 手动维护 messages 列表 | thread_id 自动隔离 |
| 中间件 | 无，异常靠 try/except | `middleware=[ModelRetryMiddleware, ...]` 可插拔 |
| 结构化输出 | 手动 json.loads + Pydantic | `response_format=MyModel` 一步到位 |
| 流式 | 手写 SSE 行解析 + [DONE] 判断 | `agent.stream_events(version="v3")` 即时可用 |
| 调试 | print + pdb 打全场 | get_state / draw_mermaid / LangSmith / Claude Code |

> **核心结论：** 每一层抽象都是在替你处理你手写过的那套逻辑。Week 03 你手写了 Agent Loop 的全部细节，所以 Week 06 用 create_agent 时，你知道那一行 API 下面在干什么——拿着 messages、检查 tool_calls、调工具、继续循环、直到不再调工具为止。**框架不是魔法，是你手写过的东西的封装。**

---

## 对照回顾：Day 05 StateGraph → Day 07 create_agent

| 对比项 | Day 05 手写 StateGraph | Day 07 create_agent |
|--------|----------------------|-------------------|
| 代码量 | ~80 行（state + nodes + graph + edges） | 1 行 `create_agent(...)` |
| 图结构自定义 | 完全自由 | 标准 ReAct 模式，不可自定义 |
| 学习成本 | 需要理解 StateGraph API | 零门槛 |
| 调试 | get_state / draw_mermaid | 底层仍然是 LangGraph，调试方法通用 |
| 适用场景 | 需要自定义控制流（多分支/并行/HITL） | 标准 ReAct Agent |

**决策建议：**
- 如果你的 Agent 是"LLM 调工具 → 继续 → 直到不用工具 → 结束"的标准 ReAct 模式，**用 create_agent**（Day 07）。
- 如果你的 Agent 需要多路并行、子图复用、interrupt 人机交互、自定义图结构，**手写 StateGraph**（Day 05）。
- 两者底层都是 LangGraph 图，调试方法通用——`get_state`、`draw_mermaid`、`stream_events` 都适用。

---

## 副线笔记

```
本周副线：全程 Claude Code 结对编程。
Day 01 — 审查 LCEL 链，理解 Runnable.pipe() 本质
Day 02 — 辅助编写 @tool 装饰器 + bind_tools 调试
Day 03 — 画 ASCII 草图设计 Agent 架构
Day 04 — 审查 StateGraph 节点 + 边 + 条件分支
Day 05 — 辅助调试 Checkpointer + interrupt 恢复
Day 06 — 调试子图/并行/流式 bug 三件套（get_state + draw_mermaid + LangSmith）
Day 07 — 审查 create_agent 配置 + 辅助编写整个项目

对比 Week 03 "自己手写 + 出问题才查文档"：
- Week 06 变成了"先自己想架构，让 Claude Code 出第一版，你审查修改"
- 效率提升：以前一小时写 50 行，现在一小时审 150 行
- 质量提升：Claude Code 能发现你忽略的边界情况（如 thread_id 隔离、中间件配置）
- 但需要你保持架构决策权——Claude Code 擅长执行，不擅长做取舍

列出 3 个本周最值得记住的 API 变化：
  1. create_agent 是 2026 年推荐入口，底层基于 LangGraph，内置 ReAct 循环
  2. InMemorySaver（不是 MemorySaver）是 2026 年的 Checkpointer 导入路径
  3. ToolRuntime 参数让 @tool 函数能访问运行时上下文（state / store / stream_writer）

Week 07 进入多 Agent 协作：
  多个 Agent 怎么分工（规划者 / 执行者 / 审查者）、怎么通信、怎么避免死锁。
  本周的单 Agent（create_agent）将成为多 Agent 系统的子节点。
```

---

## 技能覆盖（对照 Week 01 / Week 03 / Week 05 复习）

| 已学知识点 | Week 06 Day 07 项目中的复用 |
|---------------|--------------------|
| Pydantic v2 + Field | UserContext / ChatRequest / ChatResponse 模型 |
| FastAPI 路由 + Body | chat / chat/stream 路由 |
| Depends + 异常处理 + 中间件 | app.state.agent 单例 / 全局异常 / 请求追踪 |
| async/await | StreamingResponse 异步生成器 |
| SSE 流式 | chat/stream 用 stream_events 逐 token 推送 |
| 统一响应格式 | 所有接口统一 `{success, data, error}` |
| Week 03 Agent Loop 手写经验 | 理解 create_agent 底层的 ReAct 循环 |
| Week 05 向量库检索 | search_routes 工具调向量库（概念复用） |
| Week 06 @tool / ToolRuntime | 三个工具均使用 @tool 装饰器 + 运行时上下文 |

Week 01 的 FastAPI 底座 + Week 03 的 Agent 手写经验 + Week 05 的向量库能力，在 Week 06 项目中全部复现并升级——这就是"不做 Demo、做底座"的意义。

---

## 下周预告

Week 07 进入多 Agent 协作：多个 Agent 分工（规划者 / 执行者 / 审查者）、Agent 间通信、避免死锁与循环。本周的单 Agent（create_agent）将成为多 Agent 系统的子节点。LangGraph 的子图与并行能力将大放异彩。副线对比 Claude Code / Cursor / Aider 三个工具，建立"什么时候用哪个"的判断力。
