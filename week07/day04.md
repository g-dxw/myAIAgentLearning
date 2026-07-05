# Day 04 — Router + Skills：路由与按需知识

## 学习目标

Day 02 的 **Subagents** 让主 Agent 把子 Agent 包装成 tool，攥着控制权调度派活。Day 03 的 **Handoffs** 让控制权在 Agent 间真正交接，用户直接和当前接管的专家对话。这两种模式有个共同点：都把系统**拆成了多个 Agent**，各有独立上下文。当领域跨度大、需要隔离时，这很合适。

但不是所有场景都需要"拆 Agent"。有时候任务没那么复杂——要么分类很明确、派给对应专家就行，要么一个 Agent hold 得住、只是缺一点专业知识。今天补完四大模式的另外两种：**Router** 解决"先分类、再分发"，**Skills** 解决"单 Agent 按需补知识"。学完今天，选型武器库就齐了。

学完今天你能：
1. 理解 Router 模式的核心机制：先有个路由 Agent 做分类，然后一次性分发给对应的专门 Agent
2. 掌握 Skills 模式的核心：单 Agent 保持控制权，通过 load_skill 工具按需加载专门知识
3. 能用 LangGraph 实现 Router 分类分发，用 @tool 实现 Skills 动态知识加载
4. 理解 Skills 与 RAG 的本质区别：Skills 是加载 prompt/指令（教 Agent 怎么思考），RAG 是加载文档片段（给 Agent 事实依据）

---

## 一、Router 模式：分类后分发

### 1.1 回顾：前三种模式各自在解决什么

- **Subagents（Day 02）**：主 Agent 在运行中逐步决定"现在该调哪个子 Agent"，可多次调用、并行派活。核心是"主 Agent 始终在场，子 Agent 是工具人"。
- **Handoffs（Day 03）**：控制权在 Agent 之间交接，用户直接和当前接管的专家对话。核心是"接力赛，交接棒"。

这两种模式都把系统拆成了多个独立 Agent。但有一类场景是这样的：用户的意图**分类很明确**——要么是路线、要么是天气、要么是装备，几乎不会模棱两可。这时候与其让主 Agent 在运行中反复决策，不如**先分类一次，然后直接交给对应专家**。这就是 Router。

### 1.2 Router 的不同：先分类，再一次性路由

Router 像公司前台分流：用户一进门，前台先问"您办什么业务"，判断完直接领到对应窗口。前台不处理业务，只做分流；分流完就退场，后续由对应专家全程接待。

和 Subagents 的关键区别：

- **Subagents**：主 Agent 运行中**动态决策**，可能这一轮调路线专家、下一轮调天气专家，始终在场反复调度
- **Router**：先分类**一次**，确定属于哪个领域，然后**一次性路由**给对应专家，Router 自己退场

换句话说：Subagents 的路由是"运行时动态、可多次"；Router 是"入口处一次、一锤定音"。

### 1.3 核心机制图解

```
                 ┌──────────┐
  用户输入 ────► │  Router  │  只做分类，不处理业务
                 │ (分流台) │
                 └────┬─────┘
                      │ 分类判断
           ┌──────────┼──────────┐
           ▼          ▼          ▼
      路线专家    天气专家    装备专家    各自独立处理
           │          │          │
           └──────────┴──────────┘
                      ▼
                   回答用户

  Router 只在入口出现一次，分类后直接交给专家，不再回来
```

### 1.4 Router vs Subagents：到底差在哪

| 维度 | Subagents | Router |
|------|-----------|--------|
| 路由决策时机 | 运行中动态决策（可多次） | 入口处分类一次（一锤定音） |
| 主控 Agent | 始终在场，反复调度 | 分类后退场，不再回来 |
| 是否需要综合 | 需要，主 Agent 收集各子 Agent 结论 | 不一定，专家独立处理即可 |
| 适合任务 | 复杂任务需多领域协作汇总 | 分类明确、各专家独立处理 |

