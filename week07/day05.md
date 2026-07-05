# Day 05 — Deep Agents：create_deep_agent

## 学习目标

前四天我们手写了多 Agent 的四大模式：Day 02 用 `@tool` 把子 Agent 包装成工具调用实现 **Subagents**，Day 03 用共享 State + 条件边实现 **Handoffs**，Day 04 又学了 **Router** 分类派活和 **Skills** 按需加载知识。每一关你都在"亲手组装"——写包装 tool、写状态路由、写 load_skill、写 current_agent 判断函数。这套手写练习的价值在于：你彻底理解了每个模式背后在发生什么，出了问题知道往哪查。

但手写的代价也很明显——同样一个"徒步规划 + 文件记录 + 长期记忆"的 Agent，用四大模式拼出来要几十行甚至上百行配置。LangChain 在 2026 年推出了一个高层框架 **Deep Agents**，它把这四种能力（外加一个手写时完全没有的"虚拟文件系统"）打包成了 `create_deep_agent` 一行创建。今天我们就来看看这个"超级封装"到底封装了什么、什么时候该用它、什么时候还是该老老实实手写。

学完今天你能：
1. 理解 Deep Agents 的定位：把 Subagents + 文件系统 + Memory + Skills 打包成一行创建的"超级 Agent"
2. 掌握 create_deep_agent 的核心配置：model、tools、skills、subagents、store，知道每个参数背后对应前四天的哪套手写实现
3. 能用 create_deep_agent 创建带虚拟文件系统的 Deep Agent，理解它如何通过"写文件再读文件"管理长上下文
4. 理解 Deep Agents vs 手写多 Agent 的取舍：便利性 vs 灵活性，知道什么场景选框架、什么场景选手写

---

## 一、什么是 Deep Agents

### 1.1 回顾：前四天我们手写了什么

先把前四天的"手写成本"摆出来，今天才能体会 Deep Agents 到底省了什么：

| 关卡 | 模式 | 你手写了什么 | 典型代码量 |
|------|------|------------|-----------|
| Day 02 | Subagents | `@tool` 包装子 Agent、手动 invoke 提取 `.content` | ~50 行 |
| Day 03 | Handoffs | `current_agent` 字段、`should_handoff` 条件边、标记节点 | ~80 行 |
| Day 04 | Skills | `load_skill` 工具、技能库字典、手动注入上下文 | ~40 行 |
| Day 04 | Router | 分类节点、意图判断函数、条件边路由 | ~60 行 |

每一块单独看都不算多，但当你要把它们**组合**起来——一个 Agent 既要协调子 Agent、又要按需加载技能、又要跨会话记忆、又要管理长上下文——手写组装的复杂度会陡增。而且有一块能力手写根本搞不定：**让 Agent 自己读写文件来管理上下文**。

### 1.2 Deep Agents 的定位

Deep Agents 是 LangChain 2026 年推出的高层多 Agent 框架。它的核心理念用一句话讲：

> **一个"深度 Agent" = Agent + 虚拟文件系统 + 长期记忆 + 技能库 + 子代理**

注意等号右边第一个就是"Agent"——Deep Agents 不是把 Agent 推翻重做，而是在标准 ReAct Agent（`create_agent`）之上，叠加了一层"开箱即用的能力"。这些能力大多是你前四天手写过的，只是现在框架替你封装好了。

```
Deep Agents = create_agent（你 Week 06 学过的标准 ReAct Agent）
            + 虚拟文件系统（新能力，前四天没有）
            + Memory（Week 06 的 InMemoryStore）
            + Skills（Day 04 的 Skills 模式）
            + Subagents（Day 02 的 Subagents 模式）
            + 上下文自动管理（防止窗口溢出）

  底层都是 LangGraph 图，create_deep_agent 是 create_agent 的超集
```

### 1.3 Deep Agents 的五大内置能力

把内置能力和前四天的手写实现对应起来，你会一眼看懂"封装了什么"：

