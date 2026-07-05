# Day 07 — 综合实战：多 Agent 徒步出行规划

## 今日目标

把本周的四大模式（重点是 Subagents）+ Context Engineering + Week 06 的 create_agent + Week 05 的向量库 + Week 01 的 FastAPI 全部组装成一个完整的**多 Agent 徒步出行规划系统**。

过去六天我们一天搭一块积木：Day 02 Subagents 把子 Agent 包装成 tool，Day 03 Handoffs 让控制权流转，Day 04 Router 分类后分发、Skills 按需加载，Day 05 Deep Agents 一行创建带文件系统的超级 Agent，Day 06 Context Engineering 决定每个 Agent 看到什么。今天把积木拼成一座房子——路线专家 + 天气专家 + 装备专家 + 规划主 Agent，主 Agent 协调三个专家，上下文隔离让主 Agent 只看结论不看过程。

**今天全程 Claude Code 结对编程。** 你做架构决策（哪些 Agent、各自什么职责、怎么编排），Claude Code 出第一版代码，你审查修改。

---

## 项目定位

```
一个多 Agent 徒步出行规划系统，输入"我想去川西3天的进阶路线"，
主 Agent 协调三个子 Agent：
  1. 路线专家 Agent → 检索路线（复用 Week 05 向量库）→ 推荐2-3条路线
  2. 天气专家 Agent → 查询目标地区天气 → 给出天气建议
  3. 装备专家 Agent → 根据路线难度+天气生成装备清单
  4. 主 Agent → 综合三个子 Agent 的结论 → 生成完整出行规划

技术栈：Subagents 模式 + create_agent + FastAPI + Web UI
上下文策略：上下文隔离（主 Agent 只看子 Agent 结论）
```

> **和 Week 06 Day 07 的单 Agent 版本对比：** Week 06 是一个 create_agent 调所有工具（search_routes / get_weather / generate_gear_list 全塞给一个 Agent），所有工具返回结果堆在同一个 messages 里。本周是主 Agent 协调三个专家子 Agent，每个子 Agent 有独立上下文、独立工具、独立 checkpointer，主 Agent 只拿结论。核心升级就是 Day 01 讲的那句话——多 Agent 的价值不在"多"，而在"分"，分的是上下文。

---

## 项目结构

```
week07/day07/
├── main.py              # FastAPI 入口 + lifespan + CORS
├── tools/
│   ├── __init__.py
│   ├── route_tools.py   # @tool 路线检索（调 Week 05 向量库）
│   ├── weather_tools.py # @tool 天气查询
│   └── gear_tools.py    # @tool 装备生成
├── agents/
│   ├── __init__.py
│   ├── route_agent.py   # 路线专家子 Agent
│   ├── weather_agent.py # 天气专家子 Agent
│   ├── gear_agent.py    # 装备专家子 Agent
│   └── main_agent.py    # 主 Agent（协调者）
├── api/
│   ├── __init__.py
│   └── chat.py          # 对话端点 + SSE 流式
├── schemas/
│   ├── __init__.py
│   └── models.py        # Pydantic 模型
├── web/
│   ├── index.html       # 对话 UI
│   └── script.js        # 前端逻辑
└── requirements.txt
```

Week 06 的 `agent/agent_factory.py` 一个文件搞定，本周拆成 `agents/` 目录下五个文件——因为每个子 Agent 都需要独立的模型配置、工具列表、系统提示词，不能再混在一个 factory 里。

---

## Agent 架构设计

这是今天**最核心**的部分。用 Subagents 模式构建多 Agent 系统：主 Agent 把三个子 Agent 各自包装成一个 `@tool`，主 Agent 自己不干活，只负责"派活 + 综合"。

### 架构图

```
用户输入："我想去川西3天的进阶路线，帮我规划一下"
  │
  ▼
┌──────────────────────────────────────────────────────────┐
│  主 Agent（规划协调者）                                    │
│  tools: ask_route_expert / ask_weather_expert /          │
│         ask_gear_expert                                   │
│                                                          │
│  推理流程（按顺序协调）：                                   │
│  Step 1 → ask_route_expert("川西3天进阶路线")              │
│  Step 2 → ask_weather_expert("川西天气")                  │
│  Step 3 → ask_gear_expert("进阶难度+晴转多云")             │
│  Step 4 → 综合三个结论 → 生成完整出行规划                   │
└──────────────────────────────────────────────────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│ 路线专家 Agent  │  │ 天气专家 Agent  │  │ 装备专家 Agent  │
│ tools:        │  │ tools:        │  │ tools:        │
│  search_routes│  │  get_weather  │  │  generate_    │
│               │  │  get_forecast │  │  gear_list    │
│ 独立上下文     │  │ 独立上下文     │  │ 独立上下文     │
└───────────────┘  └───────────────┘  └───────────────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
        主 Agent 收到三个 tool 返回值（只有结论，过程不暴露）
                           │
                           ▼
        生成完整出行规划 → SSE 流式回复用户
```