一句话：**Subagents 是"项目经理全程跟"，Router 是"前台分流后各管各"**。

### 1.5 用 LangGraph 实现 Router

Router 的实现核心就是一个**分类节点 + 条件边**。分类节点判断意图，条件边根据判断结果路由到不同的专家 Agent。来看最小示例：

```python
"""Router 最小示例：分类后分发给对应专家"""
from typing import TypedDict, Annotated
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver


class RouterState(TypedDict):
    messages: Annotated[list, lambda x, y: x + y]


model = init_chat_model("gpt-4o-mini", temperature=0)


# 工具：每个专家只拿自己领域的
@tool
def search_routes(destination: str) -> str:
    """查询去某地的路线方案。"""
    return f"去 {destination} 的路线：成都 → 四姑娘山镇，自驾约 4 小时。"


@tool
def get_weather(location: str) -> str:
    """查询某地当前天气。"""
    return f"{location} 当前晴，气温 5-15°C，山上风大注意保暖。"


@tool
def generate_gear_list(trip_type: str) -> str:
    """根据行程类型生成装备清单。"""
    return f"{trip_type} 装备：登山鞋/冲锋衣/头灯/登山杖。"


# 三个专家 Agent（各自独立子图）
route_agent = create_agent(model=model, tools=[search_routes],
    system_prompt="你是徒步路线专家，只回答路线相关问题。")
weather_agent = create_agent(model=model, tools=[get_weather],
    system_prompt="你是天气专家，只回答天气相关问题。")
general_agent = create_agent(model=model, tools=[generate_gear_list],
    system_prompt="你是装备专家，回答装备相关问题。")


# Router 分类节点：判断用户意图（只做分类，不处理业务）
def classify_intent(state: RouterState) -> str:
    last_msg = state["messages"][-1].content
    if "路线" in last_msg or "徒步" in last_msg or "怎么走" in last_msg:
        return "route_agent"
    elif "天气" in last_msg or "气温" in last_msg:
        return "weather_agent"
    elif "装备" in last_msg or "带什么" in last_msg:
        return "general_agent"
    return "general_agent"  # 兜底


# 组装 Router 图：分类节点 + 条件边路由
builder = StateGraph(RouterState)
builder.add_node("router", lambda state: state)
builder.add_node("route_agent", route_agent)
builder.add_node("weather_agent", weather_agent)
builder.add_node("general_agent", general_agent)

builder.add_conditional_edges("router", classify_intent)
builder.add_edge(START, "router")
builder.add_edge("route_agent", END)
builder.add_edge("weather_agent", END)
builder.add_edge("general_agent", END)

app = builder.compile(checkpointer=InMemorySaver())
```

图结构就是第一节那个"入口分类 → 分发"的形状。跑起来看看效果：

```python
config = {"configurable": {"thread_id": "router-1"}}

# 路线问题 → 路由到 route_agent
result = app.invoke(
    {"messages": [{"role": "user", "content": "我想去四姑娘山徒步，怎么走？"}]}, config)
print(result["messages"][-1].content)

# 天气问题 → 路由到 weather_agent
result = app.invoke(
    {"messages": [{"role": "user", "content": "四姑娘山天气怎么样？"}]}, config)
print(result["messages"][-1].content)
```

第一句话被分类为"路线"路由给 `route_agent`，第二句被分类为"天气"路由给 `weather_agent`。Router 每次只做一次分类，然后交给对应专家，自己不再回来。

### 1.6 Router 适合什么场景

Router 的优势在于"分类明确"的场景，关键词三个：**分类明确**（意图能干净归到某一类）、**各专家独立**（处理互不依赖，不需要串行依赖）、**可并行分发**（一次提多个问题可并行分发给各专家）。

典型场景：客服分流（售前/技术/售后）、工单分发、多领域问答。反过来，如果用户意图模糊、需要多轮判断，或专家间有依赖关系，Router 不太合适——Subagents 的动态调度更灵活。

