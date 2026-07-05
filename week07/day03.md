# Day 03 — Handoffs：状态驱动交接

## 学习目标

Day 02 我们把四大模式里最主流的 **Subagents** 拆了个透：主 Agent 充当"项目经理"，把子 Agent 包装成 tool 来调用，自己始终攥着控制权。你写完了一个"主 Agent + 路线专家 + 天气专家"的最小系统，体验了上下文隔离带来的好处——主 Agent 只看结论不看过程，token 消耗可控。

但 Subagents 有一个隐含的假设：**主 Agent 必须在场**。用户永远只和主 Agent 对话，子 Agent 是幕后打工人，干完活把结论交回来就退场。这在"并行查路线 + 查天气 + 查装备"的场景里很完美——主 Agent 像个调度中心，并发派活、收结论、综合回复。

可是现实里有一类场景不是这样的。想象一个客服系统：用户进来先找**售前**问产品，聊着聊着要退货，被转给**技术**排障，最后又得找**售后**处理退款。整个过程不是"售前同时把技术、售后都叫来"，而是一个**接力**——控制权从售前交到技术，再交到售后，用户始终在和"当前接管的那个人"直接对话。这种"控制权交接 + 多轮连续对话"，正是今天 **Handoffs** 模式要解决的问题。

学完今天你能：
1. 理解 Handoffs 模式的核心机制：通过状态交接控制权，而非主 Agent 调用子 Agent
2. 掌握 Handoffs 与 Subagents 的本质区别：控制权转移 vs 工具调用，并说清用户交互方式的差异
3. 能用 LangGraph StateGraph 实现状态驱动的 Agent 交接（`current_agent` 字段 + 条件边路由）
4. 理解 Handoffs 适合多轮对话场景的原因——用户直接和当前接管的 Agent 交互，上下文连续不割裂

---

## 一、Handoffs 模式详解

### 1.1 回顾：Subagents 的控制权模型

Day 02 我们反复强调过一句话：**Subagents 的本质是主 Agent 把子 Agent 当 tool 调用**。这里有一个容易被忽略的推论——既然子 Agent 是 tool，那它就遵守 tool 的规矩：被调用、返回结果、然后**退场**。主 Agent 从头到尾都在，它才是和用户对话的那个人。

```
Subagents 的控制权：主 Agent 始终在场

用户 ──► 主Agent ──┬── 调用 路线Agent(tool) ── 返回路线结论
                  ├── 调用 天气Agent(tool) ── 返回天气结论
                  └── 综合两份结论 ──► 回复用户

  用户从头到尾只和"主Agent"说话，子Agent是幕后工具人
```

这套机制的关键词是**集中控制**。好处是主 Agent 能并行调度、综合决策；代价是主 Agent 必须理解所有领域（至少能判断该派给谁），而且用户没法跳过主 Agent 直接和某个专家深聊。

### 1.2 Handoffs 的不同：控制权真正"交接"

Handoffs 换了个思路：**不要主 Agent，让控制权在专家之间流动**。

第一个接手的 Agent（比如分诊 Agent）判断这个问题该归谁，然后**把控制权交出去**，自己退场。被交接的 Agent 接管后，直接和用户对话、调用自己的工具、多轮交互——直到它觉得"这事不归我"或者"用户的需求变了"，再把控制权交给下一个 Agent。

关键区别在"交接"两个字：交接之后，**原来的 Agent 就不在了**，用户接下来说的话，全部由新接管的 Agent 处理。不是"叫人来帮忙"，而是"把电话转过去"。

### 1.3 核心机制图解

把两种模式放一起对比，差异一目了然：

```
Subagents（工具调用，主Agent在场）     Handoffs（控制权交接，接力传递）

用户 ──► 主Agent                       用户 ──► AgentA（分诊/售前）
          │                                      │ 判断"该转给B"
          ├── 调用 子AgentB ── 返回结果            │ 交接：改状态 current_agent=B
          ├── 调用 子AgentC ── 返回结果            ▼  AgentA 退场
          └── 主Agent综合 ──► 回复用户            AgentB（技术）接管
                                                    │ 直接和用户对话
主Agent始终攥着控制权，子Agent是工具                │ 多轮交互后判断"该转给C"
用户只和主Agent说话                                  ▼
                                                    AgentC（售后）接管 ──► 回复用户

  控制权：星型（主Agent是中心）            控制权：链式/网状（在Agent间流动）
```