| 能力 | 说明 | 对应前四天的手写实现 |
|------|------|-------------------|
| 虚拟文件系统 | Agent 可以读写文件，把中间结果落盘、按需取回，管理长上下文 | 手写没有，是全新能力 |
| Memory | 跨会话长期记忆，记住用户偏好和历史 | Week 06 的 InMemoryStore |
| Skills | 按需加载专业知识，不一开始就塞满上下文 | Day 04 的 Skills 模式 |
| Subagents | 内置子 Agent 协调，主 Agent 可委托任务 | Day 02 的 Subagents 模式 |
| 上下文管理 | 自动管理上下文窗口，防止溢出 | 手写需要自己 trim / 摘要 |

前四行你都很熟了——前三行就是把你前四天手写的 `@tool` 包装、`load_skill`、`InMemoryStore` 换成框架内置参数。真正的新东西是**虚拟文件系统**和**上下文自动管理**，这也是 Deep Agents 区别于"单纯把四大模式打包"的关键，今天第三节会重点讲。

### 1.4 适合 / 不适合的场景

Deep Agents 不是银弹，它有自己的甜蜜点：

- **适合**：需要处理大量信息且要持久化（文件系统）、需要长期记忆（跨会话）、多步骤复杂任务（子 Agent + 技能协同）、上下文会膨胀到溢出的场景
- **不适合**：简单任务（杀鸡用牛刀，一个 `create_agent` 就够了）、需要精确控制每一步流程的场景（框架约束多，黑盒重）、调试要求高可观测性的场景

一句话：**Deep Agents 适合"重场景"，手写适合"要控场"**。第五节会专门展开这个取舍。

---

## 二、create_deep_agent 入门

### 2.1 最小用法

导入方式和 `create_agent` 在同一个包下，参数也高度兼容：

```python
from langchain.agents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool

model = init_chat_model("gpt-4o-mini", temperature=0)

@tool
def search_routes(destination: str) -> str:
    """查询去某地的徒步路线。"""
    return f"去 {destination} 的路线：成都 → 四姑娘山镇，全程约 200km。"

@tool
def get_weather(location: str) -> str:
    """查询某地当前天气。"""
    return f"{location} 当前晴，气温 5-15°C，山上风大。"

# 一行创建带文件系统的 Deep Agent
agent = create_deep_agent(
    model=model,
    tools=[search_routes, get_weather],
    system_prompt="你是徒步规划助手，可以读写文件来保存规划信息。",
)
```

到这里你创建的 Agent 已经**自动获得了文件操作工具**（`write_file`、`read_file`、`list_files`、`delete_file`）——你没有在 `tools` 里写它们，框架送的。这就是"一行创建超级 Agent"的体感。

### 2.2 和 create_agent 的关系

这两者的关系要理清，很多人会混淆：

| 维度 | create_agent | create_deep_agent |
|------|--------------|-------------------|
| 产物 | 标准 ReAct Agent | 带 FS + Memory + Skills + Subagents 的 Agent |
| 文件系统 | 无 | 内置 |
| Memory | 手动配 store | 内置（传 store 即可） |
| Skills | 手写 load_skill | 内置（传 skills 参数） |
| Subagents | 手写包装 tool | 内置（传 subagents 参数） |
| 底层 | LangGraph 图 | LangGraph 图（是 create_agent 的超集） |

```
create_agent          ── 标准 ReAct（Week 06 学过）
      ▲
      │ 扩展
create_deep_agent     ── = create_agent + FS + Memory + Skills + Subagents
```

记住一句话：**create_deep_agent 是 create_agent 的超集**。它能做的事 create_agent 都能做（只是要手写），create_agent 做不了的事（文件系统、自动上下文管理）才是 Deep Agents 真正的增量。

---

## 三、虚拟文件系统（重点）

这是 Deep Agents 最有价值、也最需要专门讲的能力。前四天手写四大模式时，所有中间结果都只能存在 `messages` 里——上下文越堆越长，最后要么爆窗口、要么模型注意力涣散。虚拟文件系统给了 Agent 一个"外部记事本"。

### 3.1 为什么 Agent 需要文件系统

把中间结果写在文件里而不是塞在 messages 里，有三个直接好处：

1. **上下文窗口有限**：把路线 JSON、天气数据这些"大块中间结果"写入文件，messages 里只留一句"已写入 route_info.md"，需要细节时再 `read_file` 取回——按需加载，不再全量堆在对话里
2. **结构化**：文件有名字、有内容，比塞在 messages 里的一堆文本更结构化，Agent 检索和引用都更清晰
3. **跨会话持久化**：配合 Memory，文件内容可以跨会话保留，下次对话直接读上次的文件接着干