---

## 二、Skills 模式：单 Agent + 按需知识

### 2.1 换个思路：不拆 Agent，给知识就行

Router 和前三种模式一样，都是把系统拆成多个 Agent。但有时候任务没那么复杂——一个 Agent 完全能处理，只是它在某些领域"知识不够"。比如徒步规划助手查路线、查天气都能干，但回答天气时不擅长给穿衣建议，推荐路线时不擅长评估难度。

这种时候，与其拆成三个 Agent，不如保持**单 Agent**，给它加一个"技能加载"工具。遇到特定领域问题时调用 `load_skill` 加载该领域的专业 prompt，用加载的知识来回答。打个比方：Skills 不像 Subagents 那样"请外援团队"，而是"一个人干活，遇到不会的就翻对应的专业手册"。

### 2.2 核心机制图解

```
  ┌──────────────────────────────────────────┐
  │           单 Agent（始终是一个）           │
  │  tools: [get_weather, search_routes,     │
  │          load_skill]  ← "技能"是一种工具   │
  │                                          │
  │  遇到天气问题 → 调用 load_skill("weather")│
  │       │  返回天气专家的 prompt             │
  │       ▼ 用加载的知识回答用户               │
  └──────────────────────────────────────────┘

  Agent 结构没变，只是临时加载了某个领域的"专家经验"
  不拆 Agent，不加子 Agent，只注入知识
```

关键点：**Agent 保持单 Agent 结构**，没有子 Agent、没有交接、没有路由分流。只是多了一个"翻手册"的工具，遇到专业问题就翻对应手册（加载技能 prompt），翻完用知识来回答。

### 2.3 Skills vs 多 Agent：到底差在哪

| 维度 | 多 Agent（Subagents/Handoffs/Router） | Skills |
|------|--------------------------------------|--------|
| Agent 数量 | 多个，各有独立上下文 | 单个，一个上下文 |
| 知识来源 | 每个 Agent 自带 system_prompt | 运行时按需加载 |
| 上下文隔离 | 强（各 Agent 独立窗口） | 无（都在一个窗口里） |
| 控制权 | 可能流转/交接/分发 | 始终在同一个 Agent |
| 适合场景 | 领域跨度大、需隔离 | 简单聚焦、不想拆 Agent |

一句话：**多 Agent 是"拆人"，Skills 是"补脑"**。

### 2.4 实现 Skills 加载

Skills 的实现核心是两样东西：一个**技能库**（每个技能是一段专业 prompt），一个 **load_skill 工具**（Agent 调用它来加载技能）。来看代码：

```python
"""Skills 最小示例：单 Agent 按需加载专业知识"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

model = init_chat_model("gpt-4o-mini", temperature=0)

# 技能库：每个技能是一段专业 prompt（不是文档片段，是"专家经验/思考框架"）
SKILLS = {
    "weather": (
        "你是天气专家。查询天气时注意："
        "1.区分实时天气和预报 2.根据气温给穿衣建议 "
        "3.提醒高海拔安全风险 4.降水概率要标注"
    ),
    "route": (
        "你是路线专家。推荐路线时注意："
        "1.评估难度等级（入门/进阶/极限）2.考虑季节适配 "
        "3.标注补给点和下撤路线 4.注明总里程和海拔升降"
    ),
    "gear": (
        "你是装备专家。生成清单时注意："
        "1.按必备/推荐/可选分级 2.考虑重量和体积 "
        "3.标注每件装备的用途 4.根据难度和天气调整"
    ),
}


@tool
def load_skill(skill_name: str) -> str:
    """加载指定领域的专业技能知识。
    可用技能：weather（天气）、route（路线）、gear（装备）"""
    return SKILLS.get(skill_name, f"未知技能: {skill_name}")


@tool
def get_weather(location: str) -> str:
    """查询某地当前天气。"""
    return f"{location} 当前晴，气温 5-15°C，山上风大。"


@tool
def search_routes(destination: str) -> str:
    """查询去某地的路线方案。"""
    return f"去 {destination} 的路线：路线A（入门）/路线B（进阶）。"


# 单 Agent + Skills（注意：只有一个 Agent，没有子 Agent）
agent = create_agent(
    model=model,
    tools=[get_weather, search_routes, load_skill],
    system_prompt=(
        "你是徒步规划助手。遇到专业问题时，"
        "先用 load_skill 加载对应技能知识，再用加载的知识回答。"
    ),
    checkpointer=InMemorySaver(),
)
```