记住这个对比图，今天后面所有的讨论都围绕它展开。

### 1.4 交接的本质：通过共享 State 传递控制权

那"交接"在代码层面到底是什么？答案很朴素：**修改共享 State 里的一个字段**。

Handoffs 的核心是所有 Agent 共享同一份 State（最关键的就是 `messages` 对话历史）。所谓"交接"，就是某个 Agent 在处理完当前轮之后，往 State 里写一个标记——"下一个该轮到谁了"。这个标记通常是一个字段，比如 `current_agent: str`，值是 `"route"`、`"weather"` 这样的 Agent 名字。

```
交接 = 改一个字段

State:
  messages: [用户: "查下四姑娘山的天气"]
  current_agent: "route"    ← 当前是路线Agent

        │ 路线Agent发现"天气"不归我管
        │ 返回 partial state: {"current_agent": "weather"}
        ▼

State:
  messages: [用户: "查下四姑娘山的天气"]   ← messages 不变，连续
  current_agent: "weather"   ← 控制权转给天气Agent
```

注意 `messages` 没动——这就是 Handoffs 上下文连续的根源：交接只换"谁来说话"，不换"聊到哪了"。

### 1.5 用户交互差异

这一点是选型时最容易忽略、却最影响体验的维度：

| 维度 | Subagents | Handoffs |
|------|-----------|----------|
| 用户在和谁说话 | 永远是主 Agent | 当前接管的那个 Agent |
| 专家能否多轮追问用户 | 不能，专家是 tool，一次性返回 | 能，专家直接和用户对话 |
| 对话的"主角" | 主 Agent（始终） | 流动的（谁接管谁就是主角） |
| 适合的交互形态 | 一问一答式派活 | 多轮连续对话 / 角色切换 |

举个具体的例子感受差异。用户说"我想去四姑娘山"，然后接着问"那边天气怎么样"：

- **Subagents**：两句话都进主 Agent，主 Agent 分别派给路线 Agent、天气 Agent，每次都重新调一次子 Agent。
- **Handoffs**：第一句进路线 Agent，路线 Agent 接管后和用户聊路线；用户问天气时，路线 Agent 发现该转，把控制权交给天气 Agent，天气 Agent 带着**完整对话历史**直接接上聊。

后者不需要"重新解释上下文"，因为上下文一直在那。这就是 Handoffs 适合多轮对话的根本原因。

---

## 二、用 LangGraph 实现 Handoffs

理论清楚了，上手实现。我们要搭一个最小的 Handoffs 系统：一个**路线 Agent** 和一个**天气 Agent**，它们之间能互相交接。用户问路线，路线 Agent 接管；聊着聊着问天气，控制权交给天气 Agent；反之亦然。

### 2.1 State 设计：多一个 `current_agent`

Handoffs 和 Subagents 在 State 上最大的区别——Handoffs 需要一个字段标记"当前谁接管"。交接的本质，就是改这个字段。

```python
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END, add_messages


class HandoffState(TypedDict):
    # 对话历史：所有 Agent 共享这一份，保证上下文连续
    messages: Annotated[list, add_messages]
    # 标记当前接管的 Agent："route" / "weather"
    # 交接 = 改这个字段的值
    current_agent: str
```

`messages` 用 `add_messages` reducer，和 Week 06 / Day 03 一样，节点返回 partial state 会自动追加。`current_agent` 是个普通字符串字段，覆盖式更新——谁接管就把值改成自己的名字。

### 2.2 用 create_agent 创建各专家子图

每个专家本身就是一个完整的 Agent（有自己的工具、system_prompt、内部 ReAct 循环）。用 Week 06 学过的 `create_agent` 创建，每个 Agent 是一个编译好的子图，可以作为父图的节点。

