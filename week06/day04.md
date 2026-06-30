# Day 04 — LangGraph 进阶：条件边 / 循环 / create_react_agent

## 学习目标

Day 03 我们用 `StateGraph` 画出了第一张图，但那张图只会"一条道走到黑"——所有边都是固定的 `A → B`，既不会分叉也不会回头。今天给图装上两件武器：**条件边**让它会分叉，**循环边**让它会回头。这两件武器一组合，就能把 Day 02 那个 `while True: 调模型 → 解析 tool_calls → 执行 → 回传` 的隐式循环，改写成一张 `agent ↔ tools` 的显式循环图——这正是本周的高潮：用图重写 Week 03 的 Agent Loop。最后用 `create_react_agent` 一行起手，看清楚高层 API 内部其实就是我们亲手搭的那张循环图。

学完今天你能：
1. 用 `add_conditional_edges` 写出根据 state 动态分流的条件边，并说清 router 函数、path_map、返回字符串三者的对应关系
2. 把 Day 02 的 `while` 工具循环改写成 `agent → tools → agent` 的 LangGraph 循环图，跑通一个完整可运行的 ReAct Agent
3. 说清 `recursion_limit`（默认 25）的作用，并把它和 Week 03 `agent_loop.py` 的 `max_turns` 对应起来
4. 用 `create_react_agent(model, tools)` 一行创建 ReAct Agent，并判断什么场景该手写图、什么场景该用高层 API

---

## 一、条件边 add_conditional_edges：让图会"分流"

### 1.1 Day 03 的边只会"直走"

Day 03 学的边都是固定的：`graph.add_edge("classify", "respond")`——`classify` 跑完**一定**去 `respond`，没有任何商量余地。但真实 Agent 的控制流几乎都要分叉：

- 用户问技术问题 → 走"技术回复"节点；问闲聊 → 走"闲聊回复"节点
- 模型返回了 `tool_calls` → 走"执行工具"节点；没返回 → 走 `END`
- 检索结果置信度高 → 直接生成；置信度低 → 追加一轮检索

这种"看状态决定去哪"的边，就是**条件边（conditional edge）**。

### 1.2 add_conditional_edges 三要素

```python
graph.add_conditional_edges(
    "source_node",      # ① 源节点：从哪个节点出来时判断
    router_fn,          # ② 路由函数：接收 state，返回一个字符串（路由键）
    {"path_a": "node_a", "path_b": "node_b"},  # ③ path_map：路由键 → 目标节点名
)
```

三个要素的职责：

| 要素 | 作用 | 谁来写 |
|------|------|--------|
| **源节点** | 条件边挂在哪个节点后面，执行完该节点后触发路由 | 你指定字符串 |
| **路由函数 router_fn** | 读 state，返回一个字符串决定走哪条路 | 你写，签名 `def router(state) -> str` |
| **path_map** | 把路由函数返回的字符串映射到具体目标节点名 | 你提供字典；不写则默认返回值即节点名 |

执行流程：源节点跑完 → LangGraph 调 `router_fn(state)` 拿到返回字符串 → 查 path_map → 走到对应目标节点。

### 1.3 简单分支示例：按问题类别路由