跑起来看看 Agent 怎么"翻手册"：

```python
config = {"configurable": {"thread_id": "skills-1"}}
result = agent.invoke(
    {"messages": [{"role": "user", "content": "四姑娘山天气怎么样，要带什么衣服？"}]}, config)
print(result["messages"][-1].content)
```

运行后 Agent 的推理过程大概是这样：

```
1. Agent 思考：这是天气问题，先加载天气技能
2. 调用 load_skill("weather") → 拿到天气专家 prompt
3. 调用 get_weather("四姑娘山") → 拿到天气数据
4. 用加载的专家思维 + 天气数据 → 给出带穿衣建议的回答
```

注意第 1 步——Agent 自己决定"先翻手册"。这就是 Skills 的精髓：**知识按需加载，不是一开始就全塞进 system_prompt**。

---

## 三、Skills vs RAG 对比

### 3.1 两者看起来很像，本质完全不同

Skills 和 RAG（Week 05 学的检索增强生成）乍一看都是"按需加载知识"，但本质完全不同：

- **Skills 加载的是"怎么思考"**：专家经验、思考框架、注意事项——prompt/指令级别
- **RAG 加载的是"事实依据"**：文档片段、数据记录——事实级别的信息

打个比方：Skills 是给 Agent 一本"天气观测方法论"（教它怎么判断降水），RAG 是给一份"今天的天气数据表"（告诉它具体多少度）。前者教方法，后者给数据。

### 3.2 对比表

| 维度 | Skills | RAG |
|------|--------|-----|
| 加载内容 | prompt/指令/专家经验 | 文档片段/事实数据 |
| 加载时机 | Agent 主动调用 load_skill | 检索系统自动匹配 |
| 用途 | 教 Agent"怎么思考" | 给 Agent"事实依据" |
| 典型内容 | "查天气要注意区分实时和预报" | "北京今天晴 22 度" |
| 结合 Week 05 | 不依赖向量库 | 就是向量库检索 |

关键区别在"谁决定"：Skills 是 Agent 自己判断需要哪个技能然后主动调用；RAG 是检索系统根据 query 算相似度自动返回。

### 3.3 Skills 和 RAG 可以组合使用

两者不互斥——实际项目里经常组合：**先 load_skill 加载专家思维框架，再用 RAG 检索事实数据**。一个管"怎么想"，一个管"有什么"。

```python
"""Skills + RAG 组合示例"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool

model = init_chat_model("gpt-4o-mini", temperature=0)

SKILLS = {
    "weather": "你是天气专家。注意区分实时和预报、给穿衣建议、提醒安全...",
    "route": "你是路线专家。注意评估难度、考虑季节、标注补给点...",
}


@tool
def load_skill(skill_name: str) -> str:
    """加载专业技能知识（教 Agent 怎么思考）"""
    return SKILLS.get(skill_name, f"未知技能: {skill_name}")


@tool
def search_knowledge(query: str) -> str:
    """检索知识库（Week 05 的向量库，给 Agent 事实依据）"""
    # 复用 Week 05 的向量检索
    # docs = vector_store.similarity_search(query)
    return f"知识库检索结果：关于 {query} 的相关文档片段..."


@tool
def get_weather(location: str) -> str:
    """查询某地当前天气。"""
    return f"{location} 当前晴，5-15°C。"


# 单 Agent 同时拥有 Skills（方法论）+ RAG（事实）+ 工具（数据）
agent = create_agent(
    model=model,
    tools=[load_skill, search_knowledge, get_weather],
    system_prompt=(
        "你是助手。遇到专业问题先 load_skill 加载专家思维，"
        "需要事实数据时 search_knowledge 检索知识库。"
    ),
)
```