```python
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool

model = init_chat_model("gpt-4o-mini", temperature=0)


# ─── 工具：每个专家只拿自己领域的工具 ───
@tool
def search_routes(destination: str) -> str:
    """查询去某地的路线方案。"""
    # 模拟查询
    return f"去 {destination} 的路线：成都 → 四姑娘山镇，全程约 200km，自驾 4 小时。"


@tool
def get_weather(location: str) -> str:
    """查询某地当前天气。"""
    return f"{location} 当前晴，气温 5-15°C，山上风大，注意保暖。"


# ─── 路线专家 Agent（子图）───
# system_prompt 要明确告诉它"何时该交接"——这是 Handoffs 的关键
route_agent = create_agent(
    model=model,
    tools=[search_routes],
    system_prompt=(
        "你是徒步路线专家，只回答路线相关问题。"
        "如果用户的问题和天气有关，明确说'我来帮你转到天气专家'，"
        "然后结束本轮回答，不要强行回答天气问题。"
    ),
)

# ─── 天气专家 Agent（子图）───
weather_agent = create_agent(
    model=model,
    tools=[get_weather],
    system_prompt=(
        "你是天气专家，只回答天气相关问题。"
        "如果用户的问题和路线有关，明确说'我来帮你转到路线专家'，"
        "然后结束本轮回答，不要强行回答路线问题。"
    ),
)
```

注意每个 Agent 的 `system_prompt` 里都写明了"什么情况下该交接"——这是 Handoffs 能正常工作的前提。Agent 自己得知道"这事不归我管时，说出来"，否则交接判断函数无从下手。

### 2.3 交接判断：条件边路由

交接的"判断"用一个函数实现，它检查当前 Agent 的最后一条回复，决定要不要转、转给谁。这个函数会被挂到条件边上。

```python
def should_handoff(state: HandoffState) -> str:
    """条件边判断函数：当前 Agent 回完后，决定下一步去哪。
    返回值是下一个节点名（标记节点或 END）。"""
    last_msg = state["messages"][-1].content
    current = state.get("current_agent", "")

    # 防"乒乓"死循环：当前已经在 weather 了，就不往 weather 再转
    # 注意：返回的是标记节点（set_weather），不是 agent 节点
    # 这样交接时会先经过标记节点更新 current_agent，再进入目标 Agent
    if "天气" in last_msg and current != "weather":
        return "set_weather"
    elif "路线" in last_msg and current != "route":
        return "set_route"
    # 不需要交接，结束本轮
    return END
```

这里有一个**必须防的坑**：判断条件里一定要带上 `current != "weather"` 这样的"不在自己这儿才转"的约束。否则 A 转给 B、B 看到关键词又转回 A，就死循环了。这个坑后面踩坑记录会展开。

### 2.4 完整 Handoffs 流程：组装 StateGraph

把两个 Agent 子图作为节点，用条件边连成交互网络。再补一个 `set_current` 小节点，在进入某个 Agent 前把 `current_agent` 标记成它——这样 `should_handoff` 才能正确判断"当前在谁那儿"。

```python
from langgraph.checkpoint.memory import InMemorySaver


def set_current_route(state: HandoffState) -> dict:
    """进入路线Agent前，标记当前接管者是route。"""
    return {"current_agent": "route"}


def set_current_weather(state: HandoffState) -> dict:
    """进入天气Agent前，标记当前接管者是weather。"""
    return {"current_agent": "weather"}


# ─── 组装图 ───
builder = StateGraph(HandoffState)

# 节点：标记节点 + Agent子图节点交替
builder.add_node("set_route", set_current_route)
builder.add_node("route_agent", route_agent)
builder.add_node("set_weather", set_current_weather)
builder.add_node("weather_agent", weather_agent)

# 入口：先走路线Agent（假设用户先问路线）
builder.add_edge(START, "set_route")
builder.add_edge("set_route", "route_agent")

# 路线Agent回完后，判断要不要交接
# should_handoff 返回 "set_weather" 时，先更新 current_agent 再进 weather_agent
builder.add_conditional_edges("route_agent", should_handoff)
# 天气Agent回完后，也判断要不要交接
builder.add_conditional_edges("weather_agent", should_handoff)

# 标记节点 → 对应Agent 的固定边
builder.add_edge("set_weather", "weather_agent")

app = builder.compile(checkpointer=InMemorySaver())
```