### Context Engineering 策略

| 策略 | 在本项目中的体现 |
|------|-----------------|
| 上下文隔离 | 主 Agent 只看子 Agent 返回结论，不看子 Agent 内部调工具、看结果、再思考的过程 |
| 上下文压缩 | 子 Agent 返回结构化结论（路线名+难度+距离+亮点），不是原始工具输出 |
| 独立 checkpointer | 每个子 Agent 有各自的 `InMemorySaver()` 实例，thread_id 互不干扰 |

对比 Week 06 单 Agent 的上下文：

```
Week 06 单 Agent 的 messages（一个列表全堆）：
  [system] [user] [tool:路线500字] [tool:天气100字] [tool:装备300字] [ai总结]
  → 上下文膨胀，每轮工具结果都堆进来

Week 07 多 Agent 主 Agent 的 messages（只存结论）：
  [system] [user] [tool:路线结论200字] [tool:天气结论150字] [tool:装备结论200字] [ai综合]
  → 子 Agent 内部的 search_routes / get_weather 过程不进主 Agent 上下文
```

### 为什么选 Subagents 而不是其他模式

| 模式 | 适合本项目吗 | 原因 |
|------|-------------|------|
| Subagents | 选这个 | 三个专家任务相互独立，主 Agent 需要综合全部结果 |
| Handoffs | 不适合 | 用户始终跟主 Agent 对话，不需要控制权流转到专家 |
| Router | 不适合 | 不是分类后分发，而是需要综合多个专家结论 |
| Skills | 补充用 | 可给装备专家按需加载季节性装备知识（进阶） |

---

## 代码实现

### schemas/models.py — Pydantic 模型

```python
"""schemas/models.py — 请求/响应模型定义"""
from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    """对话请求模型。"""
    message: str = Field(..., description="用户输入的消息内容")
    session_id: str = Field(
        default="default-session",
        description="会话标识，相同 session_id 保持上下文连续",
    )


class ChatResponse(BaseModel):
    """对话响应模型。"""
    success: bool
    answer: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
```

### tools/route_tools.py — 路线检索工具

```python
"""tools/route_tools.py — 路线检索工具

实际项目接 Week 05 的 Chroma 向量库做语义检索，这里用 mock 数据演示。
"""
from langchain.tools import tool

# mock 路线数据库（实际替换为向量库 similarity_search）
ROUTES_DB = {
    "川西": [
        {"name": "长穿毕（长坪沟穿越毕棚沟）", "difficulty": "进阶",
         "distance": "约45km", "altitude": "4668m", "duration": "4天",
         "highlights": "经典穿越路线，雪山草甸海子一网打尽"},
        {"name": "四姑娘山二峰", "difficulty": "硬核",
         "distance": "约30km", "altitude": "5276m", "duration": "3天",
         "highlights": "蜀山之后，技术攀登入门级雪峰"},
        {"name": "贡嘎大环线", "difficulty": "硬核",
         "distance": "约78km", "altitude": "4920m", "duration": "6-7天",
         "highlights": "蜀山之王环绕，冰川全景"},
    ],
    "滇西北": [
        {"name": "雨崩徒步", "difficulty": "进阶",
         "distance": "约40km", "altitude": "3900m", "duration": "5天",
         "highlights": "梅里雪山脚下，神瀑冰湖"},
    ],
    "西藏": [
        {"name": "冈仁波齐转山", "difficulty": "硬核",
         "distance": "约53km", "altitude": "5650m", "duration": "3天",
         "highlights": "世界中心神山转山"},
    ],
}


@tool
def search_routes(query: str, top_k: int = 3) -> str:
    """根据自然语言查询推荐匹配的徒步路线。

    Args:
        query: 路线需求描述，如 '川西 3 天进阶路线'
        top_k: 返回路线数量上限，默认 3

    Returns:
        格式化路线推荐结果，含路线名、难度、距离、海拔、亮点
    """
    # 实际项目：query → embedding → 向量库 similarity_search → 返回 top_k
    results = []
    for region, routes in ROUTES_DB.items():
        if region in query:
            results.extend(routes[:top_k])
            break

    # 没匹配到地区则返回所有
    if not results:
        for routes in ROUTES_DB.values():
            results.extend(routes)
    results = results[:top_k]

    if not results:
        return f"未找到匹配「{query}」的路线，请调整查询条件。"

    lines = [f"为您检索到 {len(results)} 条匹配路线：\n"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"路线{i}：{r['name']}\n"
            f"  难度：{r['difficulty']} | 距离：{r['distance']} | "
            f"海拔：{r['altitude']} | 天数：{r['duration']}\n"
            f"  亮点：{r['highlights']}\n"
        )
    return "\n".join(lines)
```

### tools/weather_tools.py — 天气查询工具