运行时 Agent 的推理过程：

```
用户问："四姑娘山三条路线哪条适合新手？"
1. load_skill("route")             → 加载路线专家思维（评估难度、考虑季节...）
2. search_knowledge("四姑娘山路线")  → 检索知识库（路线A/B/C 的具体数据）
3. 用专家思维框架 + 检索到的事实 → 推荐路线A，标注难度入门
```

Skills 给了"判断框架"，RAG 给了"判断素材"，两者配合才能给出靠谱推荐。

---

## 四、四大模式综合对比与选型

### 4.1 四天的模式放一起

四大模式全部学完了，放一起做最终对比：

| 模式 | 核心机制 | 控制流 | 并行 | 上下文 | 适合场景 | 一句话记忆 |
|------|---------|--------|------|--------|---------|-----------|
| Subagents | 子Agent包装成tool | 主Agent集中控制 | 强 | 隔离 | 多领域并行汇总 | 老板派活 |
| Handoffs | 状态交接控制权 | Agent间流转 | 弱 | 共享 | 多轮对话、角色切换 | 接力交接棒 |
| Router | 入口分类一次分发 | 一次性路由 | 强 | 隔离 | 分类明确、各专家独立 | 前台分流 |
| Skills | 单Agent按需加载知识 | 始终单Agent | 无 | 单一 | 简单聚焦、补知识 | 临时请顾问 |

### 4.2 选型决策流程

遇到一个任务，怎么选模式？按这个决策流程走：

```
           任务需要多领域协作吗？
                 │
        ┌────────┴────────┐
       否                  是
        │                   │
   一个Agent够、          需要并行吗？
   只是知识不够             │
        │              ┌───┴───┐
        ▼             是       否
     Skills          │        │
   (按需补知识)    Subagents  需要多轮对话吗？
                  (并行派活)    │
                          ┌───┴───┐
                         是       否
                         │        │
                      Handoffs  Router
                     (接力交接) (分类分发)
```

读法：先判断任务复杂度——简单任务用 Skills 就够；复杂任务再判断是否需要并行，需要并行用 Subagents，不需要再判断是否多轮对话，多轮用 Handoffs，分类明确用 Router。

### 4.3 混合模式：实际项目往往不是单选

真实项目里四种模式不是互斥的，经常混合使用：

- **Router + Subagents**：入口先 Router 分类，分发到专家后，专家内部用 Subagents 并行调子 Agent。Router 做"大分流"，Subagents 做"小并行"
- **Skills + RAG**：第二节讲过的组合，Skills 给思维框架，RAG 给事实数据
- **Handoffs + Skills**：交接后的专家 Agent 内部用 Skills 加载领域知识，既保持交接连续性，又有专业思维

```python
# 混合模式示意：Router 做入口分类，每个专家内部带 Skills
route_agent = create_agent(model=model, tools=[search_routes, load_skill],
    system_prompt="你是路线专家。需要专业判断时先 load_skill。")
weather_agent = create_agent(model=model, tools=[get_weather, load_skill],
    system_prompt="你是天气专家。需要专业判断时先 load_skill。")

# Router 把它们串起来
builder = StateGraph(State)
builder.add_node("router", classify_node)
builder.add_node("route_agent", route_agent)
builder.add_node("weather_agent", weather_agent)
builder.add_conditional_edges("router", classify_intent)
```

这种"Router 分流 + 各专家内部 Skills"的架构，在 Cursor 等工具里很常见（副线笔记会展开）。

### 4.4 一张表收尾：什么时候不用多 Agent