对应的图结构长这样：

```
            ┌───────────┐     ┌────────────┐
 START ───► │ set_route │ ──► │ route_agent│ ─────┐ should_handoff
            └─────┬─────┘     └────────────┘      │  ├─(天气)─► ┌────────────┐
                  ▲                              │            │set_weather │
                  │                              │            └─────┬──────┘
                  └──(路线)── should_handoff ────┤                  ▼
                              从 weather_agent    │            ┌────────────┐
                              返回"set_route"     │            │weather_agent│
                                                  │            └─────┬──────┘
                                                  └─(END)           │ should_handoff
                                                                    ├─(路线)─► set_route
                                                                    └─(END)

  交接路径：route_agent ──(天气)──► set_weather ──► weather_agent
            weather_agent ──(路线)──► set_route ──► route_agent
  关键：条件边先跳到标记节点更新 current_agent，再进入目标 Agent
```

### 2.5 跑起来看交接过程

```python
config = {"configurable": {"thread_id": "demo-1"}}

# 第一轮：用户问路线
print("=== 用户：我想去四姑娘山，怎么走？===")
result = app.invoke(
    {"messages": [{"role": "user", "content": "我想去四姑娘山，怎么走？"}]},
    config,
)
print("回复:", result["messages"][-1].content)
print("当前接管:", result["current_agent"])  # → route

# 第二轮：接着问天气，触发交接
print("\n=== 用户：那边天气怎么样，要带什么衣服？===")
result = app.invoke(
    {"messages": [{"role": "user", "content": "那边天气怎么样，要带什么衣服？"}]},
    config,  # 同一个 thread_id，接续上文
)
print("回复:", result["messages"][-1].content)
print("当前接管:", result["current_agent"])  # → weather（交接成功）
```

运行后你会看到：第一轮 `current_agent` 是 `route`，路线 Agent 回答了路线；第二轮因为消息里提到"天气"，`should_handoff` 触发，控制权交给 `weather_agent`，`current_agent` 变成 `weather`，天气 Agent 带着完整历史直接回答。这就是一次完整的 Handoff。

---

## 三、Subagents vs Handoffs 深度对比

Day 02 学了 Subagents，今天学了 Handoffs，现在把它们放在一起做一次彻底的对比。这是本周建立"选型判断力"的关键一课。

### 3.1 控制权模型：星型 vs 链式

两种模式的拓扑结构根本不同：

```
Subagents（星型）               Handoffs（链式 / 网状）

        子AgentB                   AgentA ──► AgentB
          ▲                          ▲          │
          │                          │ 交接     ▼ 交接
     主Agent(中心)                  AgentC ◄────┘
          │
          ▼
        子AgentC

  主Agent是唯一的控制中心          控制权在Agent间流动，没有中心
  所有调用都经过主Agent            交接后原Agent退场
```

星型结构意味着主 Agent 是**单点**——它要理解所有领域、承担所有调度；链式结构意味着控制权是**流动**的，每个 Agent 只关心"我自己会不会"和"该转给谁"。

### 3.2 上下文管理：隔离 vs 共享

这是两种模式在工程上最实在的差异，直接决定 token 消耗和对话连贯性：

| 维度 | Subagents | Handoffs |
|------|-----------|----------|
| 主 Agent 上下文 | 精简，只看子 Agent 返回的结论 | 不存在"主"，当前 Agent 看全量历史 |
| 子 Agent 上下文 | 隔离，每次调用是独立的，互不可见 | 共享，所有 Agent 看同一份 messages |
| 上下文连续性 | 不连续（每次调用重新组装） | 连续（对话历史一直在） |
| 隔离性 | 强（子 Agent 之间互不可见） | 弱（谁接管谁都能看到全部历史） |
| token 消耗 | 单次低（上下文短），但调用次数多 | 单次高（历史累积），但调用次数少 |

