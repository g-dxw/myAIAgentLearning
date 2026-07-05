# Day 04 — 手写 StateGraph vs create_agent

## 学习目标

Day 03 我们用 `StateGraph` 学会了搭线性流水线：`node_A → node_B → node_C`，每条边都是固定的，节点跑完就知道下一站去哪。但真实的 Agent 不是流水线——它需要循环：调模型 → 看要不要用工具 → 执行工具 → 再调模型。今天我们把 Day 03 的"静态图"升级成"循环图"，亲手写出完整的 Agent 循环，再对比官方高层 API `create_agent` 一行搞定同一个事，从而理解框架内置 Agent 的底层原理。

学完今天你能：
1. 把 Day 03 的线性图扩展成 `agent ↔ tools` 循环图，手写 `should_continue` 条件路由，跑通完整的 ReAct Agent
2. 说清 `recursion_limit`（默认 25）的作用，并与 Week 03 `max_turns` 对应
3. 用 `create_agent(model, tools)` 一行创建 Agent，并能说出其内部等价于手写图的哪几步
4. 根据场景判断该手写 StateGraph 还是用高层 API——标准 ReAct 用 `create_agent`，自定义控制流用手写图

---

## 一、从 Day 03 线性图到 Day 04 循环图

### 1.1 Day 03 回顾：节点 + 边 + 线性流水线

Day 03 我们学了 StateGraph 的两个基本概念：

| 概念 | 对应代码 | 作用 |
|------|----------|------|
| **节点（Node）** | `graph.add_node("name", fn)` | 封装一段处理逻辑，接收 state，返回更新 |
| **边（Edge）** | `graph.add_edge("A", "B")` | 决定执行顺序：A 跑完 → 去 B |
| **条件边** | `add_conditional_edges("A", router, path_map)` | 动态分流：根据 state 决定去哪 |
| **编译** | `app = graph.compile()` | 把图变成可调用的执行引擎 |

Day 03 搭建的图都是**线性或树形**的：要么 `A → B → C` 直走到底，要么 `classify → (tech|chat|other) → END` 一分三叉再各自结束。箭头永远向前，没有回头路。

### 1.2 Day 04 新挑战：Agent 需要循环

Week 03 的 Agent 核心逻辑是 `while True` 循环：

```python
# Week 03 手写 Loop 的核心骨架（回顾）
for _ in range(max_turns):
    response = model.invoke(messages)         # ① 调模型
    if not response.tool_calls:               # ② 判断是否要工具
        return response.content               # ③ 不要 → 结束
    for tc in response.tool_calls:            # ④ 要 → 执行工具
        tool_result = execute_tool(tc)
        messages.append(ToolMessage(...))     # ⑤ 回传结果
    # ⑥ 回到 ①
```

这个循环里只有两件核心事：**调模型**（agent）和 **执行工具**（tools）。把这两件事各做成一个节点，再用一条从 tools 指回 agent 的边，`while` 关键字就变成了一条**回指边**。

### 1.3 循环 = 节点 + 回指边

```
                   ┌─── 有 tool_calls ──► ┌──────────┐
                   │                       │  tools   │
                   │                       └──────────┘
                   │                            │
                   │                            │ 循环边
                   │                            ▼
  START ───► ┌───────┐ ──┐               ┌──────────┐
             │ agent │   │               │  agent   │
             │(调模型)│  ◄┼───────────────┘ (再次调) │
             └───────┘   │               └──────────┘
                         │
                         └─── 无 tool_calls ──► END

  条件边 should_continue：agent 跑完判断下一步去向
  循环边 tools → agent：让执行流能回起点，形成循环
```

> **与 Day 03 的呼应：** Day 03 的边都是"一去不回头"的普通边。今天多了一条 `tools → agent` 的回指边，图就从线性变成了循环。但循环带来一个安全问题：如果模型永远要工具怎么办？第三节的 `recursion_limit` 就是答案。

---