学了四种模式，别忘了最重要的一条：**不是所有场景都需要多 Agent**。任务简单、工具少（≤5）、领域单一时，单 Agent 就够，别为了"多 Agent"而多 Agent。

| 信号 | 建议 |
|------|------|
| 工具 ≤ 5、领域单一 | 单 Agent，啥模式都不用 |
| 单 Agent 知识不够但结构简单 | Skills |
| 多领域需要并行汇总 | Subagents |
| 多轮对话、角色切换 | Handoffs |
| 分类明确、各专家独立 | Router |

---

## 动手实验

### 🟢 青铜：运行 Router 最小示例，观察分类分发过程

把第一节的 Router 代码拼成 `router_demo.py` 跑起来。输入三句话测试："怎么去四姑娘山"（路线）、"那边天气怎么样"（天气）、"要带什么装备"（装备）。在 `classify_intent` 里加 `print` 打印分类结果，亲眼看到"路由"发生。再故意输入模糊的话（"帮我看看四姑娘山"），看 Router 怎么兜底。

### 🟡 白银：完成 router_skills_demo.py — Router 分类 + Skills 加载组合

写一个 `router_skills_demo.py`，实现 Router + Skills 的混合模式：
1. Router 入口分类用户意图（路线/天气/装备）
2. 分发到对应专家 Agent
3. 每个专家内部用 `load_skill` 加载该领域的专业 prompt
4. 用加载的技能知识 + 工具数据回答用户

要求：
- 定义至少 3 个技能（weather/route/gear）
- Router 能正确分类 3 种意图
- 专家 Agent 在回答前会先调用 load_skill
- 跑通后，在输出里能看到 Agent 调用 load_skill 的痕迹

提示：参考第四节 4.3 的混合模式代码骨架，把空填满即可。

### 🔴 王者：四模式同任务对比

用同一个任务（徒步规划：查路线 + 查天气 + 生成装备清单）分别实现四种模式（Subagents/Handoffs/Router/Skills）。对比维度：代码复杂度、模型调用次数、token 消耗、能否并行、上下文是否隔离、回答质量。最终输出对比表，写 300 字结论：这个任务推荐用哪种模式？为什么？把判断沉淀成你的选型规则。

---

## 踩坑记录 🕳️

### 坑 1：Router 分类准确率依赖 prompt 质量

Router 的分类节点如果用关键词匹配（"路线""天气"），遇到稍微变个说法就分错：

```python
# 反例：纯关键词匹配，很容易漏判
def classify_intent(state):
    last_msg = state["messages"][-1].content
    if "路线" in last_msg:        # 用户说"怎么去"就漏了
        return "route_agent"
    elif "天气" in last_msg:       # 用户说"那边冷不冷"就漏了
        return "weather_agent"
    return "general_agent"
```

**症状**：用户说"四姑娘山那边冷不冷，要穿多少"，没有"天气"关键词，被分到 general_agent，答非所问。

**解决**：分类质量要求高时，别用硬编码关键词，让 LLM 来分类：

```python
# 正例：用 LLM 做分类，更鲁棒
def classify_intent(state):
    last_msg = state["messages"][-1].content
    classification = model.invoke(
        f"判断以下用户问题的类别，只回答 route/weather/gear 之一：\n{last_msg}"
    )
    intent = classification.content.strip().lower()
    return f"{intent}_agent"
```

代价是多一次模型调用，但准确率大幅提升。工程上权衡：分类错了代价大不大？大就用 LLM，不大就关键词凑合。

### 坑 2：Skills 加载的 prompt 太长会占满上下文

如果每个技能的 prompt 写得太长，加载完反而把上下文撑爆：

```python
# 反例：技能 prompt 写成了一篇论文
SKILLS = {
    "weather": "你是天气专家。以下是天气学全部知识：第一章 大气环流..."
    # 几千字，加载完上下文直接占了一半
}
```

**症状**：Agent 调了 load_skill 后，上下文暴增，后续推理变慢、甚至超窗口。