```
传统 Agent（无文件系统）：                 Deep Agent（有文件系统）：

messages = [                              messages = [
  user: "查川西路线和天气",                   user: "查川西路线和天气",
  ai: 查路线 tool_call,                      ai: 查路线 tool_call,
  tool: [一大段路线JSON]  ← 堆这儿              tool: [路线JSON],
  ai: 查天气 tool_call,                      ai: write_file("route.md", ...) ← 写文件
  tool: [一大段天气数据]  ← 堆这儿              ai: 查天气 tool_call,
  ai: 综合分析...（前面全要重看）              tool: [天气数据],
]                                            ai: write_file("weather.md", ...) ← 写文件
  ↑ 上下文越来越长，易溢出                    ai: 综合分析（按需 read_file）
                                           ]
                                             ↑ messages 短，细节在文件里
```

### 3.2 Deep Agent 自动获得的文件工具

你只要用了 `create_deep_agent`，框架就会自动给 Agent 配上这四个工具（不用你写）：

| 工具 | 作用 |
|------|------|
| `write_file(path, content)` | 把内容写入虚拟文件系统的一个文件 |
| `read_file(path)` | 读取指定文件的内容 |
| `list_files()` | 列出虚拟文件系统里现有的所有文件 |
| `delete_file(path)` | 删除指定文件 |

这些文件是**虚拟的**——存在 Agent 的内存空间里（配合 store 可持久化），不是你磁盘上的真实文件。这点是踩坑高频区，后面会强调。

### 3.3 实战：徒步规划 Deep Agent

来看一个完整的徒步规划场景，体会 Agent 怎么自主用文件系统管理流程：

```python
"""Deep Agent 实战：徒步规划，用文件系统记录中间结果"""
from langchain.agents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.store.memory import InMemoryStore

model = init_chat_model("gpt-4o-mini", temperature=0)

@tool
def search_routes(destination: str, days: int) -> str:
    """查询去某地的徒步路线方案。"""
    return f"{destination} {days}天路线：D1 成都→康定；D2 康定→新都桥；D3 新都桥→丹巴"

@tool
def get_weather(location: str) -> str:
    """查询某地天气。"""
    return f"{location}：多云转晴，5-18°C，风力2级，紫外线强"

@tool
def generate_gear(route_difficulty: str, weather: str) -> str:
    """根据路线难度和天气生成装备清单。"""
    return f"难度{route_difficulty}、天气{weather} → 装备：冲锋衣/登山杖/头灯/防晒"

# Deep Agent 自带文件系统，不用手动加 write_file 等工具
agent = create_deep_agent(
    model=model,
    tools=[search_routes, get_weather, generate_gear],
    system_prompt="""你是徒步规划助手。
请把检索到的路线信息写入文件 route_info.md，
天气信息写入 weather.md，
最终规划方案写入 plan.md。
回答用户时，先读取 plan.md 再总结。""",
    store=InMemoryStore(),  # 跨会话记忆
)

# Agent 会自主使用文件系统
result = agent.invoke({
    "messages": [{"role": "user", "content": "帮我规划川西3天徒步，把路线和天气都记下来"}]
})

# Agent 内部流程（框架自动编排）：
# 1. search_routes("川西", 3) → 拿到路线 → write_file("route_info.md", 路线)
# 2. get_weather("川西") → 拿到天气 → write_file("weather.md", 天气)
# 3. 综合分析（可能读回两个文件）→ write_file("plan.md", 规划)
# 4. read_file("plan.md") → 总结回复用户
print(result["messages"][-1].content)
```

注意 system_prompt 里那句"把信息写入文件"的指令——Deep Agent 真的会照做。这就是文件系统的价值：Agent 自己决定什么时候写、写哪个文件、什么时候读回来，你不用在代码里编排这套流程。

### 3.4 长上下文管理的本质

把"写文件再读文件"这套机制抽象一下，它解决的其实是**长上下文管理**问题：