一句话总结：**Subagents 用"隔离"换"精简"，Handoffs 用"共享"换"连续"**。没有绝对优劣，看你更在乎哪个。

### 3.3 适用场景

把前面散落的对比收束成一张选型表：

| 维度 | Subagents | Handoffs |
|------|-----------|----------|
| 控制权 | 主 Agent 集中控制 | Agent 间流转 |
| 用户交互 | 只和主 Agent | 和当前接管的 Agent |
| 上下文 | 隔离，每次重新组装 | 共享，连续不断 |
| 并行能力 | 强（一步调多个子 Agent） | 弱（接力式，天然串行） |
| 适合场景 | 并行任务、多领域汇总 | 多轮对话、角色切换、状态流转 |
| 典型例子 | 徒步规划（路线+天气+装备并行查） | 客服（售前→技术→售后接力） |

记忆口诀：**要并行、要汇总 → Subagents；要连续、要接力 → Handoffs**。

### 3.4 性能对比：同一个任务两种实现

拿"查路线 + 查天气"这个任务，分别用两种模式跑，看看调用和开销的差异（数字是示意，取决于具体实现）：

```
Subagents 流程：
  1. 主Agent 调用 → 决定派活            (模型调用1)
  2. 主Agent → 路线Agent(tool)          (模型调用2，子Agent内部)
  3. 主Agent → 天气Agent(tool)          (模型调用3，子Agent内部)
  4. 主Agent 综合两份结论 → 回复        (模型调用4)
  合计：4 次模型调用，但每次上下文都短

Handoffs 流程：
  1. 路线Agent 接管，查路线              (模型调用1)
  2. 交接 → 天气Agent 接管，查天气       (模型调用2)
  3. 天气Agent 回复（带完整历史）         (模型调用3)
  合计：3 次模型调用，但上下文在累积变长
```

| 指标 | Subagents | Handoffs |
|------|-----------|----------|
| 模型调用次数 | 4 次 | 3 次 |
| 单次上下文长度 | 短 | 长（累积） |
| 首次响应 | 慢（要等主Agent综合） | 快（专家直接答） |
| 多轮追问效率 | 每次重新调子Agent | 上下文连续，更高效 |
| 并行性 | 高 | 低 |

特别注意"多轮追问"这一行——这是 Handoffs 的甜蜜点。当用户会连续问、来回切换时，Handoffs 因为上下文连续，省掉了 Subagents 每次重新组装上下文的开销，反而更省。但如果是"一次性查三件事然后综合"，Subagents 的并行优势就出来了。

---

## 动手实验

### 🟢 青铜：跑通 Handoffs 最小示例

把第二节的代码拼成一个 `handoffs_demo.py` 跑起来。输入"我想去四姑娘山，怎么走？"，再追问"那边天气怎么样"。观察：
1. 第一轮 `current_agent` 是什么？
2. 第二轮有没有触发交接？`current_agent` 变成了什么？
3. 在 `should_handoff` 里加一行 `print`，打印每次判断的结果，亲眼看到"交接"发生。

目标：跑通最小闭环，确认控制权真的在两个 Agent 之间流动了。

### 🟡 白银：客服三段式交接

把双 Agent 扩展成三段式客服：**售前 Agent → 技术 Agent → 售后 Agent**。场景设计：
1. 用户问"你们这个徒步装备有什么功能" → 售前接管
2. 用户说"我买的帐篷杆断了，怎么修" → 交接给技术
3. 用户说"算了我要退货退款" → 交接给售后

要求：
1. 定义三个 `create_agent`，各自有不同的工具和 system_prompt
2. `should_handoff` 要能识别三种交接信号（售前→技术→售后）
3. 三个 Agent 之间能正确接力，不出现死循环
4. 画出这个三节点交接的 ASCII 图，贴进实验记录

提示：交接信号可以从用户消息里抓关键词（"修/坏"→技术，"退/退款"→售后），也可以让 Agent 在回复里说"帮你转到XX"。

### 🔴 王者：Subagents vs Handoffs 同任务对比