```python
"""条件边示例：根据用户问题类别路由到不同回复节点"""
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages


class RouteState(TypedDict):
    messages: Annotated[list, add_messages]
    category: str   # 路由依据：分类标签（覆盖式）


# ── 节点 1：分类（纯规则，不调 LLM）──
def classify_node(state: RouteState) -> dict:
    """根据最后一条消息判断类别，写入 category 字段。"""
    last = state["messages"][-1].content
    if any(kw in last for kw in ["代码", "Python", "报错", "LangGraph"]):
        category = "tech"
    elif any(kw in last for kw in ["你好", "天气", "吃饭"]):
        category = "chat"
    else:
        category = "other"
    return {"category": category}


# ── 节点 2/3/4：三类不同的回复 ──
def tech_reply(state: RouteState) -> dict:
    return {"messages": [("assistant", "这是技术问题，我来帮你查代码。")]}

def chat_reply(state: RouteState) -> dict:
    return {"messages": [("assistant", "闲聊很开心呀！")]}

def other_reply(state: RouteState) -> dict:
    return {"messages": [("assistant", "我会尽力回答。")]}


# ── 路由函数：读 category，返回路由键 ──
def route_by_category(state: RouteState) -> str:
    """根据 category 返回对应的路由键。"""
    return state["category"]   # "tech" / "chat" / "other"


# ── 建图 ──
graph = StateGraph(RouteState)
graph.add_node("classify", classify_node)
graph.add_node("tech_reply", tech_reply)
graph.add_node("chat_reply", chat_reply)
graph.add_node("other_reply", other_reply)

graph.add_edge(START, "classify")
# 条件边：classify 跑完，按 route_by_category 的返回值分流
graph.add_conditional_edges(
    "classify",
    route_by_category,
    {"tech": "tech_reply", "chat": "chat_reply", "other": "other_reply"},
)
# 三个回复节点都通向 END
graph.add_edge("tech_reply", END)
graph.add_edge("chat_reply", END)
graph.add_edge("other_reply", END)

app = graph.compile()
```

对应的 ASCII 分支图：

```
                        ┌─(tech)──► ┌────────────┐ ──► END
                        │           │ tech_reply  │
            ┌──────────┐│           └────────────┘
 START ───► │ classify ├┤
            └──────────┘│           ┌────────────┐ ──► END
                        ├─(chat)──► │ chat_reply  │
                        │           └────────────┘
                        │           ┌────────────┐ ──► END
                        └─(other)─► │ other_reply │
                                    └────────────┘

  router_fn 返回 "tech"  → 走 tech_reply
  router_fn 返回 "chat"  → 走 chat_reply
  router_fn 返回 "other" → 走 other_reply
```

> **对比 Day 03：** Day 03 的"分类 → 回复"是单线 `classify → respond`，分类结果 `category` 写进 state 后**没人用**。今天条件边把 `category` 真正用起来——它就是路由的依据。Day 03 结尾预告里那张"三分支草图"，今天亲手实现了。

### 1.4 tools_condition：官方预置的路由函数

写 ReAct Agent 时，最常见的一种条件边是"模型有没有返回 tool_calls"——有就走工具节点，没有就走 END。这个 router 太常用了，LangGraph 直接预置了一个：`tools_condition`。

```python
from langgraph.prebuilt import tools_condition

# tools_condition 的等价手写实现长这样：
def tools_condition(state) -> str:
    """最后一条消息有 tool_calls → 返回 "tools"；否则 → 返回 END。"""
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return END
```

它返回的字符串正好是 `"tools"` 和 `END`，所以配合 `add_conditional_edges` 时**可以不写 path_map**——返回值本身就是目标节点名。下一节就用它搭 ReAct Agent。

---

## 二、用循环实现 Agent Loop（本周核心）

### 2.1 回顾 Day 02 的 while 循环

Day 02 我们用纯 LangChain 手写了一个工具循环，核心是这段：

```python
# Day 02 的 runAgent（while 循环版，回顾）
for i in range(max_iter):
    ai_msg = model_with_tools.invoke(messages)   # ① 调模型
    messages.append(ai_msg)
    if not ai_msg.tool_calls:                     # ② 没工具调用 → 退出
        return ai_msg.content
    for tc in ai_msg.tool_calls:                  # ③ 有 → 执行工具
        result = TOOL_MAP[tc["name"]].invoke(tc["args"])
        messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
    # ④ 带着 tool 结果回到 ①
```

这段代码的逻辑清楚，但控制流藏在 `for` / `if` / `return` 里——"哪一步会循环""哪一步会退出"要通读代码才能看出来。今天用图把它拍平。

### 2.2 把循环拆成"两个节点 + 一条循环边"