```
任务长、信息多的场景（比如"帮我调研10条徒步路线并对比"）：

无文件系统：
  messages 累积 10 条路线的完整数据 → 上下文爆炸 → 模型开始遗忘前面的内容

有文件系统：
  每条路线 → write_file("route_1.md" ... "route_10.md")
  messages 里只剩简短的"已写入 route_X.md"
  最后对比时 → 按需 read_file，一次取一个文件来分析
  上下文始终可控，不会随数据量线性膨胀
```

这套思路在前端也能找到类比——你不会把一个长列表的所有数据一次性塞进组件 state，而是用虚拟列表按需渲染。Deep Agent 的文件系统就是"虚拟列表"的那个按需取回机制。

### 3.5 token 消耗对比：量化文件系统的价值

"文件系统能省上下文"这句话到底省多少？用一个具体场景量化。假设要查 5 条川西徒步路线并对比，两种方案的上下文负担对比（数字是示意）：

```
无文件系统（全堆 messages）：
  messages = [user, ai, tool(路线1~800字), ai, tool(路线2~800字), ... 5条]
  上下文 ≈ 用户提问 + 5×800字路线数据 + 中间推理 ≈ 5000+ 字
  → 最后一轮对比时，模型要把 5000 字全重看一遍，注意力涣散

有文件系统（落盘按需取回）：
  messages = [user, ai, write_file(路线1), ai, write_file(路线2), ... 5次写入]
  上下文 ≈ 用户提问 + 5×"已写入route_X.md(~15字)" ≈ 800 字
  最后对比时：按需 read_file，一次取一个文件分析，每次上下文可控
  → 上下文峰值始终在 1000 字以内
```

| 指标 | 无文件系统 | 有文件系统 |
|------|-----------|-----------|
| 上下文峰值 | ~5000 字（随数据量线性增长） | ~1000 字（基本恒定） |
| 模型注意力 | 被大量原始数据稀释 | 每轮只关注当前文件 |
| 跨会话延续 | 做不到（messages 不持久） | 读上次写的文件即可 |
| 适合数据量 | 小（几条） | 大（几十上百条） |

数据量越大，文件系统的优势越明显。这也是为什么 Deep Agents 把文件系统作为"第一能力"——它解决的是 Agent 能不能扛住长任务的根本问题。

---

## 四、Memory + Skills + Subagents

文件系统之外，Deep Agent 还内置了另外三种能力。它们本质就是把你前四天手写的东西换成参数，理解起来很快。

### 4.1 Memory 配置：跨会话记忆

Day 04 我们用 `InMemoryStore` 做过跨会话记忆，那时要手动在节点里读写 store。Deep Agent 把这步内置了——传一个 `store` 进去就行：

```python
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()

agent = create_deep_agent(
    model=model,
    tools=[search_routes, get_weather],
    system_prompt="你是徒步规划助手，记住用户的偏好。",
    store=store,  # ← 传进去，Agent 自动获得跨会话记忆能力
)

# 第一次会话：告诉 Agent 偏好
agent.invoke(
    {"messages": [{"role": "user", "content": "我喜欢轻装徒步，装备越少越好"}]},
    config={"configurable": {"thread_id": "session-1"}},
)

# 第二次会话（不同 thread_id）：Agent 记得你的偏好
result = agent.invoke(
    {"messages": [{"role": "user", "content": "推荐一条路线并给装备"}]},
    config={"configurable": {"thread_id": "session-2"}},
)
# Agent 会记得"轻装"偏好，推荐难度低、装备精简的方案
```

对比 Day 04：那时你要在节点里 `store.put(namespace, key, value)` 写、`store.get(...)` 读，现在框架全包了。

### 4.2 Skills 内置：不用手写 load_skill

Day 04 你手写过 `load_skill` 工具和技能库字典。Deep Agent 直接用一个 `skills` 参数搞定，框架会替你实现"按需加载"的逻辑：

```python
# 技能库：一个字典，key 是技能名，value 是专业知识描述
skills = {
    "weather_analysis": (
        "分析天气时注意：1.区分实时和预报 2.给出穿衣建议 3.提醒安全风险"
    ),
    "route_evaluation": (
        "评估路线时注意：1.难度等级 2.季节适宜性 3.补给点位置 4.下撤路线"
    ),
}

agent = create_deep_agent(
    model=model,
    tools=[search_routes, get_weather, generate_gear],
    system_prompt="你是徒步规划助手，处理天气和路线问题时加载对应技能。",
    skills=skills,  # ← 传进去，Agent 自动按需加载技能到上下文
)
```