用同一组工具（路线 + 天气）分别实现 Subagents 版和 Handoffs 版，跑完全相同的对话（3 轮以上），记录对比数据：

1. 每轮的模型调用次数（用 LangSmith 或手动计数）
2. 每轮的 token 消耗（`response.usage_metadata`）
3. 每轮的响应时间
4. 多轮追问时，两种模式的上下文长度变化曲线

最终输出一张对比表，并写一段 200 字的结论：什么情况下 Handoffs 更优？什么情况下 Subagents 更优？把这个判断沉淀成你自己的选型规则。

---

## 踩坑记录 🕳️

### 坑 1：交接判断没加"不在自己这儿才转"，导致乒乓死循环

```python
# 反例（危险）：A 转给 B，B 看到关键词又转回 A，死循环
def should_handoff(state) -> str:
    last = state["messages"][-1].content
    if "天气" in last:
        return "weather_agent"   # 没判断当前是不是已经在 weather 了！
    elif "路线" in last:
        return "route_agent"
    return END
```

**症状**：天气 Agent 回了一句"明天天气晴，适合走路线"，里面带了"路线"两个字，`should_handoff` 立刻又把它转回路线 Agent，路线 Agent 再回一句带"天气"的，又转回来……无限循环直到达到递归上限报错。

**解决**：判断条件必须带"当前不是这个 Agent 才转"的约束。用 `current_agent` 字段做这个判断：

```python
# 正例：带 current_agent 防乒乓
def should_handoff(state) -> str:
    last = state["messages"][-1].content
    current = state.get("current_agent", "")
    if "天气" in last and current != "weather":   # 当前不在weather才转
        return "weather_agent"
    elif "路线" in last and current != "route":   # 当前不在route才转
        return "route_agent"
    return END
```

### 坑 2：State 共享导致上下文无限膨胀

Handoffs 所有 Agent 共享同一份 `messages`，这是它"上下文连续"的优点，但也是它最大的坑——**对话越长，上下文越大，token 消耗线性增长**。

```
第1轮：messages = [用户1]                     → 短
第5轮：messages = [用户1, AI1, 用户2, AI2, ...] → 长
第20轮：messages 已经塞满历史                   → 贵 + 可能超窗口
```

**应对**：长对话场景下要做上下文管理——可以用 LangGraph 的消息裁剪（`trim_messages`）、摘要压缩，或者定期把旧消息压缩成一条 summary。这是 Day 06 上下文工程的主题，今天先知道这个坑存在。

### 坑 3：子 Agent 的 system_prompt 没写清"何时该交接"

```python
# 反例：system_prompt 没交代交接，Agent 会"强行回答"不擅长的问题
weather_agent = create_agent(
    model=model, tools=[get_weather],
    system_prompt="你是天气专家。",   # 太模糊
)
# 结果：用户问路线，天气Agent硬编一段路线，不会触发交接
```

**解决**：system_prompt 必须明确两件事——"你擅长什么"和"什么情况下你该说'帮你转到XX'"。交接的信号是 Agent 自己"说"出来的，prompt 不交代，交接就触发不了。这也是 Handoffs 和 Subagents 的区别：Subagents 的路由是主 Agent 决定的，Handoffs 的路由是当前 Agent"主动出让"的，所以当前 Agent 的 prompt 要更精心设计。

### 坑 4：把 Handoffs 用在需要并行的场景

Handoffs 本质是接力（串行），**不适合并行**。如果你发现自己在 Handoffs 里想办法"同时调两个 Agent"，那说明场景选错了——这种情况天生该用 Subagents。

判断标准：如果任务是"一次性收集多个独立信息然后综合"，用 Subagents；如果任务是"一个对话流里在不同角色间切换"，用 Handoffs。别拿锤子拧螺丝。

---

## 副线笔记

### Handoffs 模式的代表：OpenAI Swarm

提到 Handoffs，绕不开 OpenAI 2024 年开源的 **Swarm** 框架——它是 Handoffs 模式最纯粹的体现。Swarm 的核心概念就两个：

