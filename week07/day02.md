# Day 02 — Subagents：主 Agent 协调子 Agent

## 学习目标

Day 01 我们从"为什么单 Agent 不够用"出发，过完了四大模式的概览：Subagents、Handoffs、Skills、Router。你脑子里现在应该有一张选型表——什么场景用什么模式。但"知道有四个模式"和"能动手搭一个"之间还差得远。今天我们从概览里挑出最主流的第一个模式 **Subagents** 深入拆解：主 Agent 到底怎么把子 Agent 当成一个 tool 来调用？为什么说这套机制的本质是"上下文工程"？

Subagents 是四大模式里最直觉的一种——你有一个主 Agent 充当"项目经理"，它手里攥着几个专家子 Agent（路线专家、天气专家、装备专家），用户的需求来了，主 Agent 自己不干活，而是把活派给对应专家，专家干完了把结论交回来，主 Agent 再综合回复。听起来简单，但背后的"上下文隔离"和"包装成 tool"两个设计，才是它真正强大的地方。

学完今天你能：
1. 理解 Subagents 模式的核心机制：主 Agent 把子 Agent 包装成 tool 调用，子 Agent 的内部推理过程对主 Agent 不可见
2. 掌握两种 Subagents 实现方式：tool-per-agent（每个子 Agent 一个 tool）和 single dispatch tool（一个分发 tool 路由到子 Agent），知道各自适合什么场景
3. 能用 `create_agent` 创建子 Agent 并包装成 `@tool`，再交给主 Agent 协调，跑通一个"主 Agent + 路线专家 + 天气专家"的最小系统
4. 理解 Subagents 的上下文隔离机制（主 Agent 只看结论不看过程）和并行调用能力（一步调多个子 Agent）

---

## 一、Subagents 模式详解

### 1.1 从 Day 01 的定义说起

Day 01 我们给 Subagents 下过一个定义：**主 Agent 把子 Agent 当 tool 调用**。这句话里有两个关键词需要拆开看。

第一个是"子 Agent"。子 Agent 不是一个普通函数，它本身就是一个完整的 `create_agent` 产物——有自己的模型、自己的工具、自己的 system_prompt、自己的 checkpointer。它内部会跑完整的 Agent 循环（LLM 思考 → 调工具 → 看结果 → 再思考），是一个有自主推理能力的"小号 Agent"。

第二个是"当 tool 调用"。主 Agent 并不直接知道有"路线专家"这个 Agent 存在，它只知道手里有一个叫 `ask_route_expert` 的 tool。这个 tool 的实现细节是——内部去 invoke 一次路线专家 Agent，拿到它的最终回复，把这个回复当作 tool 的返回值交还给主 Agent。对主 Agent 来说，调用这个 tool 和调用一个 `get_weather` 函数没有任何区别。

### 1.2 核心机制图解

用一个徒步规划的场景把整条调用链画出来：

```
用户问："川西3天路线和天气怎么样？"
  │
  ▼
┌─────────────────────────────────────────────────┐
│  主 Agent（徒步规划主助手）                      │
│  手里两个 tool：ask_route_expert / ask_weather   │
│                                                 │
│  LLM 思考：这题要查路线 + 查天气，同时调两个 tool  │
│  ↓ tool_call: ask_route_expert("川西3天路线")    │
│  ↓ tool_call: ask_weather_expert("川西天气")     │
└─────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
┌──────────────────┐          ┌──────────────────┐
│ 路线专家子 Agent  │          │ 天气专家子 Agent  │
│ tools: search_   │          │ tools: get_      │
│        routes    │          │        weather   │
│                  │          │                  │
│ 内部循环：        │          │ 内部循环：        │
│ LLM → 调路线工具  │          │ LLM → 调天气工具  │
│ → 看结果 → 总结   │          │ → 看结果 → 总结   │
│ → 返回路线结论    │          │ → 返回天气结论    │
└──────────────────┘          └──────────────────┘
        │                              │
        └──────────┬───────────────────┘
                   ▼
        主 Agent 收到两个 tool 返回值
        （只有结论，没有子 Agent 内部过程）
                   │
                   ▼
        主 Agent 综合两份结论 → 回复用户
        "川西3天推荐 D1 成都→康定..."
```