观察 Day 02 的循环体，其实只干两件事：**调模型** 和 **执行工具**。把它们各做成一个节点，再用条件边决定"调完模型去哪"：

| Day 02 循环体里的代码 | 对应的图节点 / 边 |
|----------------------|-------------------|
| `model_with_tools.invoke(messages)` | `agent` 节点 |
| `if not ai_msg.tool_calls: return` | 条件边 `agent → END`（无 tool_calls 时） |
| `for tc: 执行工具 + ToolMessage` | `tools` 节点（用 `ToolNode` 封装） |
| 循环回到 ① 再调模型 | 普通边 `tools → agent`（**这就是循环边**） |

关键洞察：**循环不是 `while` 关键字，而是一条指回起点的边。** `tools → agent` 这条边让执行流从 tools 回到 agent，自然形成了"调模型 → 执行工具 → 再调模型"的循环。

ASCII 循环图：

```
                          ┌─── 有 tool_calls ──► ┌───────┐ ────┐
                          │                      │ tools │     │
                          │                      └───────┘     │
                          │                                    │ 循环边
                          │                                    │ (回 agent)
  START ───► ┌────────┐ ──┤                                    │
             │ agent  │   │                                    │
             │ (调模型)│ ◄─┘                                    │
             └────────┘                                        │
                          │                                    │
                          └─── 无 tool_calls ──► END            │
                                                               │
                          条件边 tools_condition 决定走向 ◄──────┘
```

### 2.3 完整可运行的 ReAct Agent 图

把上面的设计落成代码，就是今天的产出文件 `react_agent_graph.py` 的核心：

```python
"""react_agent_graph.py — 用 LangGraph 图重写 Week 03 / Day 02 的 Agent Loop"""
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition


# ─── 1. 工具定义（复用 Day 02 的三个工具）──────────────────────
@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。city 为城市名，如 '北京'、'上海'。"""
    db = {"北京": "晴 25°C", "上海": "多云 28°C", "Tokyo": "小雨 18°C"}
    return db.get(city, f"{city}：暂无天气数据")


@tool
def search_routes(location: str, difficulty: str = "easy") -> str:
    """根据地点检索徒步路线。location 为起点城市，difficulty 为难度 easy/medium/hard。"""
    routes = {"北京": "香山、百望山、奥森", "杭州": "北高峰、宝石山"}
    return f"为 {location}({difficulty}) 找到：{routes.get(location, '暂无路线')}"


@tool
def calculate_distance(start: str, end: str) -> str:
    """计算两个地点之间的直线距离（公里）。start/end 为地点名。"""
    table = {("北京", "上海"): 1213, ("杭州", "上海"): 175}
    d = table.get((start, end)) or table.get((end, start))
    return f"{start}→{end} 约 {d} 公里" if d else f"暂无 {start}↔{end} 距离数据"


tools = [get_weather, search_routes, calculate_distance]
model = init_chat_model("gpt-4o-mini", temperature=0)


# ─── 2. agent 节点：调模型（绑了工具）──────────────────────────
def call_model(state: MessagesState) -> dict:
    """调模型，把回复追加到 messages。MessagesState 自带 add_messages reducer。"""
    # 注意 bind_tools 每次调用都绑一次（也可在外层绑好复用）
    response = model.bind_tools(tools).invoke(state["messages"])
    return {"messages": [response]}   # 返回 partial state，reducer 自动追加


# ─── 3. 建图：两节点 + 条件边 + 循环边 ─────────────────────────
graph = StateGraph(MessagesState)

# 两个节点
graph.add_node("agent", call_model)        # agent 节点：调模型
graph.add_node("tools", ToolNode(tools))   # tools 节点：执行工具（ToolNode 自动产出 ToolMessage）

# 入口
graph.add_edge(START, "agent")

# 条件边：agent 跑完，tools_condition 判断有无 tool_calls
#   有 → 去 "tools" 节点；无 → 去 END
graph.add_conditional_edges("agent", tools_condition)

# 循环边：tools 跑完回到 agent，形成 agent ↔ tools 的循环
graph.add_edge("tools", "agent")

# 编译
app = graph.compile()


# ─── 4. 调用 ──────────────────────────────────────────────────
if __name__ == "__main__":
    result = app.invoke({
        "messages": [
            SystemMessage(content="你是徒步出行助手，可查天气、检索路线、算距离。"),
            HumanMessage(content="北京天气如何？再算一下北京到上海的距离"),
        ],
    })
    # invoke 返回最终全状态，回复在 messages 最后一条
    print("最终回复:", result["messages"][-1].content)
    print(f"共产生 {len(result['messages'])} 条消息")
```