## 二、手写 StateGraph Agent 循环（官方 Quickstart 6 步流程）

这一节完全按照官方 Quickstart 的六步流程，手写一个完整的 ReAct Agent 循环图。产出代码对应 `react_agent_compare.py` 中的手写版本。

### 2.1 Step 1：定义工具

```python
"""Step 1 — 定义 Agent 可调用的工具"""
from langchain.tools import tool


@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。city 为城市名，如 '北京'、'上海'。"""
    db = {"北京": "晴 25°C", "上海": "多云 28°C", "深圳": "阵雨 30°C", "成都": "阴 22°C"}
    return db.get(city, f"暂无 {city} 的天气数据")


@tool
def calculate_distance(start: str, end: str) -> str:
    """计算两个城市之间的直线距离（公里）。start/end 为城市名。"""
    table = {("北京", "上海"): 1213, ("杭州", "上海"): 175, ("北京", "深圳"): 2150}
    d = table.get((start, end)) or table.get((end, start))
    if d:
        return f"{start} → {end} 约 {d} 公里"
    return f"暂无 {start} ↔ {end} 距离数据"


TOOLS = [get_weather, calculate_distance]
TOOL_MAP = {t.name: t for t in TOOLS}  # 工具名 → 工具对象的映射，Step 4 要用
```

工具定义和 Week 03 / Day 02 完全一致：`@tool` 装饰器自动生成 name/description/args_schema。`TOOL_MAP` 是为 Step 4 手写工具执行准备的。

### 2.2 Step 2：定义 State（消息累加器）

```python
"""Step 2 — 定义 Agent State：messages 用 operator.add 做 reducer"""
import operator
from typing import Annotated, TypedDict
from langchain.messages import AnyMessage


class AgentState(TypedDict):
    """Agent 状态：消息列表。等价于框架的 MessagesState。"""
    messages: Annotated[list[AnyMessage], operator.add]
```

关键设计：

| 设计 | 含义 |
|------|------|
| `Annotated[list[AnyMessage], operator.add]` | messages 字段的 reducer 是 `operator.add`，即每次节点返回 `{"messages": [msg]}` 时，框架自动把新消息**追加**到已有列表末尾，而不是覆盖 |
| `AnyMessage` | `langchain.messages` 提供的联合类型，覆盖所有消息子类（HumanMessage / AIMessage / ToolMessage / SystemMessage 等） |
| 等价于框架的 `MessagesState` | LangGraph 的 `MessagesState` 也是这么定义的，我们今天手动写一遍 |

> **与 Day 03 的呼应：** Day 03 我们自定义了带 `messages` + `category` 的 State。今天 AgentState 只有 `messages`——Agent 循环不需要额外状态字段，所有信息都通过消息传递。更纯粹。

### 2.3 Step 3：模型节点 call_model

```python
"""Step 3 — Agent 节点：调 LLM，决定是否调用工具"""
from langchain.chat_models import init_chat_model

MODEL = init_chat_model("gpt-4o-mini", temperature=0)


def call_model(state: AgentState) -> dict:
    """Agent 节点：将消息传给绑了工具的 LLM，返回 AIMessage（可能含 tool_calls）。

    这是循环中的"思考"环节——LLM 看当前消息历史，决定是直接回答还是调工具。
    """
    # bind_tools 把工具的 JSON Schema 注入到模型调用的 tools 参数中
    response = MODEL.bind_tools(TOOLS).invoke(state["messages"])
    # 返回 partial state，reducer 自动追加到 messages 列表末尾
    return {"messages": [response]}
```

`call_model` 干的活和 Week 03 循环体第一步完全一样：把全部历史消息发给绑了工具的模型，拿回一个 `AIMessage`。区别是它**只负责调模型**，不负责判断后续走哪条路——那交给 Step 5 的条件边。

### 2.4 Step 4：工具节点 execute_tools（手写，不用 ToolNode）