整条链路的精髓在于：主 Agent 的 messages 里只会出现两个 tool 的返回值（路线结论 + 天气结论），它完全看不到子 Agent 内部"先调了路线工具、看了结果、又调了一次、最后总结"这种细节。这就是上下文隔离。

### 1.3 上下文隔离：Subagents 的核心价值

为什么要隔离？先看反例——单 Agent 方案。

如果不用 Subagents，把路线工具和天气工具都塞给一个单 Agent，它的 messages 会变成这样：

```
[单 Agent 的 messages ——又长又乱]
├── user: 川西3天路线和天气怎么样？
├── ai: 我先查路线 (tool_call: search_routes)
├── tool: 找到 5 条路线，详情：①成都→康定→新都桥...
├── ai: 再查天气 (tool_call: get_weather)
├── tool: 川西未来3天：多云转晴，气温 5-18°C...
├── ai: 再查第二条路线的天气...
├── tool: ...
├── ai: 综合以上，我的推荐是...
```

每个工具的原始返回值（可能是大段 JSON、长文本）都堆在 messages 里，LLM 每次思考都要把这些"过程垃圾"重新过一遍。工具越多、调用越多次，上下文就越臃肿，模型越容易"犯傻"——忘记上文、选错工具、推理混乱。这正是 Day 01 讲过的"单 Agent 上下文爆炸"问题。

换成 Subagents，主 Agent 的 messages 长这样：

```
[Subagents 主 Agent 的 messages ——干净]
├── user: 川西3天路线和天气怎么样？
├── ai: 我同时问路线专家和天气专家 (两个 tool_call)
├── tool(ask_route_expert): 川西3天推荐路线：D1 成都→康定...
├── tool(ask_weather_expert): 川西未来3天：多云转晴...
├── ai: 综合两位专家，我的规划是...
```

主 Agent 只看到两个"浓缩后的结论"，子 Agent 内部那些"调了路线工具、看了 JSON、又调了一次"的过程，全部留在子 Agent 自己的 messages 里，对主 Agent 不可见。

对比一下两种方案的上下文负担：

| 维度 | 单 Agent | Subagents |
|------|---------|-----------|
| 主上下文里的工具返回 | 原始数据（可能几百上千 token） | 浓缩结论（几十 token） |
| 工具调用过程是否可见 | 全部堆在 messages 里 | 隔离在子 Agent 内部 |
| 上下文增长 | 随工具调用次数线性膨胀 | 只按子 Agent 数量增长 |
| 模型注意力分散 | 容易被过程数据干扰 | 只关注结论，注意力集中 |

> **直觉类比：** 单 Agent 像一个项目经理亲自去跑每个工地的测量、搬砖、记录——所有原始数据堆在他脑子里；Subagents 像项目经理只听各专业组长的"一句话汇报"，原始数据留在专业组那里。项目经理的脑子永远清爽，能专注做"综合决策"。

---

## 二、两种实现方式

把子 Agent 包装成 tool 有两种常见做法，理解它们的差异能让你在不同场景下做出正确选型。

### 2.1 Tool-per-agent 模式（推荐入门）

最直觉的实现：**每个子 Agent 对应一个独立的 `@tool` 函数**。tool 内部做两件事——invoke 一次对应的子 Agent，提取最终回复返回给主 Agent。

这种方式的优点是"一眼能看懂"：主 Agent 手里的 tool 列表就是它的专家清单，每个 tool 名字和 docstring 直接告诉 LLM"我是个路线专家，找路线来问我"。

完整代码示例：