```python
"""tools/weather_tools.py — 天气查询工具"""
from langchain.tools import tool
from datetime import datetime, timedelta

WEATHER_DB = {
    "川西": {"condition": "晴转多云，夜间有阵雪可能", "temp_range": "-5~12°C",
             "wind": "3-4级，垭口6级",
             "alert": "昼夜温差大注意保暖；紫外线极强需防晒；垭口风力大注意防风"},
    "滇西北": {"condition": "多云有阵雨", "temp_range": "5~18°C",
               "wind": "2-3级", "alert": "天气多变随身携带雨具；雨后路滑注意安全"},
    "西藏": {"condition": "晴", "temp_range": "0~15°C",
             "wind": "4-5级", "alert": "高海拔注意防寒和防高反；空气干燥注意补水"},
}


@tool
def get_weather(region: str) -> str:
    """查询指定地区未来3天的天气预报。

    Args:
        region: 地区名，如 '川西'、'滇西北'、'西藏'

    Returns:
        格式化天气信息，含天气状况、温度、风力、徒步建议
    """
    today = datetime.now()
    dates = [(today + timedelta(days=i)).strftime("%m月%d日") for i in range(3)]

    if region in WEATHER_DB:
        w = WEATHER_DB[region]
        return (f"📍 {region} 未来3天天气预报\n"
                f"日期：{' / '.join(dates)}\n"
                f"天气：{w['condition']}\n温度：{w['temp_range']}\n"
                f"风力：{w['wind']}\n徒步建议：{w['alert']}")
    return f"暂未获取到 {region} 的天气数据，请确认地区名称。"


@tool
def get_forecast(region: str, days: int = 3) -> str:
    """获取指定地区的多日天气预报详情。region 为地区名，days 为天数。"""
    if region in WEATHER_DB:
        w = WEATHER_DB[region]
        today = datetime.now()
        lines = [f"📍 {region} 未来{days}天逐日预报：\n"]
        for i in range(days):
            date = (today + timedelta(days=i)).strftime("%m月%d日")
            lines.append(f"Day{i+1}（{date}）：{w['condition']}，温度 {w['temp_range']}，风力 {w['wind']}")
        lines.append(f"\n徒步建议：{w['alert']}")
        return "\n".join(lines)
    return f"暂未获取到 {region} 的预报数据。"
```

### tools/gear_tools.py — 装备生成工具

```python
"""tools/gear_tools.py — 装备生成工具

根据路线难度和天气条件智能生成装备清单。CMA 山地户外教练实战经验分级。
"""
from langchain.tools import tool


@tool
def generate_gear_list(difficulty: str, weather_summary: str, duration_days: int = 3) -> str:
    """根据路线难度和天气条件生成建议的徒步装备清单。

    Args:
        difficulty: 路线难度等级，可选 '休闲' / '进阶' / '硬核'
        weather_summary: 天气摘要，如 '晴转多云 -5~12°C 注意保暖防风'
        duration_days: 行程天数，默认 3 天

    Returns:
        分级装备清单（必备/推荐/可选），含用途说明
    """
    # 必备装备：所有路线无条件携带
    must_have = [
        "登山鞋（防滑防水，提前磨合）", "登山包 45-65L（带防雨罩）",
        "头灯 + 备用电池", "急救包（含高原反应药、创可贴、消毒碘伏）",
        "防晒霜 SPF50+ + 唇膏", "保暖帽 + 保暖手套",
        "1.5L+ 水壶/水袋", "高热量路餐（能量棒、坚果、巧克力）",
        "离线地图 / GPS 设备", "身份证 + 紧急联系人信息卡",
    ]
    # 推荐装备：按难度分级
    recommended = {
        "休闲": ["登山杖（单杖）", "速干衣裤", "遮阳帽", "充电宝"],
        "进阶": ["双杖（保护膝盖）", "护膝", "对讲机", "冲锋衣裤", "抓绒衣", "防潮垫+睡袋"],
        "硬核": ["冰爪", "头盔", "安全带+主锁+扁带", "卫星电话/PLB", "动力绳30m+", "高山靴"],
    }
    # 可选装备：按天气补充
    optional = []
    if "雪" in weather_summary or "寒" in weather_summary or "-5" in weather_summary:
        optional += ["羽绒服（营地保暖）", "保温杯", "雪套"]
    if "雨" in weather_summary or "阵雨" in weather_summary:
        optional += ["雨衣", "防水袋"]
    if "风" in weather_summary or "6级" in weather_summary:
        optional += ["防风面罩", "墨镜"]
    if "晴" in weather_summary or "晒" in weather_summary:
        optional += ["太阳镜", "防晒头巾"]

    rec = recommended.get(difficulty, recommended["进阶"])
    lines = [f"装备清单（{difficulty}级路线 / {duration_days}天行程）", "=" * 50, "",
            "【必备 — 不可省略】"]
    lines += [f"  {i+1}. {g}" for i, g in enumerate(must_have)]
    lines += ["", f"【推荐 — {difficulty}路线】"]
    lines += [f"  {i+1}. {g}" for i, g in enumerate(rec)]
    if optional:
        lines += ["", "【可选 — 按天气补充】"]
        lines += [f"  {i+1}. {g}" for i, g in enumerate(optional)]
    lines += ["", "=" * 50, f"提示：基于{difficulty}级路线和当前天气定制，请根据实际情况调整。"]
    return "\n".join(lines)
```