Agent 会根据当前任务自己判断"要不要加载 weather_analysis 技能"，加载后把技能描述注入到本轮上下文里。和 Day 04 手写的 `load_skill` 效果一样，但你不用写那个 tool 了。

### 4.3 Subagents 内置：一行挂载子 Agent

Day 02 你手写 `@tool` 包装子 Agent、手动 invoke 提取 `.content`。Deep Agent 用 `subagents` 参数直接挂载，框架替你做包装：

```python
from langchain.agents import create_agent

# 先创建一个子 Agent（用标准 create_agent）
route_subagent = create_agent(
    model=model,
    tools=[search_routes],
    system_prompt="你是路线专家，只回答路线问题，简洁给结论。",
)

# 挂到 Deep Agent 上当子代理
agent = create_deep_agent(
    model=model,
    tools=[get_weather],  # 主 Agent 自己留天气工具
    system_prompt="你是徒步规划主助手，路线问题委托给路线专家。",
    subagents=[route_subagent],  # ← 内置子代理，框架自动包装成可委托的 tool
)

# 主 Agent 遇到路线问题会自动委托给 route_subagent
result = agent.invoke(
    {"messages": [{"role": "user", "content": "川西路线怎么样？天气如何？"}]}
)
# 内部：路线部分委托 route_subagent，天气部分主 Agent 自己查，最后综合
```

对比 Day 02：那时 `ask_route_expert` 这个 `@tool` 是你手写的，内部 `route_expert.invoke(...)` + 提取 `.content` 也是你手写的。现在框架替你做了，你只要把子 Agent 塞进 `subagents` 列表。

> **注意**：Deep Agent 内置的 subagents 和你 Day 02 手写的 Subagents，行为**大体一致**但**不一定完全相同**——框架内部可能有额外的协调逻辑（比如上下文传递方式、错误处理）。这也是后面踩坑记录会强调的点：黑盒多，行为细节得实测。

### 4.4 四件套协同：一个完整 Deep Agent

把文件系统、Memory、Skills、Subagents 拼到一个 Deep Agent 里，看看它们怎么协同：

```python
"""完整 Deep Agent：四件套协同"""
from langchain.agents import create_deep_agent, create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.store.memory import InMemoryStore

model = init_chat_model("gpt-4o-mini", temperature=0)

# 主 Agent 自己的工具
@tool
def get_weather(location: str) -> str:
    """查询某地天气。"""
    return f"{location}：晴，5-15°C"

# 子 Agent（Subagents 能力）
route_subagent = create_agent(
    model=model,
    tools=[search_routes],  # 假设 search_routes 已定义
    system_prompt="你是路线专家，简洁给结论。",
)

# 技能库（Skills 能力）
skills = {
    "weather_analysis": "分析天气时注意穿衣和安全提醒",
    "route_evaluation": "评估路线时注意难度和季节适宜性",
}

agent = create_deep_agent(
    model=model,
    tools=[get_weather],          # 主 Agent 的工具
    system_prompt="你是徒步规划助手，路线委托给路线专家，天气自己查，结果写文件。",
    store=InMemoryStore(),        # Memory 能力
    skills=skills,                # Skills 能力
    subagents=[route_subagent],   # Subagents 能力
    # 文件系统自动内置，不用配
)

# 这个 Agent 同时具备：
# - 文件系统：write_file/read_file 管理长上下文
# - Memory：跨会话记住用户偏好
# - Skills：处理天气/路线时加载对应技能
# - Subagents：路线问题委托给 route_subagent
```

四件套各管一摊，互不冲突。这就是 Deep Agents"一行创建超级 Agent"的完整面貌——你前四天要手写上百行的组合，现在一个调用搞定。

---

## 五、Deep Agents vs 手写多 Agent

这是今天最重要的判断力训练。框架好不好用，取决于你的场景。

### 5.1 全维度对比