```python
"""
Subagents 模式：tool-per-agent 实现
主 Agent + 路线专家子 Agent + 天气专家子 Agent
"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

# -------- 公共模型 --------
model = init_chat_model("gpt-4o-mini", temperature=0)

# -------- 子 Agent 的底层工具 --------

@tool
def search_routes(destination: str, days: int) -> str:
    """搜索指定目的地的徒步路线。destination 为目的地，days 为天数。"""
    # 演示用 mock 数据，生产环境接真实路线 API
    routes_db = {
        "川西": "D1 成都→康定(折多山口)→新都桥；D2 新都桥→塔公草原→八美；D3 八美→丹巴藏寨→返程",
        "雨崩": "D1 飞来寺→西当→上雨崩；D2 上雨崩→冰湖→上雨崩；D3 上雨崩→神瀑→西当",
    }
    key = destination if destination in routes_db else "川西"
    return routes_db.get(key, f"{destination} 暂无路线数据，建议参考川西路线")


@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前及未来天气。city 为城市名称。"""
    weather_db = {
        "成都": "多云转晴，5-18°C，风力2级",
        "康定": "晴，2-12°C，紫外线强",
        "雨崩": "小雨，3-10°C，需防雨装备",
    }
    return weather_db.get(city, f"{city}：暂无天气数据")


# -------- 子 Agent 1：路线专家 --------
route_expert = create_agent(
    model=model,
    tools=[search_routes],
    system_prompt=(
        "你是徒步路线专家，擅长根据用户的目的地和天数推荐路线。"
        "调用 search_routes 工具获取路线数据后，给出清晰的日程安排。"
        "回答要简洁，只给路线结论，不要寒暄。"
    ),
    checkpointer=InMemorySaver(),   # 注意：独立实例，不和主 Agent 共用
)

# -------- 子 Agent 2：天气专家 --------
weather_expert = create_agent(
    model=model,
    tools=[get_weather],
    system_prompt=(
        "你是天气查询专家，擅长查目的地天气并给出穿衣/装备建议。"
        "调用 get_weather 工具后，简洁汇报天气和注意事项。"
    ),
    checkpointer=InMemorySaver(),   # 同样独立实例
)

# -------- 把子 Agent 包装成 tool --------

@tool
def ask_route_expert(query: str) -> str:
    """向路线专家提问，获取徒步路线推荐。当用户需要路线规划时调用。query 为路线相关的需求描述。"""
    result = route_expert.invoke({"messages": [{"role": "user", "content": query}]})
    # 子 Agent 返回的是 dict，提取最后一条 AI message 的 content
    return result["messages"][-1].content


@tool
def ask_weather_expert(query: str) -> str:
    """向天气专家提问，获取目的地天气信息。当用户需要查天气时调用。query 为天气相关的需求描述。"""
    result = weather_expert.invoke({"messages": [{"role": "user", "content": query}]})
    return result["messages"][-1].content


# -------- 主 Agent --------
main_agent = create_agent(
    model=model,
    tools=[ask_route_expert, ask_weather_expert],
    system_prompt=(
        "你是徒步规划主助手，负责协调路线专家和天气专家。"
        "当用户同时需要路线和天气时，请同时调用两个专家。"
        "拿到专家的结论后，综合给出完整的出行规划建议。"
    ),
    checkpointer=InMemorySaver(),
)


# -------- 运行 --------
if __name__ == "__main__":
    from uuid import uuid7

    config = {"configurable": {"thread_id": str(uuid7())}}

    result = main_agent.invoke(
        {"messages": [{"role": "user", "content": "川西3天路线和天气怎么样？"}]},
        config=config,
    )
    print("=== 主 Agent 最终回复 ===")
    print(result["messages"][-1].content)
```

跑起来后，主 Agent 的 messages 里只会出现两个 tool 的返回值（路线结论 + 天气结论），而子 Agent 内部调 `search_routes` 和 `get_weather` 的过程，主 Agent 完全看不到。

### 2.2 Single dispatch tool 模式

当子 Agent 数量变多（比如路线、天气、装备、住宿、交通五六个专家），tool-per-agent 模式会让主 Agent 手里的 tool 列表也跟着膨胀。LLM 在一堆工具里挑对工具的准确率会下降——这又回到了单 Agent"工具太多就犯傻"的老问题。

Single dispatch tool 模式的思路是：**只用一个 `@tool` 做路由分发**，它接收一个 `expert_type` 参数，内部根据这个参数选择调用哪个子 Agent。主 Agent 手里永远只有一个 tool，不用在多个工具间纠结。