### agents/route_agent.py — 路线专家子 Agent

```python
"""agents/route_agent.py — 路线专家子 Agent

Subagents 模式的子 Agent：有独立的模型、工具、系统提示词、checkpointer。
主 Agent 通过包装的 @tool 调用它，内部跑完整 ReAct 循环后返回结论。
"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from tools.route_tools import search_routes

# 子 Agent 用 temperature=0，保证路线检索结果稳定可复现
model = init_chat_model("gpt-4o-mini", temperature=0)

route_expert = create_agent(
    model=model,
    tools=[search_routes],
    system_prompt="""你是徒步路线专家，擅长推荐适合的徒步路线。

你的职责：
1. 根据用户的目的地、天数、难度要求检索匹配路线
2. 推荐2-3条最适合的路线，包含：路线名、难度、距离、海拔、亮点
3. 如果没有完全匹配的，推荐最接近的并说明差异

注意：你只负责路线推荐，不回答天气或装备问题。""",
    checkpointer=InMemorySaver(),  # 独立实例，和主 Agent 隔离
)
```

### agents/weather_agent.py — 天气专家子 Agent

```python
"""agents/weather_agent.py — 天气专家子 Agent"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from tools.weather_tools import get_weather, get_forecast

model = init_chat_model("gpt-4o-mini", temperature=0)

weather_expert = create_agent(
    model=model,
    tools=[get_weather, get_forecast],
    system_prompt="""你是天气查询专家。

你的职责：
1. 查询指定地区的当前天气和未来天气预报
2. 给出徒步相关的天气建议（如防雨、防寒、防晒）
3. 如果天气恶劣，明确提醒不适合出行

注意：你只负责天气信息，不推荐路线或装备。""",
    checkpointer=InMemorySaver(),
)
```

### agents/gear_agent.py — 装备专家子 Agent

```python
"""agents/gear_agent.py — 装备专家子 Agent"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from tools.gear_tools import generate_gear_list

model = init_chat_model("gpt-4o-mini", temperature=0)

gear_expert = create_agent(
    model=model,
    tools=[generate_gear_list],
    system_prompt="""你是徒步装备专家，拥有 CMA 山地户外教练的专业经验。

你的职责：
1. 根据路线难度和天气情况生成装备清单
2. 装备按必备/推荐/可选三级分类
3. 标注每件装备的用途和注意事项
4. 考虑重量和实用性，不是越多越好

注意：你只负责装备建议，不回答路线或天气问题。""",
    checkpointer=InMemorySaver(),
)
```

### agents/main_agent.py — 主 Agent（协调者）

Subagents 模式核心：把三个子 Agent 各自包装成一个 `@tool`，主 Agent 只负责"派活 + 综合"。

```python
"""agents/main_agent.py — 主 Agent，协调三个专家子 Agent"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agents.route_agent import route_expert
from agents.weather_agent import weather_expert
from agents.gear_agent import gear_expert

# 主 Agent 用 temperature=0.7，综合规划时需要一定创造性
model = init_chat_model("gpt-4o-mini", temperature=0.7)


# ─── 把子 Agent 包装成 tool（Subagents 模式核心） ───
@tool
def ask_route_expert(query: str) -> str:
    """向路线专家提问，获取路线推荐。
    当用户需要推荐徒步路线、查询路线难度或距离时使用此工具。
    query 为路线相关需求描述，如 '川西3天进阶路线'。"""
    result = route_expert.invoke(
        {"messages": [{"role": "user", "content": query}]},
        config={"configurable": {"thread_id": "route-expert"}},
    )
    return result["messages"][-1].content  # 只返回结论，不暴露内部过程


@tool
def ask_weather_expert(query: str) -> str:
    """向天气专家提问，获取天气信息。
    当用户需要查询目的地天气、获取徒步天气建议时使用此工具。
    query 为天气相关需求，如 '川西未来3天天气'。"""
    result = weather_expert.invoke(
        {"messages": [{"role": "user", "content": query}]},
        config={"configurable": {"thread_id": "weather-expert"}},
    )
    return result["messages"][-1].content


@tool
def ask_gear_expert(query: str) -> str:
    """向装备专家提问，获取装备清单。
    当用户问"带什么装备""需要准备什么""穿什么"时使用此工具。
    query 为装备相关需求，需包含路线难度和天气信息。"""
    result = gear_expert.invoke(
        {"messages": [{"role": "user", "content": query}]},
        config={"configurable": {"thread_id": "gear-expert"}},
    )
    return result["messages"][-1].content


SYSTEM_PROMPT = """你是徒步出行规划主助手，负责协调三个专家子 Agent 为用户提供完整的出行规划。

## 协调流程
1. 路线推荐：调用 ask_route_expert 获取适合的路线推荐
2. 天气查询：根据推荐路线的地区，调用 ask_weather_expert 查询天气
3. 装备生成：根据路线难度和天气情况，调用 ask_gear_expert 生成装备清单
4. 综合规划：把三个专家的结果整合成完整的出行规划方案

## 输出格式
最终出行规划应包含：推荐路线 / 天气预报和建议 / 装备清单 / 安全注意事项 / 行程建议

## 约束
- 每一步都基于前一步的结果进行
- 如果用户只问一方面（如只问路线），不需要调用所有专家
- 注意安全提示，恶劣天气或高难度路线要特别提醒
"""

main_agent = create_agent(
    model=model,
    tools=[ask_route_expert, ask_weather_expert, ask_gear_expert],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=InMemorySaver(),
)
```