### 2.4 逐行解读四个关键点

**① agent 节点只调模型。** `call_model` 干的事和 Day 02 循环体里的 `model_with_tools.invoke(messages)` 一模一样——把全部历史发给绑了工具的模型，拿回 `AIMessage`。区别是它不用管"有没有 tool_calls""要不要退出"，那些交给条件边。

**② tools 节点用 ToolNode 封装。** `ToolNode(tools)` 是官方预置节点，它自动干 Day 02 循环体里那段 `for tc: 执行 + 构造 ToolMessage` 的活——读最后一条 `AIMessage` 的 `tool_calls`，逐个执行，把结果包成 `ToolMessage` 追加到 messages。**Day 02 那 8 行 for 循环，ToolNode 一行替你干了。**

**③ 条件边 tools_condition 做分流。** `add_conditional_edges("agent", tools_condition)` 让 agent 节点跑完后，由 `tools_condition` 读最后一条消息：有 `tool_calls` 返回 `"tools"`（去 tools 节点），无则返回 `END`（结束）。这替代了 Day 02 的 `if not ai_msg.tool_calls: return`。

**④ `tools → agent` 是循环边。** 这条普通的 `add_edge` 让执行流从 tools 回到 agent，于是 `agent → tools → agent → tools → ...` 直到模型不再要工具，条件边把它送去 END。**循环不需要 `while` 关键字，一条回指的边就够了。**

> **和 Week 03 `agent_loop.py` 的对应：** Week 03 的 `while self._loop_count < self.max_turns:` 循环体里的四步（调 LLM / 判断 tool_calls / 执行工具 / 回传），正好对应图的四个元素（agent 节点 / 条件边 / tools 节点 / 循环边）。Week 03 用 `self._loop_count += 1` 计数防死循环，图用什么防？下一节讲。

---

## 三、recursion_limit 与循环终止

### 3.1 图循环默认有递归上限

手写 `while True` 最怕死循环——模型一直要工具、永远不回答。Week 03 的 `agent_loop.py` 用 `max_turns=10` 兜底；Day 02 的 `run_agent` 用 `max_iter=5` 兜底。LangGraph 的图循环同样需要兜底，机制叫 **recursion_limit**（递归上限）。

- **默认值 25**：每个图编译后默认 `recursion_limit=25`，意思是单次 `invoke` 最多执行 25 个节点的步数（一次"节点执行"算一步）。
- **超限报错**：超过上限会抛 `GraphRecursionError`，而不是无限转下去。

### 3.2 怎么设置 recursion_limit

```python
from langgraph.errors import GraphRecursionError

# 方式 1：invoke 时通过 config 临时设置
result = app.invoke(
    {"messages": [HumanMessage(content="...")]},
    config={"recursion_limit": 50},   # 提高到 50 步
)

# 方式 2：捕获超限异常，优雅降级
try:
    result = app.invoke(inputs, config={"recursion_limit": 30})
except GraphRecursionError:
    result = {"messages": [("assistant", "抱歉，思考步数超限，请简化问题。")]}
```

> **注意单位：** `recursion_limit` 计的是**节点执行步数**，不是"循环圈数"。一次 `agent → tools → agent` 的循环走 2 步（agent 一步、tools 一步），所以 `recursion_limit=25` 大约允许 12 圈循环。这和 Week 03 `max_turns` 按"轮"计数略有差别。