- **Agent**：封装了指令、工具的实体
- **Handoff function**：一个特殊函数，调用它就把控制权交给目标 Agent

Swarm 的设计哲学和今天讲的一模一样：没有"主 Agent"，Agent 之间通过 handoff 函数接力，用户始终和当前接管的 Agent 对话。Swarm 后来演进进了 OpenAI 的 Agents SDK（`agents.handoffs`），思路不变。

### LangGraph 的官方 Handoffs 实现

我们今天手写了 `current_agent` + 条件边来教学，但 LangGraph 官方提供了更高层的封装，生产环境直接用：

```python
# 官方预构建：pip install langgraph-swarm
from langchain.agents import create_agent
from langgraph_swarm import create_swarm, create_handoff_tool
from langgraph.types import Command

# 1. 造交接工具：调用它 = 把控制权交给目标Agent
transfer_to_hotel = create_handoff_tool(
    agent_name="hotel_assistant",
    description="转给酒店预订助手",
)

# 2. 每个Agent带上"自己的工具 + 交接工具"
flight_assistant = create_agent(
    model="openai:gpt-4o",
    tools=[book_flight, transfer_to_hotel],
    system_prompt="你是机票助手，需要订酒店就转给酒店助手",
    name="flight_assistant",
)
hotel_assistant = create_agent(
    model="openai:gpt-4o",
    tools=[book_hotel],
    system_prompt="你是酒店助手",
    name="hotel_assistant",
)

# 3. 一行组装 Swarm
swarm = create_swarm(
    agents=[flight_assistant, hotel_assistant],
    default_active_agent="flight_assistant",
).compile()
```

官方做法和我们的手写版有两个关键升级：

1. **交接靠 `Command` 原语**：`Command(goto="目标Agent", update={...}, graph=Command.PARENT)`，框架层面识别这个原语就知道"要跳节点"了，不用我们手写条件边。
2. **交接是工具**：Agent 调一个 `transfer_to_XX` 工具就完成交接，比"在回复里说关键词、再用条件边抓关键词"更可靠。

### 谁在用 Handoffs 模式

- **客服系统**：售前 → 技术 → 售后的经典接力，是 Handoffs 的教科书场景
- **多角色对话**：销售助手聊着聊着转给财务助手核对账单
- **复杂工单流转**：一线支持 → 二线专家 → 升级处理，每段交接带状态
- **Claude/OpenAI 的智能体团队**：2026 年主流的多 Agent 编排都内置了 handoff 机制

**选型直觉**：只要你的场景里有"接力""转接""流转"这几个词，先想到 Handoffs；只要场景里有"同时""汇总""并行"，先想到 Subagents。

---

## 检查清单

- [ ] 理解 Handoffs 的控制权交接机制：交接 = 改共享 State 里的 `current_agent` 字段
- [ ] 实现了状态驱动的 Agent 交接（`create_agent` 子图 + 条件边 + `current_agent`）
- [ ] 能说出 Subagents 和 Handoffs 的 3 个区别（控制权模型 / 用户交互 / 上下文管理）
- [ ] 知道什么场景该用 Handoffs（多轮对话、角色切换、接力流转）
- [ ] 跑通了 `handoffs_demo.py`，亲眼看到 `current_agent` 在两个 Agent 间切换

---

## 下课预告

明天 **Day 04 — Router + Skills：路由分类与按需知识加载**。

今天 Handoffs 解决了"控制权在 Agent 间流动"的问题，但有个前提——每个 Agent 得是独立实体。可如果任务其实没那么复杂，一个 Agent 就能干，只是它"知识不够"怎么办？明天学两种"不分裂 Agent、但给它补充能力"的思路：

- **Router**：先给用户意图分类，再把整件事派给对应的专门 Agent（适合分类明确的场景）
- **Skills**：单 Agent 保持控制，按需把专门知识当"技能"加载进上下文（适合单 Agent 够用、只需补知识的场景）

两者都是"比 Handoffs 更轻"的协作方式，和 Subagents / Handoffs 凑齐四大模式。明天把它们补完，你就拥有了完整的选型武器库。