> **关键点：包装函数里的 `thread_id`。** 每个子 Agent 的 `invoke` 调用都传了独立的 thread_id，这保证了子 Agent 自己的多轮记忆。如果用同一个 thread_id，多个子 Agent 会串状态。Day 02 踩过这个坑，今天别再踩。

### main.py — FastAPI 入口

```python
"""main.py — FastAPI 应用入口"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from agents.main_agent import main_agent
from api.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[init] 多 Agent 徒步规划系统启动")
    app.state.agent = main_agent
    print("[init] 主 Agent 就绪，三个子 Agent 已加载")
    yield
    print("[shutdown] 系统关闭")


app = FastAPI(title="多 Agent 徒步出行规划", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(chat_router, prefix="/api")

web_dir = os.path.join(os.path.dirname(__file__), "web")
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir, html=True), name="static")


@app.get("/")
async def index():
    index_path = os.path.join(web_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "系统已启动，访问 /docs 查看 API"}


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
```

### api/chat.py — 对话端点 + SSE 流式

```python
"""api/chat.py — 对话端点 + SSE 流式"""
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from schemas.models import ChatRequest, ChatResponse
import json

router = APIRouter()


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    """阻塞模式：等主 Agent 协调完所有子 Agent 后返回完整规划。"""
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        return JSONResponse(status_code=503,
                            content=ChatResponse(success=False, error="Agent 未初始化").model_dump())

    config = {"configurable": {"thread_id": req.session_id}}
    input_data = {"messages": [{"role": "user", "content": req.message}]}
    try:
        result = agent.invoke(input_data, config=config)  # 主 Agent 自动协调三个子 Agent
        return ChatResponse(success=True, answer=result["messages"][-1].content,
                            session_id=req.session_id).model_dump()
    except Exception as e:
        return ChatResponse(success=False, error=f"Agent 推理失败：{str(e)}").model_dump()


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """SSE 流式模式：实时推送主 Agent 调用哪个子 Agent、子 Agent 结论。"""
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        return JSONResponse(status_code=503,
                            content={"success": False, "error": "Agent 未初始化"})

    config = {"configurable": {"thread_id": req.session_id}}
    input_data = {"messages": [{"role": "user", "content": req.message}]}

    async def event_stream():
        try:
            # stream_events(version="v3") 追踪多 Agent 全链路
            for snapshot in agent.stream_events(input_data, config, version="v3"):
                if snapshot.messages:
                    for msg in snapshot.messages:
                        if msg.content and msg.type == "ai":
                            yield f"data: {json.dumps({'type':'text','content':msg.content}, ensure_ascii=False)}\n\n"
            yield 'data: {"type":"done"}\n\n'
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','content':str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                                      "X-Accel-Buffering": "no"})
```