```python
"""Step 4 — 工具节点：手写执行工具（不用 ToolNode），产生 ToolMessage"""
from langchain_core.messages import ToolMessage


def execute_tools(state: AgentState) -> dict:
    """工具节点：遍历模型最后一条消息的 tool_calls，逐一执行并打包 ToolMessage。

    注意：这里手写而不使用 ToolNode，目的是理解底层机制。
    create_agent 内部使用的是内置 ToolNode，但我们自己手写一遍才能
    理解 tools 节点本质上就是"读 tool_calls → 逐条执行 → 返回 ToolMessage"。
    """
    last_msg = state["messages"][-1]
    tool_messages = []

    for tc in last_msg.tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        tool_call_id = tc["id"]

        # 从 TOOL_MAP 查找工具并执行
        tool_fn = TOOL_MAP.get(tool_name)
        if tool_fn is None:
            result = f"错误：未知工具 '{tool_name}'"
        else:
            try:
                result = tool_fn.invoke(tool_args)
            except Exception as e:
                result = f"工具执行异常：{e}"

        tool_msg = ToolMessage(content=str(result), tool_call_id=tool_call_id)
        tool_messages.append(tool_msg)

    return {"messages": tool_messages}
```

**为什么手写而不是用 ToolNode？** `ToolNode` 是 LangGraph 预置的工具执行节点，自动做上面这个 `for` 循环的事。但今天我们的主题是**理解底层原理**，手写一遍才能说清楚：工具节点就是"解析 `tool_calls` → 逐个调用 → 包装 `ToolMessage`"这三步，没有黑魔法。

> **与 Week 03 的呼应：** Week 03 `_execute_tool` 方法里那七八行 `for tc` 代码，和这里的 `execute_tools` 做的事一模一样。区别是 Week 03 把它写在 `while` 循环体里，今天独立成图中的一个节点。

### 2.5 Step 5：条件路由 should_continue

```python
"""Step 5 — 条件路由：判断下一步是继续调工具还是结束"""
from langgraph.graph import END


def should_continue(state: AgentState) -> str:
    """条件路由函数：读最后一条消息，看有无 tool_calls。

    返回：
        - "tools" → agent 要调工具，去 tools 节点
        - END     → agent 已直接回答，结束整个图
    """
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return END
```

`should_continue` 等价于官方预置的 `tools_condition`，区别是我们手写了一遍。它的本质就是一个读 state、返字符串的函数——条件边拿到字符串，去 path_map（或直接当节点名）里找下一站。

### 2.6 Step 6：建图 + 编译 + invoke

```python
"""Step 6 — 把前面 5 步组装成一个完整的 StateGraph"""
from langgraph.graph import StateGraph, START


def build_agent_graph() -> StateGraph:
    """构建手写 StateGraph Agent 循环图。

    图结构：
        START → agent ──(should_continue)──► tools ──► agent(循环)
                        └──(should_continue)──► END
    """
    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("agent", call_model)
    graph.add_node("tools", execute_tools)

    # 入口
    graph.add_edge(START, "agent")

    # 条件边：agent 跑完，由 should_continue 决定下一步
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", END: END},  # "tools" → tools 节点, END → 结束
    )

    # 循环边：tools 跑完回到 agent，形成 agent ↔ tools 的循环
    graph.add_edge("tools", "agent")

    return graph.compile()


# ─── 调用 ───
if __name__ == "__main__":
    from langchain_core.messages import HumanMessage

    app = build_agent_graph()

    result = app.invoke({
        "messages": [
            HumanMessage(content="北京天气如何？再算一下北京到上海的距离"),
        ],
    })

    print("=" * 50)
    print("手写 StateGraph Agent 运行结果：")
    print("最终回复:", result["messages"][-1].content)
    print(f"共产生 {len(result['messages'])} 条消息")
    for i, msg in enumerate(result["messages"]):
        print(f"  [{i}] {msg.__class__.__name__}: {msg.content[:60]}...")
```

### 2.7 完整 ASCII 图与执行流程

手写图的完整执行流程：