### 3.3 与 Week 03 max_turns 的对应关系

| 防死循环机制 | Week 03 `agent_loop.py` | LangGraph 图 |
|-------------|------------------------|--------------|
| 参数名 | `max_turns=10` | `recursion_limit=25`（默认） |
| 计数单位 | 一轮（调模型 + 执行工具算一轮） | 一步（一个节点执行算一步） |
| 超限行为 | 返回 `"⏰ 已达到最大工具调用轮数"` 字符串 | 抛 `GraphRecursionError` 异常 |
| 设置方式 | 构造函数 `ToolAgent(max_turns=10)` | `invoke(inputs, config={"recursion_limit": N})` |
| 循环检测 | `_detect_tool_loop()` 查连续 3 次相同调用 | 无内置，需自己写节点判断或靠 limit 兜底 |

**换算直觉：** Week 03 的 1 轮 ≈ LangGraph 的 2 步（agent + tools），所以 `max_turns=10` 大致对应 `recursion_limit=20`。迁移时按 2 倍换算即可。

### 3.4 一个常见误区

```python
# ❌ 以为 recursion_limit 是"循环圈数"，设成 5 想跑 5 圈
app.invoke(inputs, config={"recursion_limit": 5})
# 实际只能跑 2 圈（5 步 = 2 圈 agent+tools + 1 步收尾），复杂问题会提前 GraphRecursionError

# ✅ 按步数算，留足余量
app.invoke(inputs, config={"recursion_limit": 50})   # 约 25 圈，够用
```

---

## 四、create_react_agent 高层 API

### 4.1 一行创建 ReAct Agent

第二节我们用了约 20 行搭出 `agent ↔ tools` 循环图。这套结构（agent 节点 + ToolNode + tools_condition + 循环边）是 ReAct Agent 的标准范式，LangGraph 把它封装成了一个高层 API：

```python
from langgraph.prebuilt import create_react_agent

# 一行创建 ReAct Agent，返回可直接 invoke 的编译图
agent = create_react_agent(model, tools)
```

`create_react_agent(model, tools)` 返回的是一个已经 `compile()` 过的图，用法和我们手写的 `app` 完全一样——直接 `invoke` 即可。

### 4.2 使用示例

```python
"""create_react_agent 高层 API 示例"""
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
# 复用第二节的 tools 定义（get_weather / search_routes / calculate_distance）

model = init_chat_model("gpt-4o-mini", temperature=0)

# 一行创建 ReAct Agent
agent = create_react_agent(model, tools)

# 直接 invoke，和手写图的用法一模一样
result = agent.invoke({
    "messages": [
        SystemMessage(content="你是徒步出行助手。"),
        HumanMessage(content="北京天气如何？再算北京到上海的距离"),
    ],
})
print(result["messages"][-1].content)
```

### 4.3 它内部就是第二节那张图

`create_react_agent` 不是黑魔法——它内部干的事，和我们第二节手写的一模一样：

```python
# create_react_agent(model, tools) 的等价手写实现（简化版）
def create_react_agent(model, tools):
    # agent 节点
    def call_model(state):
        response = model.bind_tools(tools).invoke(state["messages"])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile()   # 返回编译好的图
```

**对照看：** 第二节我们手写的 `graph + app = graph.compile()`，和上面这个函数体**逐行对应**。`create_react_agent` 只是把这 8 行封装成一个函数调用。正因为我们亲手搭过一遍，用高层 API 时心里清楚——它内部就是 `agent ↔ tools` 的循环图，循环边是 `tools → agent`，条件边是 `tools_condition`，防死循环靠 `recursion_limit`。

> **类比记忆：** `create_react_agent` 之于手写图，就像 Day 02 的 `@tool` 之于 Week 03 手写 JSON Schema——都是把重复的样板封装成一行。手写过的人用高层 API 知道每一行在干什么，没手写过的人只当它是个黑盒。

---