```python
"""
Subagents 模式：single dispatch tool 实现
用一个 @tool 路由到多个子 Agent
"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

model = init_chat_model("gpt-4o-mini", temperature=0)

# -------- 子 Agent 的底层工具（同上，此处省略 search_routes / get_weather 定义） --------
# 假设 search_routes、get_weather、get_gear_list 三个底层工具已定义

@tool
def get_gear_list(activity: str) -> str:
    """查询指定活动的装备清单。activity 为活动类型，如 hiking/camping。"""
    return "徒步基础装备：登山鞋、冲锋衣、登山杖、头灯、急救包"

# -------- 三个子 Agent --------
route_expert = create_agent(model=model, tools=[search_routes],
                            system_prompt="你是路线专家，简洁给路线结论。",
                            checkpointer=InMemorySaver())

weather_expert = create_agent(model=model, tools=[get_weather],
                              system_prompt="你是天气专家，简洁报天气。",
                              checkpointer=InMemorySaver())

gear_expert = create_agent(model=model, tools=[get_gear_list],
                           system_prompt="你是装备专家，简洁列装备清单。",
                           checkpointer=InMemorySaver())

# -------- 一个分发 tool 搞定所有专家 --------
@tool
def dispatch_to_expert(expert_type: str, query: str) -> str:
    """
    分发给对应领域的专家处理。expert_type 取值：route（路线）/ weather（天气）/ gear（装备）。
    query 为具体问题。根据用户需求选择合适的专家类型。
    """
    experts = {
        "route": route_expert,
        "weather": weather_expert,
        "gear": gear_expert,
    }
    expert = experts.get(expert_type)
    if not expert:
        return f"未知专家类型: {expert_type}，可选: {list(experts.keys())}"
    result = expert.invoke({"messages": [{"role": "user", "content": query}]})
    return result["messages"][-1].content

# -------- 主 Agent 只有一个 tool --------
main_agent = create_agent(
    model=model,
    tools=[dispatch_to_expert],    # 无论多少专家，主 Agent 永远只有一个 tool
    system_prompt=(
        "你是徒步规划主助手，通过 dispatch_to_expert 调用不同专家。"
        "用户需要路线就传 expert_type=route，需要天气就传 weather，需要装备就传 gear。"
        "可以多次调用 dispatch_to_expert 来协调多个专家。"
    ),
    checkpointer=InMemorySaver(),
)
```

注意这里有个取舍：dispatch 模式下主 Agent 一次只能调一个专家（一个 tool_call 只能带一组参数），所以并行性不如 tool-per-agent。如果需要并行，主 Agent 得在多个步骤里连续调用 dispatch。

### 2.3 两种方式对比

| 维度 | tool-per-agent | single dispatch tool |
|------|---------------|---------------------|
| 主 Agent 的工具数量 | 每个子 Agent 一个，数量随专家增长 | 永远只有 1 个 dispatch tool |
| 主 Agent 上下文负担 | tool 列表变长（每个 tool 的 schema 都要塞进 prompt） | tool 列表恒定，schema 固定 |
| 路由方式 | LLM 直接从多个 tool 里选 | LLM 选 expert_type 参数，由 tool 内部路由 |
| 并行调用 | 天然支持，一步返回多个 tool_call | 较弱，需多次调用 dispatch |
| 路由出错风险 | 选错 tool | 选错 expert_type 字符串 |
| 适用场景 | 子 Agent 少（2-4 个），需要并行 | 子 Agent 多（5+ 个），主上下文要省 |
| 实现复杂度 | 简单直观 | 需要维护专家字典和路由逻辑 |

选型建议：**入门和需要并行的场景用 tool-per-agent；专家数量多、主 Agent 上下文要精简的场景用 single dispatch**。两者不互斥，可以混用——核心专家用独立 tool 保证并行，边缘专家塞进 dispatch 减少工具数量。

---

## 三、上下文隔离与并行调用

### 3.1 上下文隔离实测

"上下文隔离"听起来抽象，我们用一个具体实验把它量化。同一个问题"川西3天路线和天气"，分别用单 Agent 和 Subagents 跑，对比主上下文的 messages 长度。