```
START
  │
  ▼
┌───────────┐
│   agent   │  ←── 调模型，返回 AIMessage（可能含 tool_calls）
└─────┬─────┘
      │
      │ should_continue(state)
      │
      ├── 有 tool_calls ──────────► ┌───────────┐
      │                              │   tools   │  ←── 逐一执行工具
      │                              └─────┬─────┘
      │                                    │
      │                                    │ (循环边)
      │                                    ▼
      │                              ┌───────────┐
      │                              │   agent   │  ←── 再调模型（看到工具结果）
      │                              └─────┬─────┘
      │                                    │
      │                                    └──→ (再次判断，循环或结束)
      │
      └── 无 tool_calls ──► END
```

一次典型的两步工具调用流程：`agent → tools → agent → tools → agent → END`，共 5 步节点执行。

---

## 三、recursion_limit：循环终止保护

### 3.1 为什么需要它

手写 `while True` 最怕死循环——模型一直要工具、永远不回答。Week 03 用 `max_turns=10` 兜底。LangGraph 的图循环同样需要兜底，机制叫 **recursion_limit**（递归上限）。

- **默认值 25**：每个编译后的图默认 `recursion_limit=25`，单次 `invoke` 最多执行 25 步（一个节点执行算一步）
- **超限行为**：抛 `GraphRecursionError`，而不是无限转下去

### 3.2 设置方式

```python
from langgraph.errors import GraphRecursionError

# 方式 1：invoke 时通过 config 临时调整
result = app.invoke(
    {"messages": [HumanMessage(content="...")]},
    config={"recursion_limit": 50},   # 提高到 50 步
)

# 方式 2：捕获异常，优雅降级
try:
    result = app.invoke(inputs, config={"recursion_limit": 30})
except GraphRecursionError:
    result = {"messages": [("assistant", "抱歉，思考步数超限，请简化问题。")]}
```

### 3.3 与 Week 03 max_turns 的对应

| 防死循环机制 | Week 03 `agent_loop.py` | LangGraph 图 |
|-------------|------------------------|--------------|
| 参数名 | `max_turns=10` | `recursion_limit=25`（默认） |
| 计数单位 | 一轮（调模型 + 执行工具算一轮） | 一步（一个节点执行算一步） |
| 超限行为 | 返回 `"已达到最大工具调用轮数"` 字符串 | 抛 `GraphRecursionError` 异常 |
| 设置方式 | 构造函数 `ToolAgent(max_turns=10)` | `invoke(inputs, config={"recursion_limit": N})` |

**换算直觉：** Week 03 的 1 轮 ≈ LangGraph 的 2 步（agent + tools），所以 `max_turns=10` 大致对应 `recursion_limit=20`。生产环境建议设到 50~100 留足余量。

---

## 四、create_agent 高层 API

### 4.1 一行创建 Agent

第二节我们用了约 40 行代码搭出了完整的 Agent 循环图。这套"agent 节点 + tools 节点 + should_continue + 循环边"是 ReAct Agent 的标准范式，LangChain 把它封装成了一个高层 API：

```python
"""create_agent — 一行创建完整的 ReAct Agent"""
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

# 一行创建 Agent，返回一个已 compile() 的图
agent = create_agent(
    model="gpt-4o-mini",
    tools=[get_weather, calculate_distance],
    system_prompt="你是徒步出行助手，可查天气和算距离。",
    checkpointer=InMemorySaver(),
)

# 直接 invoke，用法和手写图完全一样
result = agent.invoke({
    "messages": [
        HumanMessage(content="北京天气如何？再算北京到上海的距离"),
    ],
})
print(result["messages"][-1].content)
```

`create_agent` 会自动帮你完成第二节 Step 2 ~ Step 6 的所有工作：