## 五、手写图 vs create_react_agent 对比

### 5.1 两者对照

| 维度 | 手写 StateGraph（第二节） | create_react_agent（第四节） |
|------|--------------------------|------------------------------|
| 代码量 | 约 20 行（建图 + 连边 + 编译） | 1 行 |
| 控制流可见性 | 完全可见（每条边都自己连） | 隐藏在函数内部 |
| 可定制性 | 高（可加任意节点 / 边 / 分支） | 低（标准 ReAct 范式） |
| 调试粒度 | 可在每个节点插桩 print | 只能看整体输入输出 |
| 适合场景 | 需要自定义控制流（多分支、人机确认、并行） | 标准 ReAct Agent，开箱即用 |
| 学习价值 | 理解机制 | 快速产出 |

### 5.2 决策表：什么时候用哪个

| 场景 | 推荐 | 理由 |
|------|------|------|
| 标准 ReAct Agent（调模型 → 用工具 → 回答） | `create_react_agent` | 标准范式，一行起手，别重复造轮子 |
| 要在"执行工具前"插一个人工确认节点 | 手写图 | 需要加 `interrupt` / 自定义节点，高层 API 不支持 |
| 要按问题类别路由到不同工具集 | 手写图 | 多分支条件边，`create_react_agent` 只有单条 agent↔tools 循环 |
| 要并行调多个工具 / 多个检索器 | 手写图 | 需要扇出边，高层 API 是串行的 |
| 快速原型 / Demo / 教学 | `create_react_agent` | 快，能跑就行 |
| 生产级 Agent，需要精细控制流 | 手写图 | 可调试、可插桩、可加业务节点 |

> **一句话原则：** 标准 ReAct 用 `create_react_agent`，需要改控制流就退回手写图。两者不是二选一，而是"先用高层 API 跑通，遇到瓶颈再退回手写图定制"。

---

## 动手实验

### 🟢 青铜级：跑通手写 ReAct Agent 图

把第二节的 `react_agent_graph.py` 完整敲出来跑通，输入"北京天气如何？再算北京到上海的距离"，观察终端输出。确认你看到了 `agent → tools → agent → tools → agent → END` 的多步执行（天气和距离两次工具调用）。把最终回复和消息总数贴到笔记里。

### 🟡 白银级：对比手写图与 create_react_agent

用**同一个问题**和**同一套工具**，分别跑第二节的 `app`（手写图）和第四节的 `agent`（create_react_agent），对比：
1. 两者最终回复是否一致（模型有随机性，允许措辞不同）
2. 两者产生的消息总数是否相近
3. 把 `recursion_limit` 改成 `3`，观察两者是否都抛 `GraphRecursionError`

思考：既然结果差不多，为什么还要学手写图？（提示：看第五节决策表）

### 🔴 王者级：加一个"工具前确认"节点

在手写图的基础上，加一个 `confirm_node`：在 `agent` 决定调工具后、`tools` 执行前，先走 `confirm_node`，它打印"即将调用工具 X，参数 Y"并模拟用户确认（直接放行即可）。图结构改成 `agent →(条件边)→ confirm → tools → agent`。难点：条件边要区分"有 tool_calls 去 confirm"和"无 tool_calls 去 END"。这其实是 Day 05 `interrupt` 人机交互的雏形——今天先用手写节点占位。

---

## 踩坑记录 🕳️

### 坑 1：条件边返回的字符串和 path_map / 节点名对不上

```python
# ❌ router 返回 "technical"，但 path_map 里只有 "tech"
def route(state):
    return "technical"   # 拼错了
graph.add_conditional_edges("classify", route, {"tech": "tech_reply"})

# 运行时：KeyError 或走到 END，行为不符合预期

# ✅ router 返回值必须和 path_map 的 key 严格一致
def route(state):
    return "tech"        # 和 path_map 的 key 对齐
```