### web/index.html — 对话 UI

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>多 Agent 徒步出行规划</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family:system-ui,sans-serif; background:#f5f5f5; height:100vh; display:flex; flex-direction:column; }
        .header { background:#2c3e50; color:white; padding:16px 24px; }
        .header h1 { font-size:18px; } .header span { font-size:12px; opacity:0.7; }
        .chat-area { flex:1; overflow-y:auto; padding:20px; }
        .message { max-width:80%; margin-bottom:16px; padding:12px 16px; border-radius:12px; line-height:1.6; white-space:pre-wrap; }
        .message.user { background:#3498db; color:white; margin-left:auto; }
        .message.ai { background:white; border:1px solid #e0e0e0; }
        .input-area { display:flex; padding:16px; background:white; border-top:1px solid #e0e0e0; }
        .input-area input { flex:1; padding:12px; border:1px solid #ddd; border-radius:8px; font-size:14px; }
        .input-area button { padding:12px 24px; margin-left:8px; background:#2c3e50; color:white; border:none; border-radius:8px; cursor:pointer; }
    </style>
</head>
<body>
    <div class="header">
        <h1>多 Agent 徒步出行规划</h1>
        <span>主 Agent 协调路线专家 / 天气专家 / 装备专家</span>
    </div>
    <div class="chat-area" id="chatArea">
        <div class="message ai">你好！告诉我你想去哪里、几天、什么难度，我来协调路线、天气、装备三个专家为你规划。</div>
    </div>
    <div class="input-area">
        <input type="text" id="messageInput" placeholder="输入消息，如：我想去川西3天的进阶路线" />
        <button id="sendBtn" onclick="sendMessage()">发送</button>
    </div>
    <script src="script.js"></script>
</body>
</html>
```

### web/script.js — 前端逻辑

```javascript
// web/script.js — SSE 流式接收主 Agent 回复
const chatArea = document.getElementById('chatArea');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
let sessionId = 'session-' + Date.now();

messageInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendMessage(); });

async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message) return;
    appendMessage('user', message);
    messageInput.value = '';
    sendBtn.disabled = true;

    const aiMsg = appendMessage('ai', '');
    try {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, session_id: sessionId }),
        });
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '', textBuffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const event = JSON.parse(line.slice(6));
                    if (event.type === 'text') {
                        textBuffer += event.content;
                        aiMsg.textContent = textBuffer;
                    } else if (event.type === 'done') {
                        sendBtn.disabled = false;
                    } else if (event.type === 'error') {
                        aiMsg.textContent = '错误: ' + event.content;
                        sendBtn.disabled = false;
                    }
                } catch (e) {}
            }
        }
    } catch (err) {
        aiMsg.textContent = '请求失败：' + err.message;
        sendBtn.disabled = false;
    }
    chatArea.scrollTop = chatArea.scrollHeight;
}

function appendMessage(role, content) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.textContent = content;
    chatArea.appendChild(div);
    chatArea.scrollTop = chatArea.scrollHeight;
    return div;
}
```

### requirements.txt

```txt
langchain>=0.3.0
langgraph>=0.3.0
fastapi>=0.115.0
uvicorn>=0.30.0
pydantic>=2.0.0
langchain-openai>=0.2.0
```

---

## 运行与测试

```bash
# 1. 安装依赖
pip install langchain langgraph fastapi uvicorn langchain-openai

# 2. 配置 API Key（如果用 OpenAI）
set OPENAI_API_KEY=your-key-here

# 3. 启动服务
uvicorn main:app --reload --port 8000

# 4. 测试
# 浏览器打开 http://localhost:8000
# 输入："我想去川西3天的进阶路线，帮我规划一下"
# 观察主 Agent 依次调用路线专家、天气专家、装备专家
```

### 预期执行流程

```
用户："我想去川西3天的进阶路线，帮我规划一下"

主 Agent 推理：
  Step 1 → ask_route_expert("川西3天进阶路线")
           路线专家内部：search_routes → 推荐"长穿毕"（进阶，45km，4668m）
           → 返回路线结论给主 Agent

  Step 2 → ask_weather_expert("川西天气")
           天气专家内部：get_weather → 晴转多云，-5~12°C，注意保暖防风
           → 返回天气结论给主 Agent

  Step 3 → ask_gear_expert("进阶难度，天气晴转多云-5~12°C")
           装备专家内部：generate_gear_list → 必备/推荐/可选三级清单
           → 返回装备清单给主 Agent

  Step 4 → 主 Agent 综合三个结论 → 完整出行规划 → SSE 流式回复
```

### 验证要点

| 验证项 | 预期结果 |
|--------|---------|
| 三个子 Agent 独立运行 | 各自能单独 invoke，返回各自领域结论 |
| 主 Agent 协调顺序 | 先路线 → 再天气 → 后装备 → 综合 |
| 上下文隔离 | 主 Agent 的 messages 里看不到 search_routes / get_weather |
| 多轮对话记忆 | 追问"那条路线详细说说"时主 Agent 记得前文 |
| SSE 流式 | 前端看到主 Agent 逐段输出 + 子 Agent 调用状态 |

---

## 动手实验

### 🟢 青铜：运行完整系统，测试单轮对话

启动服务后在 Web UI 输入：`我想去川西3天的进阶路线，帮我规划一下`

观察：
1. 主 Agent 是否依次调用了三个子 Agent
2. 最终回复是否包含路线推荐 + 天气 + 装备 + 安全提示
3. SSE 流式是否正常（逐段显示）

**验收标准：** 能看到主 Agent 按顺序调用路线→天气→装备三个专家，最终输出完整规划。

### 🟡 白银：测试多轮对话，观察 Checkpointer 记忆

用同一个 session_id 进行多轮对话：

```
第一轮：推荐川西3天进阶路线
第二轮：那条路线天气怎么样？
第三轮：我需要带什么装备？
```

观察：
1. 第二轮主 Agent 是否记得第一轮推荐的路线（Checkpointer 生效）
2. 第三轮主 Agent 是否记得前两轮的路线和天气信息
3. 主 Agent 是不是只调用需要的子 Agent，而不是每次都调全部

**进阶验证：** 换一个新的 session_id 重问第二轮，确认主 Agent 不记得上文（会话隔离生效）。

### 🔴 王者：添加第四个子 Agent（安全评估专家）

1. 创建 `agents/safety_agent.py`，系统提示词定义安全评估职责
2. 创建 `tools/safety_tools.py`，实现 `assess_safety(route_difficulty, weather, altitude)` 工具
   - 评估风险等级（低/中/高），参考 CMA 山地户外教练安全规范
   - 给出安全建议（高反预防、紧急预案、保险建议）
3. 在 `main_agent.py` 里包装成 `@tool ask_safety_expert`
4. 更新主 Agent 系统提示词，在综合规划时额外调用安全评估
5. 验证：四步协调变成五步（路线→天气→装备→安全评估→综合）

**验收标准：** 主 Agent 能协调四个子 Agent，最终规划包含安全评估章节。

---

## 踩坑记录 🕳️

### 坑 1：子 Agent 的 checkpointer 必须各自独立实例

如果三个子 Agent 共用一个 `InMemorySaver()` 实例，它们的 thread_id 会冲突——路线专家的状态可能覆盖天气专家的状态。

```python
# 错误写法：共用一个 checkpointer
shared = InMemorySaver()
route_expert = create_agent(..., checkpointer=shared)    # 危险
weather_expert = create_agent(..., checkpointer=shared)  # 串状态