| create_agent 参数 | 等价于手写图的哪个部分 |
|-------------------|-----------------------|
| `model` | Step 3 的 `MODEL.bind_tools(TOOLS)` |
| `tools` | Step 1 的工具定义 + Step 4 的工具节点 |
| `system_prompt` | 自动往 messages 开头插入 SystemMessage |
| `checkpointer` | 给编译图附加检查点（下一行解释） |
| `InMemorySaver()` | 内存中的检查点存储，默认即用（Day 05 深入） |

### 4.2 create_agent 底层伪代码

`create_agent` 不是黑魔法——它内部干的事，和我们第二节 Step 2~6 手写的**逐行对应**：

```python
# create_agent(model, tools, ...) 的等价内部实现（简化示意）
def create_agent(model, tools, system_prompt=None, checkpointer=None, **kwargs):
    # Step 2：定义 state（内部用 MessagesState，等价我们的 AgentState）
    # 内部自动使用 MessagesState，无需手写

    # Step 3：定义 agent 节点
    def call_model(state):
        response = model.bind_tools(tools).invoke(state["messages"])
        return {"messages": [response]}

    # Step 4：定义 tools 节点（内部用的是 ToolNode，比我们手写的更健壮）
    # 自动处理未知工具、异常等

    # Step 5：条件路由（内部用 tools_condition，等价我们的 should_continue）
    # 但 create_agent 用的是更完善的版本，支持更多边缘情况

    # Step 6：建图 + 编译
    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")

    # 附加 checkpointer（如果有传入）
    return graph.compile(checkpointer=checkpointer)
```

> **核心观点：** `create_agent` 就是我们今天手写的 Step 2~6 的封装。正因为亲手搭过一遍，用高层 API 时你知道：它内部有一个 `agent` 节点、一个 `tools` 节点、一条条件边从 `agent` 分流到 `tools` 或 `END`、一条循环边从 `tools` 回到 `agent`。它不是什么黑盒，是你今天已经写过的代码的现成版本。

### 4.3 代码量对比：5 行 vs 40 行

| 版本 | 核心行数（不含工具定义） | 控制流可见性 | 定制空间 |
|------|------------------------|-------------|----------|
| 手写 StateGraph（第二节） | ~40 行 | 每条边都明确可见 | 完全自由 |
| create_agent（第四节） | 5 行 | 隐藏在函数内部 | 有限（受参数约束） |

**40 行到 5 行的压缩，压掉的是样板代码，不是理解。** 手写过 40 行的人用 5 行知道每一行在干什么；没手写过的人，5 行只是 5 行。

---

## 五、手写图 vs create_agent 对比与选型

### 5.1 全面对比表

| 维度 | 手写 StateGraph（第二节） | create_agent（第四节） |
|------|--------------------------|----------------------|
| **代码量** | ~40 行（建图 + 连边 + 编译） | 1 行 + 参数配置 |
| **控制流可见性** | 完全可见——每条边、每个节点都在代码里 | 隐藏在内部，由框架管理 |
| **可定制性** | 极高——可加任意节点、分支、子图、interrupt | 有限——只能改参数（prompt、model、tools） |
| **调试粒度** | 可在每个节点函数里插桩 `print` 或日志 | 只能通过整体 `invoke` 观察行为 |
| **状态结构** | 自定义 State，可加任意字段 | 固定 MessagesState，只能通过 messages 传递信息 |
| **异常处理** | 节点内完全可控，可 try/except | 框架内置了部分异常处理，但定制困难 |
| **checkpointer** | 需手动传入 `graph.compile(checkpointer=...)` | 默认带 InMemorySaver，也支持传入 |
| **学习价值** | 理解机制——知道 Agent 循环底层怎么运作 | 快速产出——适合"已知原理，要效率" |

### 5.2 选型决策表