**解决：** router 返回的字符串是 path_map 的 key，必须逐字对上。建议把 key 定义成常量复用，避免拼写不一致。不写 path_map 时，返回值必须直接是节点名（如 `tools_condition` 返回 `"tools"` / `END`）。

### 坑 2：忘了连循环边，Agent 只调一次工具就停

```python
graph.add_conditional_edges("agent", tools_condition)
# ❌ 忘了 graph.add_edge("tools", "agent")

# 现象：tools 节点跑完后无处可去，图直接结束，模型没机会看到工具结果再回答
# 最终回复里没有基于工具结果的总结，甚至是个空回复
```

**解决：** 循环边 `tools → agent` 是 ReAct Agent 的命脉，漏了它图就退化成"只调一次工具不回头"。建图时按 ASCII 草图逐条连边，连完核对一遍。

### 坑 3：recursion_limit 太小，复杂问题报 GraphRecursionError

```python
# ❌ 默认 25 步，遇到要调 7、8 个工具的多步问题就超限
result = app.invoke(inputs)
# Raise: GraphRecursionError: Recursion limit of 25 reached

# ✅ 按问题复杂度调高，并捕获异常降级
try:
    result = app.invoke(inputs, config={"recursion_limit": 50})
except GraphRecursionError:
    result = {"messages": [("assistant", "思考步数超限，请简化问题。")]}
```

**解决：** 默认 25 步约 12 圈循环，多数场景够用。但"查多城天气 + 算多段距离"这类多工具任务容易触顶。生产环境建议显式设置 `recursion_limit` 并 `try/except` 降级，呼应 Week 03 `max_turns` 超限返回提示字符串的做法。

### 坑 4：ToolNode 遇到未知工具名直接抛异常

```python
# 模型偶尔会"幻觉"出一个不存在的工具名
# ToolNode 默认行为：遇到 tools 列表里没有的工具名，抛 ValueError

# ✅ 给 ToolNode 传 handle_tool_errors=True，错误会变成 ToolMessage 回传给模型
graph.add_node("tools", ToolNode(tools, handle_tool_errors=True))
# 模型收到"工具不存在"的反馈后，通常会改用别的工具或直接回答
```

**解决：** `ToolNode(tools, handle_tool_errors=True)` 让工具执行错误（包括未知工具名、参数错误、工具内部异常）都变成 `ToolMessage` 回传给模型，让模型自己应对，而不是整个图崩掉。这呼应 Week 03 `_execute_tool` 里把异常字符串化的做法。

### 坑 5：手写图和 create_react_agent 混用，状态结构不一致

```python
# 手写图用了自定义 State（带 category 字段）
class MyState(TypedDict):
    messages: Annotated[list, add_messages]
    category: str

# 后来想换成 create_react_agent，但它内部用的是 MessagesState（只有 messages）
agent = create_react_agent(model, tools)
agent.invoke({"messages": [...], "category": "tech"})  # ❌ category 被忽略

# ✅ create_react_agent 只认 messages，自定义字段要在 prompt / 工具里体现
```

**解决：** `create_react_agent` 固定用 `MessagesState`，无法加自定义状态字段。需要传递业务字段（如分类标签、置信度）时，只能退回手写图用自定义 State。这也是第五节决策表里"需要自定义控制流 → 手写图"的具体体现。

---

## 副线笔记：对比手写 Loop 与图编排

今天的主线是把 Day 02 / Week 03 的 `while True` 工具循环改写成 LangGraph 的循环图。两套代码做的是**完全一样的事**——调模型、判断 tool_calls、执行工具、回传、再调。差别只在控制流的表达方式。把 Week 03 `agent_loop.py` 的 `run()` 方法和今天的 `react_agent_graph.py` 并排对比：