# 正确写法：各自独立实例
route_expert = create_agent(..., checkpointer=InMemorySaver())
weather_expert = create_agent(..., checkpointer=InMemorySaver())
gear_expert = create_agent(..., checkpointer=InMemorySaver())
```

### 坑 2：stream_events 在多 Agent 场景下事件量爆炸

单 Agent 的 stream_events 输出就不少，多 Agent 场景下每个子 Agent 的内部 ReAct 循环都会刷出来——三个子 Agent 加起来可能上百条 event。**解决：** 前端做节流处理，只关注主 Agent 的 tool_call（调了哪个子 Agent）、子 Agent 的最终返回、主 Agent 的综合输出文本。Day 06 踩坑记录里的过滤技巧同样适用。

### 坑 3：子 Agent 包装 tool 的 docstring 决定主 Agent 何时调用

主 Agent 不知道"路线专家"这个概念，它只知道有个 `ask_route_expert` 的 tool。如果 docstring 写得模糊（比如只写"问专家"），主 Agent 就会选错。

```python
# 错误写法
@tool
def ask_gear_expert(query: str) -> str:
    """问专家。"""  # 主 Agent 不知道什么时候用

# 正确写法
@tool
def ask_gear_expert(query: str) -> str:
    """向装备专家提问，获取装备清单。
    当用户问"带什么装备""需要准备什么"时调用。
    query 需包含路线难度和天气信息。"""
```

Day 06 调试三板斧里那个实战 bug 就是这个——主 Agent 把"去川西要带什么装备"派给了路线专家，根因就是 docstring 太简略。

### 坑 4：本地模型多 Agent 的 token 消耗

用 ollama 本地模型跑多 Agent，三个子 Agent + 一个主 Agent = 四次 LLM 推理链路，一次完整规划可能触发 10+ 次 LLM 调用。**解决：** 本地开发先用 `gpt-4o-mini`（便宜快），调试通过后换本地模型。或把子 Agent 的系统提示词写得更精确，减少无效推理轮次。

---

## 副线笔记

### 全程 Claude Code 结对编程

今天全程用 Claude Code 结对编程：你做架构决策（哪些 Agent、各自什么职责、怎么编排、上下文怎么隔离），Claude Code 出第一版代码，你审查修改。

```
1. 你画架构图 → 给 Claude Code
2. 你定义每个 Agent 的职责边界 → Claude Code 生成系统提示词
3. 你定义工具签名 → Claude Code 生成工具实现
4. 你审查代码 → 修改 docstring、调整 checkpointer 配置
5. 你跑测试 → 发现问题 → Claude Code 辅助调试（Day 06 三板斧）
```

关键原则：**架构决策权在你手里。** Claude Code 擅长执行和发现边界情况，但不擅长做取舍（该用 Subagents 还是 Handoffs、子 Agent 该拆几个）。这种决策必须你来定。

### 对比 Week 06 单 Agent 版本

| 维度 | Week 06 Day 07 | Week 07 Day 07 |
|------|----------------|----------------|
| Agent 数量 | 1 个（所有工具塞给它） | 4 个（1 主 + 3 子） |
| 工具归属 | 一个 Agent 拿所有工具 | 每个子 Agent 只拿自己领域的工具 |
| 上下文 | 所有结果堆在一个 messages | 主 Agent 只看子 Agent 结论 |
| 并行能力 | 串行（一次调一个工具） | 可并行（多个子 Agent 同时跑） |
| 扩展性 | 加工具让 Agent 越来越乱 | 加子 Agent 不影响现有 Agent |
| 上下文长度 | 随工具数量线性膨胀 | 隔离后主上下文短 40-60% |

核心升级就是 Day 01 讲的：**多 Agent 的价值不在"多"，而在"分"——分的是上下文，不是工作量。**

### 上下文隔离的实际效果

用 Day 06 的 `context_eng.py` 方法量化对比（青铜实验可做）：

```
Week 06 单 Agent 主上下文：
  [system:200字] [user:20字] [tool路线:500字] [tool天气:100字] [tool装备:300字] [ai:400字]
  → 总计约 1520 字