| 场景 | 推荐方案 | 理由 |
|------|---------|------|
| **标准 ReAct Agent**（调模型 → 用工具 → 回答） | `create_agent` | 标准范式一行起手，别重复造轮子 |
| **需要自定义控制流**（多分支路由、并行节点、子图） | 手写 StateGraph | `create_agent` 只有单条 agent↔tools 循环路径 |
| **需要在执行工具前插入人工确认** | 手写 StateGraph | 需要 `interrupt` + `Command(resume=...)`（Day 05），高层 API 不支持 |
| **需要自定义 State 字段**（如置信度、分类标签、session_id） | 手写 StateGraph | `create_agent` 固定 MessagesState |
| **快速原型 / Demo / 教学** | `create_agent` | 快，能跑就行 |
| **生产级 Agent 需要精细控制流** | 手写 StateGraph | 可插桩、可测、可加业务节点（日志/监控/限流） |
| **学习 LangGraph 机制** | 手写 StateGraph | 不手写过永远不知道高层 API 内部在干什么 |

> **一句话选型原则：** 标准 ReAct 用 `create_agent`，需要改控制流就退回手写图。两者不是二选一——先用高层 API 跑通原型，遇到瓶颈再退回手写图做定制。手写过的人有这个退路，没手写过的人只能卡住。

---

## 动手实验

### 🟢 青铜级：跑通手写 StateGraph Agent

1. 新建 `react_agent_compare.py`，把第二节 Step 1~6 的代码完整敲进去
2. 运行 `python react_agent_compare.py`
3. 输入问题 `"北京天气如何？再算北京到上海的距离"`，观察终端输出
4. 确认你看到多步执行：一次 `agent → tools → agent → tools → agent → END`（天气和距离各一次工具调用）
5. 把最终回复和消息总数贴到笔记里

**验证要点：**
- 工具调用是否成功（ToolMessage 内容有天气数据和距离数据）
- 最终回复是否综合了两个工具的结果
- 消息数量是否符合预期（1 条 Human + 1 条 AIMessage(tools) + 1 条 ToolMessage + 1 条 AIMessage(tools) + 1 条 ToolMessage + 1 条 AIMessage(answer) = 6 条）

### 🟡 白银级：手写图 vs create_agent 对比实验

用**同一个问题**和**同一套工具**，分别跑手写图（第二节）和 `create_agent`（第四节），对比：

1. **最终回复一致性**：两者回答的语义是否一致（模型有随机性，允许措辞不同）
2. **消息数量**：两者产生的消息列表长度是否一致
3. **recursion_limit 测试**：把 `recursion_limit` 设为 3，观察两者是否都抛 `GraphRecursionError`
4. **速度对比**：粗略计时（用 `time.time()`），看两者执行时间是否相近

**思考题：** 既然结果差不多，为什么还要学手写图？提示：看第五节决策表——当你需要加一个"执行工具前先记日志"的节点时，两种方式分别怎么改？

### 🔴 王者级：定制一个"日志监控"节点

在手写图的基础上，在 `agent` 和 `tools` 之间插入一个 `log_node`，在每次调工具前记录 `tool_calls` 的摘要并打印：

```
[LOG] agent 决定调工具：天气查北京，距离算北京→上海
```

图结构改为：

```
START → agent ──(should_continue)──► log_node ──► tools ──► agent
                 └──(should_continue)──► END
```

**难点：** `log_node` 不修改 state 的业务字段，只在控制台打印日志。它返回的 `{}` 或 `None` 表示"不更新 state"。注意条件边的目标节点要改为 `"log_node"` 而非 `"tools"`。

**思考：** 这个 `log_node` 在 `create_agent` 的框架里能加吗？如果不行，说明了什么？

---

## 踩坑记录 🕳️

### 坑 1：手写 ToolNode 时漏了 tool_call_id，ToolMessage 对不上

```python
# ❌ 构造 ToolMessage 时忘了传 tool_call_id
result = tool_fn.invoke(tool_args)
msg = ToolMessage(content=str(result))  # 没有 tool_call_id
# 模型收到后无法将工具结果和之前的 tool_call 关联起来

# ✅ 必须从 tool_calls 中提取 id 并传给 ToolMessage
for tc in last_msg.tool_calls:
    tool_call_id = tc["id"]       # 从 tool_call 里取 id
    result = TOOL_MAP[tc["name"]].invoke(tc["args"])
    msg = ToolMessage(content=str(result), tool_call_id=tool_call_id)
```