```python
"""
上下文隔离实测：对比单 Agent vs Subagents 的主上下文长度
"""
# ---- 方案 A：单 Agent，所有工具塞给它 ----
single_agent = create_agent(
    model=model,
    tools=[search_routes, get_weather],
    system_prompt="你是徒步规划助手，用 search_routes 查路线，用 get_weather 查天气。",
    checkpointer=InMemorySaver(),
)

result_a = single_agent.invoke(
    {"messages": [{"role": "user", "content": "川西3天路线和天气怎么样？"}]},
    config={"configurable": {"thread_id": "single"}},
)
messages_a = result_a["messages"]

# ---- 方案 B：Subagents（即第二节的 main_agent）----
result_b = main_agent.invoke(
    {"messages": [{"role": "user", "content": "川西3天路线和天气怎么样？"}]},
    config={"configurable": {"thread_id": "sub"}},
)
messages_b = result_b["messages"]

# ---- 对比 ----
print(f"单 Agent messages 条数: {len(messages_a)}")
print(f"Subagents 主 Agent messages 条数: {len(messages_b)}")

# 估算 token：粗略按字符数 / 1.5（中文 token 系数）
def estimate_tokens(messages):
    total = sum(len(m.content) if hasattr(m, "content") else 0 for m in messages)
    return int(total / 1.5)

print(f"单 Agent 估算 token: ~{estimate_tokens(messages_a)}")
print(f"Subagents 主 Agent 估算 token: ~{estimate_tokens(messages_b)}")
```

实测结果（mock 数据，数字会因模型和工具返回而变）：

| 方案 | messages 条数 | 估算 token | 主上下文里能看到的内容 |
|------|--------------|-----------|---------------------|
| 单 Agent | ~7 条 | ~320 token | 路线工具原始返回 + 天气工具原始返回 + 中间推理 |
| Subagents 主 Agent | ~4 条 | ~150 token | 路线专家结论 + 天气专家结论 |

关键差异：单 Agent 的 messages 里有完整的 `search_routes` 原始返回（可能是一大段路线 JSON）和 `get_weather` 原始返回，Subagents 的主 Agent 只看到专家"浓缩后的一句话结论"。当底层工具返回的数据越复杂（比如真实路线 API 返回几十条带坐标的路线），这个隔离带来的 token 节省就越明显。

再看看子 Agent 内部长什么样——主 Agent 看不到的"过程"都堆在这里：

```python
# 主 Agent 看不到子 Agent 的内部 messages，但我们可以单独查
# 看 route_expert 自己跑完后的完整 messages
route_result = route_expert.invoke(
    {"messages": [{"role": "user", "content": "川西3天路线"}]},
    config={"configurable": {"thread_id": "route-internal"}},
)
print(f"路线专家内部 messages 条数: {len(route_result['messages'])}")
# 这里包含：user 输入、ai 的 tool_call、tool 的原始返回、ai 的总结
# 这些全部留在子 Agent 内部，主 Agent 一无所见
```

这就是上下文隔离的本质：**子 Agent 把"调工具看结果再总结"的脏活全揽了，只把干净的结论递给主 Agent**。主 Agent 永远只关心"我要问什么"和"专家给了什么结论"，不被过程数据干扰。

### 3.2 并行调用

Subagents 模式天然支持并行——主 Agent 的 LLM 在一步内可以返回多个 tool_call，如果这些 tool_call 分别是 `ask_route_expert` 和 `ask_weather_expert`，create_agent 内部会并行执行它们。

```
主 Agent 一步返回两个 tool_call：
  tool_call[0]: ask_route_expert("川西3天路线")
  tool_call[1]: ask_weather_expert("川西天气")

两个子 Agent 同时跑（并行）：
  路线专家内部循环 ──┐
                     ├─ 并行 ──→ 各自返回结论
  天气专家内部循环 ──┘

主 Agent 收齐两个结论 → 综合回复
```

对比串行调用，并行的好处是延迟降低——两个专家同时干活，总耗时约等于较慢那个的耗时，而不是两者之和。

用 async/await 可以让并行更可控（特别是当子 Agent 的工具本身是异步 API 调用时）：