Week 07 多 Agent 主 Agent 上下文：
  [system:200字] [user:20字] [tool路线结论:200字] [tool天气结论:150字] [tool装备结论:200字] [ai:400字]
  → 总计约 1170 字（减少 ~23%）
  子 Agent 内部多调几次工具时，Week 06 进一步膨胀，Week 07 不受影响——隔离的价值
```

---

## 检查清单

- [ ] 三个子 Agent 都能独立运行（各自能单独 invoke）
- [ ] 主 Agent 能正确协调三个子 Agent（按路线→天气→装备顺序）
- [ ] FastAPI 服务正常运行（uvicorn main:app 不报错）
- [ ] Web UI 能展示流式回复（SSE 逐段显示）
- [ ] 多轮对话记忆正常（同 session_id 追问能引用上文）
- [ ] 上下文隔离效果可见（主 Agent messages 里没有 search_routes 等底层工具名）
- [ ] 子 Agent 的 checkpointer 各自独立（不串状态）
- [ ] tool 的 docstring 清晰（主 Agent 不选错子 Agent）

---

## 本周总结

回顾 Week 07 的学习路径：

| Day | 主题 | 核心收获 |
|-----|------|---------|
| Day 01 | 为什么多 Agent + 四大模式概览 | 多 Agent 本质是上下文工程，不是"凑一起" |
| Day 02 | Subagents 模式 | 主 Agent 把子 Agent 包装成 tool，上下文隔离 |
| Day 03 | Handoffs 模式 | 控制权流转，所有 Agent 共享 messages |
| Day 04 | Router + Skills 模式 | 分类后分发，按需加载知识 |
| Day 05 | Deep Agents 高层框架 | 一行创建带文件系统的超级 Agent |
| Day 06 | Context Engineering + 调试 | 上下文工程三层决策 + 调试三板斧 |
| Day 07 | 综合实战 | 多 Agent 徒步规划系统落地 |

### 本周核心升级路径

```
Week 06：单 Agent（create_agent 调所有工具）
  → 一个 Agent 什么都能干，但工具多了就犯傻
  → 上下文膨胀、工具选择困惑、无法并行

Week 07：多 Agent（Subagents 模式）
  → 主 Agent 协调 + 子 Agent 专精
  → 上下文隔离（主 Agent 只看结论）
  → 可并行、可扩展、各司其职

核心转变：从"一个 Agent 什么都能干"到"多个专精 Agent 协作"
本质是：上下文工程——给每个 Agent 只看它需要的信息
```

### 四大模式选型决策表

| 场景 | 推荐模式 | 典型案例 |
|------|---------|---------|
| 多领域并行，主 Agent 综合 | Subagents | 路线+天气+装备（今天做的） |
| 多轮对话，角色切换 | Handoffs | 客服流转、多步骤审批 |
| 分类后分发到对应处理器 | Router | 意图分类后路由 |
| 按需加载知识/工具 | Skills | 季节性装备知识、地区指南 |
| 需要文件系统管理中间结果 | Deep Agents | 长期项目、复杂代码工程 |

### 项目代码行数（填）：________

### 最大的收获：
________________________________

### 踩过最大的坑 & 怎么解决的：
________________________________

### 还没搞懂的（诚实写）：
________________________________

### 用 Claude Code 结对编程的体验：
________________________________

---

## 下周预告

Week 08 进入 MCP 协议（Model Context Protocol）：

本周的多 Agent 系统里，工具（search_routes / get_weather / generate_gear_list）都是项目内部的 Python 函数。但真实世界里的工具分布在各处——数据库、第三方 API、文件系统、其他 Agent 服务。怎么让 Agent 跨进程、跨语言、跨服务地调用工具？这就是 MCP 要解决的问题。

MCP 是 Anthropic 提出的开放协议，2026 年已成为事实标准。本周你会：

- 理解 MCP Server / Client 模型：把工具从"项目内函数"变成"独立服务"
- 开发自定义 MCP Server：把今天的路线/天气/装备工具暴露成 MCP 工具
- 让任何 MCP Client（Claude Desktop / Cursor / 你的 Agent）都能调用你的工具
- 对比 Week 07 的 @tool 本地函数 vs MCP 远程工具的区别和取舍

```
Week 07：工具 = 项目内 @tool 函数（紧耦合）
Week 08：工具 = MCP Server 暴露的远程能力（松耦合，可复用）
```