| 维度 | 手写多 Agent（Day 02-04） | Deep Agents |
|------|--------------------------|-------------|
| 代码量 | 多（手写包装tool、状态路由、load_skill） | 少（一行创建 + 几个参数） |
| 灵活性 | 高（每一步都可控） | 中（受框架约束） |
| 文件系统 | 无（前四天没有这能力） | 内置 |
| Memory | 手动配 Store + 手动读写 | 内置（传 store 即可） |
| Skills | 手写 load_skill + 技能库 | 内置（传 skills 即可） |
| Subagents | 手写 @tool 包装 + 提取 content | 内置（传 subagents 即可） |
| 调试难度 | 可控（自己写的，能看每步） | 较高（黑盒多，文件读写不直观） |
| 上手速度 | 慢（要懂底层） | 快（照着文档传参数） |
| 适合 | 需要精确控制、要可观测性 | 快速搭建复杂 Agent、重场景 |

### 5.2 什么时候用 Deep Agents

符合下面任何一条，优先考虑 Deep Agents：

- 任务需要处理大量信息且要持久化（文件系统是刚需）
- 需要快速搭建一个"多能力 Agent"（内置 Skills + Subagents 省事）
- 不需要精确控制每一步流程，让 Agent 自主编排即可
- 团队想快速验证想法，不想陷在底层组装里

### 5.3 什么时候手写

符合下面任何一条，老老实实手写：

- 流程需要精确控制（比如固定要先查路线再查天气再生成装备，顺序不能乱）
- 调试需要高可观测性（线上出了问题要能逐步排查）
- 团队有经验，想要完全掌控每个细节
- 任务其实很简单（一个 create_agent 就够，Deep Agents 是杀鸡用牛刀）

### 5.4 选型决策树

```
你的任务是？
│
├─ 简单任务（1-2个工具就能搞定）
│   └─ 用 create_agent（Week 06），别上 Deep Agents
│
├─ 复杂任务，但流程要精确控制 / 要可观测
│   └─ 手写四大模式（Day 02-04）
│
└─ 复杂任务，要持久化大量信息 / 要长期记忆 / 要快速搭建
    └─ 用 create_deep_agent
```

记住：**框架和手写不是对立的**。真实项目里经常混用——核心流程手写保证可控，边缘能力（比如文件记录、长期记忆）用 Deep Agents 兜底。选型的本质是判断"这块我愿不愿意交给框架黑盒"。

---

## 动手实验

### 🟢 青铜：让 Deep Agent 用文件系统记事

用第二节的 `create_deep_agent` 创建一个带文件系统的 Agent，给它两个工具（比如 `search_routes` 和 `get_weather`）。让它完成一个任务：查川西路线和天气，并**把结果分别写入 `route.md` 和 `weather.md`**。重点观察：

1. Agent 是否真的调用了 `write_file`？（在工具调用日志里找）
2. Agent 回复时有没有 `read_file` 把文件内容读回来再总结？
3. 如果再问一句"刚才路线写到哪个文件了"，Agent 能不能答上？（验证文件确实存在）

目标：亲眼看到 Agent 自主使用文件系统，确认"虚拟文件系统"不是噱头。

### 🟡 白银：完成 deep_agent_demo.py

把第三节的徒步规划 Deep Agent 整合成一个可运行的 `deep_agent_demo.py`，要求：

1. 定义 `search_routes`、`get_weather`、`generate_gear` 三个工具（可用 mock 数据）
2. 用 `create_deep_agent` 创建 Agent，配置 `store=InMemoryStore()`（Memory）和 `skills`（至少两个技能）
3. 跑两个会话：第一会话让 Agent 规划川西 3 天徒步并写入文件；第二会话（新 thread_id）问"我上次规划的路线是什么"，验证 Memory + 文件系统能跨会话取回
4. 打印每次 Agent 调用了哪些工具（重点看 `write_file` / `read_file` 的调用时机）
5. 在文件里加注释，标注每块对应前四天的哪个手写实现（比如"Memory ← Day 04 InMemoryStore"）

进阶：尝试挂一个 `route_subagent`（用 `create_agent` 创建）到 `subagents` 参数，观察主 Agent 怎么委托任务给子代理。

### 🔴 王者：create_agent vs create_deep_agent 同任务对比

用同一组工具和同一个任务（川西 3 天徒步规划 + 记录），分别用 `create_agent` 和 `create_deep_agent` 实现，记录对比数据：