**原因：** LangChain 的消息关联机制靠 `tool_call_id` 把 `ToolMessage` 和它对应的 `AIMessage.tool_calls[i]["id"]` 绑定。丢了 id，模型就拿不到工具结果。

### 坑 2：条件边 router 返回值写的字符串和节点名对不上

```python
# ❌ should_continue 返回 "execute_tools"，但节点名叫 "tools"
def should_continue(state):
    return "execute_tools"   # 拼写和节点名不一致

graph.add_node("tools", execute_tools)
graph.add_conditional_edges("agent", should_continue)
# 运行时：KeyError: "execute_tools" not found in nodes

# ✅ 返回值必须是 path_map 中定义的 key（或不提供 path_map 时必须是节点名）
def should_continue(state):
    return "tools" if state["messages"][-1].tool_calls else END
```

**解决：** 条件边的返回值要么在 path_map 字典的 key 里，要么直接是目标节点名。建议显式写 path_map 字典，一目了然。

### 坑 3：reducer 用错——messages 被覆盖而不是追加

```python
# ❌ AgentState 没定义 reducer，每次节点返回覆盖整个 messages 列表
class AgentState(TypedDict):
    messages: list[AnyMessage]   # 没有 Annotated[...]

# 在 call_model 中：
return {"messages": [response]}
# 调用两次后 state["messages"] 只有最后一条消息，前面的全丢了

# ✅ 必须用 Annotated + operator.add 声明 reducer
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
# 这样每次返回 {"messages": [new_msg]} 时，框架自动追加到已有列表
```

**原因：** 没有 reducer 时，节点返回的 dict 会直接替换 state 中对应的字段。`operator.add` 让列表变成"追加"行为——这是 Agent 场景最常用的 reducer 模式。

### 坑 4：recursion_limit 设得太小，正常多步工具调用也超限

```python
# ❌ 默认 25 步，问题需要调 7 个工具就超限
result = app.invoke({"messages": [...]})
# GraphRecursionError: Recursion limit of 25 reached

# ✅ 按问题复杂度调高，并捕获异常
try:
    result = app.invoke(
        {"messages": [HumanMessage(content="查北京、上海、深圳、成都四城的天气")]},
        config={"recursion_limit": 50},
    )
except GraphRecursionError:
    result = {"messages": [("assistant", "思考步数超限，请简化问题。")]}
```

**换算：** 查 4 个城市各需一次工具调用 → 4 轮循环 = agent(1) + tools(4) + agent(结束) ≈ 9 步。默认 25 步够。但如果工具调用多（>10 次），就要主动调高。

### 坑 5：create_agent 传入的 model 是字符串时，可能匹配不到正确的模型

```python
# ❌ 传入字符串 "gpt-4o-mini"，但环境里没安装对应包或没配置 API Key
agent = create_agent(model="gpt-4o-mini", tools=TOOLS)
# 报错：ModelNotFoundError 或 API 认证失败

# ✅ 方式一：先初始化 model 对象再传给 create_agent
model = init_chat_model("gpt-4o-mini", temperature=0)
agent = create_agent(model=model, tools=TOOLS)

# ✅ 方式二：确保环境变量已配置（如 OPENAI_API_KEY）
import os
os.environ["OPENAI_API_KEY"] = "sk-..."
agent = create_agent(model="gpt-4o-mini", tools=TOOLS)
```

**原因：** `create_agent` 接受 model 字符串时会内部调用 `init_chat_model`，但这要求环境已经正确配置了 API Key 和模型包。

---

## 副线笔记：从"代码即控制流"到"图即控制流"

今天的主线是把 Week 03 的 `while True` 工具循环改写成 LangGraph 的循环图。两套代码做的是**完全一样的事**——调模型、判断 tool_calls、执行工具、回传、再调。差别只在控制流的表达方式。