```python
"""
并行调用：主 Agent 一步调多个子 Agent
"""
import asyncio

async def run_parallel():
    # 当主 Agent 的 LLM 同时返回 ask_route_expert 和 ask_weather_expert 时
    # create_agent 内部会并行执行这两个 tool
    # 如果 tool 函数本身是 async 的，并行效果更好
    result = await main_agent.ainvoke(
        {"messages": [{"role": "user", "content": "川西3天路线和天气怎么样？"}]},
        config={"configurable": {"thread_id": "parallel"}},
    )
    print(result["messages"][-1].content)

# 也可以手动并行 invoke 两个子 Agent（绕过主 Agent，纯做对比测试）
async def manual_parallel():
    """手动并行调两个子 Agent，测延迟"""
    import time
    start = time.time()

    # asyncio.gather 并行执行
    route_task = route_expert.ainvoke(
        {"messages": [{"role": "user", "content": "川西3天路线"}]},
        config={"configurable": {"thread_id": "r1"}},
    )
    weather_task = weather_expert.ainvoke(
        {"messages": [{"role": "user", "content": "川西天气"}]},
        config={"configurable": {"thread_id": "w1"}},
    )
    route_res, weather_res = await asyncio.gather(route_task, weather_task)

    elapsed = time.time() - start
    print(f"并行总耗时: {elapsed:.2f}s")
    print("路线:", route_res["messages"][-1].content)
    print("天气:", weather_res["messages"][-1].content)

if __name__ == "__main__":
    asyncio.run(run_parallel())
    asyncio.run(manual_parallel())
```

并行调用的注意事项：

| 关注点 | 说明 |
|-------|------|
| LLM 是否返回多个 tool_call | 取决于模型能力，GPT-4o 系列通常能一步返回多个，弱模型可能串行 |
| 子 Agent 是否线程安全 | 并行调用时各子 Agent 用独立 thread_id，避免 checkpointer 写冲突 |
| 共享资源竞争 | 如果多个子 Agent 都调同一个外部 API（比如同一个搜索接口），注意限流 |
| 错误隔离 | 一个子 Agent 失败不应拖垮整个调用，tool 内部 try/except 兜底 |

---

## 动手实验

### 🟢 青铜：观察上下文隔离效果

把第一节 `tool-per-agent` 的完整代码跑起来，重点不是看主 Agent 的回复，而是**对比 messages 长度**：

1. 跑通主 Agent，打印 `result["messages"]`，数一数主上下文有几条消息
2. 单独 invoke 一次 `route_expert`，打印它的 `result["messages"]`，数一数子 Agent 内部有几条
3. 验证：主 Agent 的 messages 里是否出现了 `search_routes` 这个底层工具的名字？（答案：不应该出现，它只看到 `ask_route_expert` 的返回值）
4. 把主 Agent 的 messages 总字符数和子 Agent 内部 messages 总字符数对比，体会"结论 vs 过程"的体量差异

### 🟡 白银：完成 subagents_demo.py

把第二节的两段代码整合成一个可运行的 `subagents_demo.py`，实现完整场景：

- 定义 `search_routes`、`get_weather` 两个底层工具（可以用 mock 数据）
- 创建路线专家、天气专家两个子 Agent
- 把两个子 Agent 包装成 `ask_route_expert`、`ask_weather_expert` 两个 `@tool`
- 创建主 Agent 协调这两个 tool
- 用户问"川西3天路线和天气"，主 Agent 应该**同时**调用两个专家（观察是否并行），综合两份结论后回复
- 额外：在主 Agent 回复后，打印主 Agent 的 messages 和子 Agent 的 messages，用具体数字记录上下文隔离效果

进阶要求：换一个需要多轮的问题，比如"先查川西路线，再根据路线上的城市查天气"，观察主 Agent 如何分步协调两个专家。

### 🔴 王者：对比两种方式的 token 消耗和响应时间

实现 single dispatch tool 模式（加一个 gear 装备专家），和 tool-per-agent 模式做对比：

1. 同一个问题（比如"川西3天需要路线、天气、装备"），分别用两种模式跑
2. 用 `time` 模块记录两种模式的响应时间
3. 用 `usage_metadata`（如果模型返回）或字符数估算 token 消耗，对比主 Agent 上下文负担
4. 思考并记录：哪种模式并行性更好？哪种主上下文更省？什么情况下你会切换模式？
5. 进阶：把对比结果整理成一张表，作为你后续选型的决策依据

---

## 踩坑记录 🕳️

### 坑 1：子 Agent 的 checkpointer 和主 Agent 共用了同一个实例

```python
# ❌ 错误：主子 Agent 共用一个 checkpointer
shared_saver = InMemorySaver()
route_expert = create_agent(model=model, tools=[...], checkpointer=shared_saver)
main_agent = create_agent(model=model, tools=[...], checkpointer=shared_saver)
```

后果：主 Agent 和子 Agent 的会话状态写到同一个 checkpointer 里，thread_id 一旦相同就会串状态——子 Agent 可能读到主 Agent 的对话历史，或者主 Agent 被子 Agent 的内部消息污染，行为完全不可预测。