1. **代码量**：两版各多少行？（Deep Agent 应该明显更少）
2. **功能差异**：`create_agent` 版能不能实现"写文件 + 跨会话记忆"？如果不能，缺了什么、要补多少代码？
3. **可观测性**：两版调试时，哪个更容易看到"Agent 内部在干什么"？Deep Agent 的文件读写你能在哪看到？
4. **灵活性**：尝试在 `create_agent` 版里强制"必须先查路线再查天气"的顺序，再在 Deep Agent 版里做同样的约束——哪个更容易？

最终输出一张对比表 + 一段 200 字结论：什么场景你选 Deep Agents？什么场景你选 create_agent + 手写？

---

## 踩坑记录 🕳️

### 坑 1：以为文件系统是真磁盘，去找文件找不到

Deep Agents 的文件系统是**虚拟的**——存在 Agent 的内存空间里（配合 store 可持久化到内存层），不是你电脑磁盘上的真实文件。你跑完 Agent 去项目目录找 `route_info.md`，肯定找不到。

**症状**：Agent 说"已写入 route_info.md"，你在文件管理器里翻不到，以为 Agent 在骗你。

**解决**：理解文件系统是"Agent 视角的虚拟空间"。要查看文件内容，得让 Agent 自己 `read_file("route_info.md")` 打印出来，或者用框架提供的 API 查询虚拟文件系统状态。这点是 Deep Agents 最大的认知坎。

### 坑 2：create_deep_agent 不是所有版本都有

`create_deep_agent` 是 2026 年 LangChain 新推的高层 API，**老版本没有**。如果你的 `langchain` 版本较旧，导入会直接 `ImportError`。

**解决**：先确认版本，`pip show langchain` 看一眼。需要较新版本（2026 年的发布）。如果项目锁了旧版本又暂时不能升，就只能继续用 `create_agent` + 手写四大模式。这也是为什么前四天的手写练习不是"白学"——版本不兼容时它们是退路。

### 坑 3：subagents 行为和手写 Subagents 不完全一致

Deep Agent 内置的 subagents，框架内部可能有额外的协调逻辑（上下文怎么传、错误怎么兜、子 Agent 之间能不能互相委托），这些细节和你 Day 02 手写的 `@tool` 包装**不一定完全一样**。

**症状**：你期望子 Agent 像手写时那样"调一次返回一个字符串结论"，结果 Deep Agent 的 subagents 可能返回更复杂的结构，或者主 Agent 的委托方式和你预想的不同。

**解决**：别假设框架行为等于手写行为。挂载 subagents 后先跑简单任务，观察主 Agent 实际怎么委托、子 Agent 返回什么格式。黑盒的部分必须实测确认。

### 坑 4：调试困难，文件读写不直接可见

手写多 Agent 时，每一步都是你写的，出问题能逐节点排查。Deep Agents 把文件系统、Memory、Skills 都封装进黑盒了，Agent "为什么读这个文件""为什么加载这个技能"的决策过程不直观。

**应对**：
- 开启 LangSmith 追踪，能看到每一步的 tool 调用（包括 `write_file`/`read_file`）
- 在 system_prompt 里要求 Agent "每次读写文件时口头说明在做什么"，强行让它汇报
- 关键任务别全交给 Deep Agent 黑盒——核心流程手写保证可控，边缘能力用 Deep Agent 兜底

### 坑 5：简单任务上 Deep Agents 反而更慢更贵

Deep Agents 内置的上下文管理、文件系统协调会引入额外的模型调用（比如要决定"该不该写文件""该不该加载技能"）。简单任务上一个 `create_agent` 就能秒回的，上 Deep Agents 可能多绕几步、多花 token。

**解决**：按第五节的决策树选型。简单任务别上 Deep Agents，杀鸡别用牛刀。

---

## 副线笔记

### Deep Agents vs 手写的哲学：Next.js vs 原生 React

这周副线聊一个工程师的核心判断力——什么时候选框架，什么时候手写。

类比前端你最熟：`create_deep_agent` 像 **Next.js**——约定大于配置，文件路由、SSR、API Routes 都给你封装好，开箱即用，但你要按它的规矩来；手写多 Agent 像**原生 React**——自由度高，路由自己定、数据获取自己写，但要搭的脚手架多。