把两种方式并排对比：

| 维度 | Week 03 手写 Loop | Day 04 图编排 |
|------|------------------|--------------|
| **控制流表达** | `while` / `if` / `return` 隐在代码缩进里 | `add_edge` / `add_conditional_edges` 显式声明 |
| **循环语义** | `for _ in range(max_turns)` | `add_edge("tools", "agent")` 回指边 |
| **分支语义** | `if not tool_calls: return` | `add_conditional_edges("agent", should_continue)` |
| **退出语义** | `return content` 跳出函数 | 条件边指向 `END` |
| **状态管理** | `messages.append()` 手动维护 | reducer 自动合并 |
| **工具执行** | 手写 `for tc` 循环（~8 行） | `execute_tools()` 节点（封装在图中） |
| **防死循环** | `max_turns` + `_detect_tool_loop()` | `recursion_limit` 框架内置 |

### 关键洞察：控制流从"行为"变成了"结构"

Week 03 的 `while True` 循环，你是通过**阅读代码的行为**来理解控制流的——"哦，这里有个 for 循环，它会一直跑直到 tool_calls 为空"。

Day 04 的图，你是通过**观察图的结构**来理解控制流的——"哦，`tools → agent` 是一条回指边，所以执行流会循环"。

前者是**过程式的**，控制流藏在循环体的每一步里；后者是**声明式的**，控制流就是图结构本身，一眼可读。

### 为什么这很重要

当你需要修改控制流时，两种方式的差异就体现出来了：

- **手写 Loop**：想加"执行工具前先问用户确认"的逻辑，你得在循环体里找对位置插入代码，还要改循环变量、退出条件——至少改 3~5 行，容易引入 Bug。
- **图编排**：想加确认节点，你在 `agent` 和 `tools` 之间插一个新节点，改一条条件边的目标——改 1~2 行，结构清晰。

这种"改结构不用改逻辑"的能力，就是图编排相对于手写循环的核心优势。明天 Day 05 的 `interrupt` 会把这个优势放大到极致——在任意边暂停图执行，等人确认后恢复，全程不需要改节点函数。

> **一句话总结：** Week 03 你手写过 Loop，所以知道 Agent 循环的每一步在做什么；今天你用手写 StateGraph 重新实现了这个循环，所以知道框架的边和节点对应循环里的哪一行；明天用高层 API 时，你知道它内部就是这张图——这就是"手写过，所以不是黑盒"的完整路径。

---

## 今日产出检查清单

- [ ] 能手写完整 6 步 StateGraph Agent 循环：工具定义 → State → agent 节点 → tools 节点 → should_continue 条件路由 → 编译 + invoke
- [ ] 手写图跑通了至少一个涉及两轮工具调用的例子（如"查天气 + 算距离"），看到 `agent → tools → agent → tools → agent → END` 的多步执行
- [ ] 能说清 `recursion_limit` 的作用（默认 25，按节点步数计），并和 Week 03 `max_turns`（按轮计）按 2 倍关系换算
- [ ] 用 `create_agent(model, tools)` 一行创建 Agent 并跑通，能说出它内部等价于手写图的 Step 2~6
- [ ] 能对照决策表说出"标准 ReAct 用 create_agent、需要自定义控制流用手写图"
- [ ] 产出文件 `react_agent_compare.py` 可独立运行，包含手写 StateGraph 版本和 create_agent 版本的对比代码

---

> **下一课预告：Day 05 — 持久化：Checkpointer / Store / interrupt**。今天我们的图跑完就没了——进程一死，对话历史、中间状态全丢，也没法在"执行工具前"暂停问用户一句。明天给图装上两件生产级武器：用 `Checkpointer` 给每一步状态自动存档，实现断点恢复和长记忆；用 `interrupt()` 在任意节点暂停图执行，等人确认后继续。你会发现，今天王者实验里那个手写 log_node，明天一个 `interrupt` 就优雅搞定。