**解决：** 每个子 Agent 用独立的 `InMemorySaver()` 实例，主 Agent 也是一个独立实例。它们各自管理自己的会话状态，互不干扰。如果需要共享长期记忆，用 `InMemoryStore` 而不是 checkpointer。

### 坑 2：子 Agent 返回的是 dict，直接当字符串用报错

```python
# ❌ 错误：把子 Agent 的返回值当字符串
@tool
def ask_route_expert(query: str) -> str:
    result = route_expert.invoke({"messages": [...]})
    return result          # result 是 dict，不是 str

# ✅ 正确：提取最后一条 AI message 的 content
@tool
def ask_route_expert(query: str) -> str:
    result = route_expert.invoke({"messages": [...]})
    return result["messages"][-1].content
```

**解决：** `create_agent` 返回的是 `dict`，里面有 `messages` 列表。子 Agent 的最终回复在 `result["messages"][-1].content`。`[-1]` 是最后一条消息（AI 的最终回复），`.content` 是文本内容。这一步是包装子 Agent 时最容易漏的。

### 坑 3：tool 的 docstring 太简略，主 Agent 不知道何时调用

```python
# ❌ 错误：docstring 太简略
@tool
def ask_route_expert(query: str) -> str:
    """问路线专家。"""
    ...

# ✅ 正确：写清"什么时候用"和"参数是什么"
@tool
def ask_route_expert(query: str) -> str:
    """向路线专家提问，获取徒步路线推荐。当用户需要路线规划时调用。query 为路线相关的需求描述。"""
    ...
```

**解决：** 主 Agent 的 LLM 是靠 tool 的 docstring 决定"什么时候调这个 tool"和"传什么参数"的。docstring 里要写清两点：**什么时候用这个工具**（触发条件）、**参数是什么含义**（输入描述）。这是 Week 06 Day 02 `@tool` 那天就强调过的，在 Subagents 里更要严格执行——因为这里的 tool 背后是整个子 Agent，调错的成本更高。

### 坑 4：并行调用时子 Agent 的 thread_id 撞车

并行调用多个子 Agent 时，如果它们的 invoke 用了相同的 `thread_id`，会因为并发写 checkpointer 导致状态混乱。

```python
# ❌ 错误：两个子 Agent 用同一个 thread_id
route_expert.invoke(..., config={"configurable": {"thread_id": "shared"}})
weather_expert.invoke(..., config={"configurable": {"thread_id": "shared"}})  # 撞车

# ✅ 正确：每个子 Agent 调用用不同的 thread_id
route_expert.invoke(..., config={"configurable": {"thread_id": "route-001"}})
weather_expert.invoke(..., config={"configurable": {"thread_id": "weather-001"}})
```

**解决：** 包装 tool 时，给每次子 Agent 调用生成一个独立的 thread_id（比如用 `uuid`）。这样即便并行调用，每个子 Agent 的会话状态也互不干扰。

### 坑 5：子 Agent 自己也"不调工具直接回答"

子 Agent 收到 query 后，LLM 可能觉得"我知道答案，不用调工具"，直接输出文本——这就失去了子 Agent 包装底层工具的意义。

**解决：** 在子 Agent 的 system_prompt 里明确指令"必须先调用 xxx 工具获取数据再回答"。同时检查模型能力（本地小模型经常不主动调工具，换 7B+ 或云端模型）。这个坑和 Week 06 单 Agent 不调工具是同一个根因，只是现在出现在子 Agent 身上。

---

## 副线笔记

### 分析 Claude Code 的 Subagents 架构

今天的副线是拿一个真实的多 Agent 产品来印证我们学的 Subagents 模式——Anthropic 的 Claude Code。它是一个终端里的 AI 编程助手，架构上就是典型的 Subagents 模式。

Claude Code 的主 Agent 是你和它对话的那个"总助手"，它背后协调着几个专门的子 Agent：

```
你（用户）在终端里提问
   │
   ▼
Claude Code 主 Agent（总控）
   │  手里有几个 tool，每个 tool 背后是一个子 Agent
   ├── 代码搜索子 Agent：在代码库里 grep / 语义检索，返回相关代码片段
   ├── 测试子 Agent：跑测试、分析失败原因，返回测试结论
   └── 审查子 Agent：审查代码变更，返回审查意见
   │
   ▼
主 Agent 综合各子 Agent 的结论 → 给你回复
```