**解决**：技能 prompt 要精炼，只写"思考框架和注意事项"，控制在 200-300 字以内。需要大量知识时用 RAG 而非 Skills——Skills 管"怎么想"，RAG 管"有什么"。

### 坑 3：Skills 加载的知识和 system_prompt 冲突

```python
# 反例：system_prompt 要求简短，技能 prompt 要求详细分析，两个指令打架
agent = create_agent(model=model, tools=[load_skill],
    system_prompt="你是通用助手，对所有问题给简短回答。")  # 要求简短
# load_skill("weather") 返回："你是天气专家，回答时要详细分析..."
```

**症状**：Agent 行为不一致，有时简短有时啰嗦，因为它收到两个矛盾的指令。
**解决**：system_prompt 只写"通用职责和调度逻辑"（"遇到专业问题先 load_skill"），领域细节交给技能 prompt。让技能 prompt 在加载后"覆盖"通用行为，可以在技能 prompt 里明确说"以下指令优先于通用规则"。

### 坑 4：Router 模式不适合需要多轮上下文的场景

Router 设计是"分类一次、分发一次"。如果多轮对话需要跨领域且上下文连续，Router 力不从心——每轮重新分类，上一轮的上下文在另一个专家那里：

```
第1轮："四姑娘山怎么走"  → 分类为路线 → 路线专家回答
第2轮："那边天气怎么样"   → 重新分类为天气 → 天气专家回答（不知道上轮聊了路线）
```

这种场景天生该用 Handoffs。**Router 适合每轮独立，Handoffs 适合多轮连续。**

---

## 副线笔记

### 对比 Cursor 的 Router + Skills 架构

回头看 Cursor 这类 AI 编程工具的架构，会发现和今天学的一致：

- **Router 层**：Cursor 先分类（代码生成/修复/解释/配置），路由给对应处理流程
- **Skills 层**：按需加载领域技能（如"React 专家技能"、"Python 调试技能"），和今天的 load_skill 一模一样
- **RAG 层**：检索项目代码库的事实数据

Cursor 实际是 **Router + Skills + RAG** 三合一——Router 做入口分类，Skills 加载专家思维，RAG 检索事实数据，正是今天第四节"混合模式"的工业级实现。

### 选型直觉沉淀

四天学完，沉淀三条选型直觉：

1. **看复杂度**：任务简单、单 Agent 够用 → Skills；任务复杂、需要多 Agent 协作 → 后三种
2. **看交互**：用户要多轮连续对话 → Handoffs；一问一答式 → Subagents 或 Router
3. **看分类**：意图分类明确、各专家独立 → Router；需要动态决策派活 → Subagents

记住口诀：**Subagents 派活、Handoffs 接力、Router 分流、Skills 补脑**。

---

## 检查清单

- [ ] 理解 Router 的分类分发机制：入口分类一次，一次性路由给对应专家
- [ ] 理解 Skills 的按需知识加载：单 Agent + load_skill 工具，不拆 Agent
- [ ] 能区分 Skills 和 RAG：Skills 加载 prompt/指令（怎么想），RAG 加载文档片段（有什么）
- [ ] 完成了 router_skills_demo.py，跑通了 Router 分类 + Skills 加载的组合
- [ ] 知道四大模式各自适合什么场景，能根据任务选型
- [ ] 理解混合模式：Router + Subagents、Skills + RAG 等组合方式

---

## 下课预告

明天 **Day 05 — Deep Agents：一行创建超级 Agent**。

四大模式全部补完了，选型武器库已齐。但不管用哪种模式，都要手写 StateGraph、配条件边、组装节点……明天学 **Deep Agents**——用 `create_deep_agent` 一行创建带**文件系统 + 记忆 + 子代理**的超级 Agent。LangChain 2026 年的高层封装，文件读写、长期记忆、子 Agent 调度全打包好，不用再手搓 StateGraph。明天见。