| 维度 | Week 03 手写 Loop（`agent_loop.py`） | Day 04 图编排（`react_agent_graph.py`） |
|------|------------------------------------|----------------------------------------|
| **控制流可见性** | 藏在 `while` / `if` / `return` 里，要通读代码 | 图结构本身就是控制流，一眼看出循环在哪 |
| **状态管理** | `self.messages` 手动 append，字段散落 | `MessagesState` + reducer 自动合并 |
| **分支逻辑** | `if not tool_calls: return` 写在循环体里 | `tools_condition` 条件边，与业务代码解耦 |
| **工具执行** | 手写 `for tc: execute + ToolMessage`（约 8 行） | `ToolNode(tools)` 一行封装 |
| **防死循环** | `max_turns` + `_detect_tool_loop()` 手写 | `recursion_limit` 框架内置 |
| **持久化** | 无，进程死即丢 | Checkpointer 自动存档（Day 05 学） |
| **可视化** | 画不出，只能读代码 | `graph.get_graph()` 可导出结构，能画图 |
| **调试** | 在循环体里插 print | 可 `stream` 逐节点看状态，或 LangSmith 追踪 |
| **人机交互** | 要硬插代码改循环 | `interrupt` 在边上暂停（Day 05 学） |
| **代码量** | `agent_loop.py` 约 500 行（含工具定义） | `react_agent_graph.py` 约 60 行 |

### 结论：把"隐式循环"变成"显式图"

Week 03 的 `while True` 不是错了，而是"控制流隐式藏在代码缩进里"。它的循环、分支、退出条件都混在循环体的几行代码中，想看清"这个 Agent 有几步、哪步会循环、哪步能停"必须在脑子里模拟执行。一旦要加"执行工具前问用户确认""并行调两个检索器""失败重试"这类需求，就得在循环体里继续堆 if/else，很快就不可维护。

LangGraph 的图编排把**控制流从代码里抽出来，变成显式的图结构**：
- 循环不再是 `while` 关键字，而是一条 `tools → agent` 的回指边
- 分支不再是 `if/else`，而是 `add_conditional_edges` 的条件边
- 退出不再是 `return`，而是条件边指向 `END`

这样一来，控制流和业务逻辑就分开了——业务逻辑在节点函数里（纯函数，好测），控制流在图结构里（可视、可画、可讨论）。这正是从"手写 Agent"到"框架编排"的关键一跃：**不是代码变短了，而是控制流变得可见、可工程化了。**

> 一句话：**Week 03 的 while True 是"代码即控制流"，LangGraph 是"图即控制流"。** 手写过 while 的人，看图能立刻对应出每条边是循环体里的哪一行；没手写过的人，图只是一张画。这就是本周反复强调"手写过，所以用框架不是黑盒"的意义。

---

## 今日产出检查清单

- [ ] 能用 `add_conditional_edges` 写出根据 state 分流的条件边，说清 router_fn / path_map / 返回字符串三者的关系
- [ ] 把 Day 02 的 `while` 工具循环改写成 `agent ↔ tools` 的 LangGraph 循环图，`react_agent_graph.py` 跑通至少一个两轮工具调用的例子
- [ ] 能说清 `recursion_limit`（默认 25，按节点步数计）的作用，并把它和 Week 03 `max_turns`（按轮计）按 2 倍关系换算
- [ ] 用 `create_react_agent(model, tools)` 一行创建 ReAct Agent 并跑通，确认它和手写图行为一致
- [ ] 能对照决策表说出"标准 ReAct 用 create_react_agent、需要自定义控制流用手写图"
- [ ] 产出文件 `react_agent_graph.py` 可独立运行，含手写图 + create_react_agent 两种写法的对比

---

> **下一课预告：Day 05 — 持久化与人机交互：Checkpointer / interrupt**。今天我们的图跑完就没了——进程一死，对话历史、中间状态全丢，也没法在"执行工具前"暂停问用户一句。明天给图装上两件生产级武器：用 `Checkpointer`（MemorySaver / SqliteSaver）给每一步状态自动存档，实现断点恢复和长记忆；用 `interrupt()` 在任意节点暂停图执行，等人确认后 `Command(resume=...)` 继续。你会发现，今天坑 4 模拟的"工具前确认"，明天一个 `interrupt` 就优雅搞定。