关键观察——它和我们今天实现的 Subagents 模式高度一致：

| 维度 | Claude Code 的做法 | 我们今天的实现 |
|------|-------------------|--------------|
| 子 Agent 独立上下文 | 每个子 Agent 有独立 messages，不污染主 Agent | 每个子 Agent 独立 checkpointer + 独立 messages |
| 主 Agent 只看结论 | 主 Agent 只收到子 Agent 的"汇报"，看不到搜索过程 | 主 Agent 只看 tool 返回值，看不到子 Agent 内部 tool_call |
| 上下文工程 | 主 Agent 上下文保持精简，专注综合决策 | 同理，主上下文只存结论 |
| 包装成 tool | 主 Agent 把"调子 Agent"当成一个 tool | `@tool` 包装子 Agent 的 invoke |

但也有一些差异值得思考：

1. **子 Agent 的粒度**：Claude Code 的子 Agent 不是"一个专家一个"，而是按"任务类型"划分——搜索是一类、测试是一类。这更接近 tool-per-agent 模式，因为每个子 Agent 职责清晰且可能并行。

2. **子 Agent 的自主性**：Claude Code 的子 Agent 内部还能再调工具（比如搜索子 Agent 内部可能用 grep、用 ripgrep、用语义检索），和我们子 Agent 内部跑完整 Agent 循环一样。

3. **错误隔离**：如果搜索子 Agent 没找到结果，主 Agent 不会崩溃，而是换个策略或告诉你"没找到"。我们今天的实现里，tool 内部也应该 try/except 兜底，避免一个子 Agent 报错拖垮整个调用。

**今日观察任务：**

- 用 Claude Code（或任何你能接触到的多 Agent AI 编程工具）处理一个需要"搜索代码 + 跑测试"的任务
- 观察它的输出里，主回复是否只包含子 Agent 的结论，而不包含子 Agent 内部的搜索/测试过程
- 对照我们今天实现的 Subagents，找一找：它的子 Agent 划分是按 tool-per-agent 还是 dispatch？主上下文是否做到了隔离？
- 思考：如果你要给 Claude Code 加一个"部署子 Agent"，它的 system_prompt 和工具该长什么样？

---

## 检查清单

- [ ] 理解 Subagents 的核心机制：主 Agent 把子 Agent 包装成 tool，子 Agent 内部跑完整 Agent 循环
- [ ] 实现了 tool-per-agent 模式：每个子 Agent 对应一个 `@tool`，主 Agent 手里有多个 tool
- [ ] 实现了 single dispatch tool 模式：一个 `@tool` 内部路由到多个子 Agent
- [ ] 观察到上下文隔离效果：主 Agent 的 messages 只有结论，子 Agent 内部的工具调用过程不可见
- [ ] 理解并行调用：主 Agent 一步返回多个 tool_call 时，多个子 Agent 可以并行执行
- [ ] 知道两种方式的取舍：tool-per-agent 适合少专家 + 并行，dispatch 适合多专家 + 主上下文精简
- [ ] 记住了踩坑：子 Agent 用独立 checkpointer、返回值要提取 `.content`、docstring 要写清触发条件
- [ ] 对照 Claude Code 的 Subagents 架构，理解工业级产品和今天实现的对应关系

---

## 下课预告

今天我们实现的 Subagents 有个共同特点——**主 Agent 始终握着控制权**，子 Agent 干完活就把结论交回来，主 Agent 综合后回复用户。这种"集中调度"模式适合主 Agent 要做综合决策的场景。

但如果场景变成"用户先跟客服聊，聊到技术问题就交接给技术支持，技术支持处理完再交接回客服"——这种**控制权在多个 Agent 间流转**的场景，Subagents 就不合适了，因为它的主 Agent 一直把控全局。

Day 03 我们学 **Handoffs 模式**——另一种多 Agent 协作方式。它和 Subagents 最大的区别是：控制权会从一个 Agent "交接"给另一个 Agent，用户直接和当前握有控制权的 Agent 对话。我们会对比 Subagents vs Handoffs 的本质差异，搞清楚什么场景该用哪个。