```
Next.js（约定大于配置）              原生 React（自由度高）
  ├ 文件路由自动生效                   ├ 路由自己配（react-router）
  ├ SSR 开箱即用                       ├ SSR 自己搭（要懂同构）
  ├ API Routes 约定路径                ├ API 自己写
  └ 快速出活，但黑盒重                 └ 慢，但每步可控

create_deep_agent（约定大于配置）      手写四大模式（自由度高）
  ├ 文件系统内置                       ├ 文件系统没有，自己造
  ├ Memory/Skills/Subagents 参数化     ├ 每个模式手写 @tool / 条件边
  ├ 快速搭复杂 Agent                   └ 慢，但每步可控
  └ 黑盒多，调试难                     └ 可观测性强
```

**选型直觉**：
- 要快速出活、能接受框架约束 → Deep Agents（Next.js）
- 要精确控场、要可观测性 → 手写（原生 React）
- 真实项目经常混用：核心流程手写，边缘能力用框架兜底（就像 Next.js 项目里关键页面也能 "use client" 退回纯客户端）

什么时候选框架、什么时候手写，是工程师的核心判断力，不是"框架一定好"或"手写一定强"。

### 谁在用 Deep Agent 架构

- **Claude Code / Cursor 这类 AI 编程助手**：内部就是某种 Deep Agent 架构——有文件系统（读写你的代码文件）、有 Memory（记住项目上下文）、有 Skills（按语言/框架加载专业知识）、有 Subagents（搜索子 Agent、测试子 Agent）
- **复杂研究助手**：需要调研大量资料、整理成文档、跨会话延续进度的场景，文件系统 + Memory 是刚需
- **长任务 Agent**：比如"帮我监控某网站一周并每天生成报告"，没有文件系统根本撑不下来

**今日观察任务**：
- 用 Claude Code（或任何 Deep Agent 类工具）处理一个需要"读多个文件 + 改代码 + 跑测试"的任务
- 观察它怎么用文件系统管理中间状态——是不是"读文件→改→写回→再读"循环
- 对照今天的 Deep Agents，找一找它的 Memory、Skills、Subagents 分别体现在哪
- 思考：如果让你用 `create_deep_agent` 复刻一个简化版 Claude Code，subagents 和 skills 该怎么配？

---

## 检查清单

- [ ] 理解 Deep Agents 的五大内置能力（文件系统 / Memory / Skills / Subagents / 上下文管理），能对应到前四天的手写实现
- [ ] 用 `create_deep_agent` 创建了带文件系统的 Agent，亲眼看到它自主调用 `write_file` / `read_file`
- [ ] 理解文件系统如何管理长上下文（中间结果落盘、按需取回、messages 不膨胀）
- [ ] 知道 Deep Agents 内置的 Memory / Skills / Subagents 怎么配（store / skills / subagents 参数）
- [ ] 能说出 Deep Agents 和手写多 Agent 的取舍（便利性 vs 灵活性 / 可观测性）
- [ ] 记住了踩坑：文件系统是虚拟的、版本兼容性、subagents 行为要实测、简单任务别上 Deep Agents

---

## 下课预告

今天 Deep Agents 把四大模式打包成了一行创建，解决了"快速搭复杂 Agent"的问题。但无论是手写多 Agent 还是 Deep Agents，只要任务一复杂、对话一长，就会撞上一个共同的墙——**上下文管理**。多 Agent 系统里上下文怎么不爆、怎么压缩、出了问题怎么排查，是工程化的硬骨头。

明天 **Day 06 — Context Engineering + 多 Agent 调试**。我们会学：
- 多 Agent 系统的上下文为什么会爆（Subagents 的隔离、Handoffs 的共享、Deep Agent 的文件系统各有各的膨胀方式）
- Context Engineering 的手段：`trim_messages`、摘要压缩、选择性记忆
- 多 Agent 调试的可观测性：LangSmith 追踪、逐步排查黑盒

今天 Deep Agents 把问题"封装"了，明天我们反过来把它"拆开看"——上下文到底在怎么流动。这是把多 Agent 从"能跑"推向"能上线"的关键一课。
