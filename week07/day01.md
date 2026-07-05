# Day 01 — 为什么多 Agent + 四大模式概览

## 学习目标

Week 06 你用 `create_agent` 一行创建了一个"什么都能干"的单 Agent：查天气、算距离、搜路线、生成装备清单——所有工具全塞给它，所有上下文全堆在一个 messages 列表里。它能跑，在工具不多时表现还不错。但当工具数量超过 10 个、对话轮次变多、领域跨度过大时，单 Agent 就开始"犯傻"：选错工具、忘记上文、推理混乱、只能串行干活。今天我们正式从"单 Agent"跨入"多 Agent"的世界，但多 Agent 的本质不是"多个 Agent 凑一起"，而是**上下文工程**——给每个 Agent 只看它需要的信息。本周先从认知升级开始：搞清楚单 Agent 什么时候不够、多 Agent 在解决什么、2026 年 LangChain 官方推荐的四大模式各自适合什么场景。

学完今天你能：
1. 说清楚单 Agent 的四大痛点（工具太多选错、上下文太长遗忘、领域太杂推理混乱、无法并行），并能用徒步规划场景举出具体例子
2. 理解多 Agent 的核心本质是"上下文工程"——给每个 Agent 只看它需要的信息，而不是"把多个 Agent 凑一起"
3. 掌握 2026 年 LangChain 官方四大模式：Subagents / Handoffs / Skills / Router 的核心机制和适用场景，能画出每个模式的 ASCII 结构图
4. 能根据任务需求选择合适的模式，并完成 `patterns_overview.py` 最小示例，用伪代码展示四大模式的结构差异

---

## 一、单 Agent 什么时候不够用

### 1.1 回顾 Week 06：create_agent 能干什么

Week 06 的 `create_agent` 把"模型 + 工具 + Prompt + Checkpointer"封装成一行调用，底层自动用 LangGraph 管理 ReAct 循环。你做过一个徒步出行规划 Agent，配置大概是这样：

```python
"""Week 06 回顾：一个 create_agent 塞了所有工具"""
from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver


@tool
def search_routes(region: str, days: int) -> str:
    """检索指定区域的徒步路线。region 为区域名，days 为天数。"""
    return f"找到 3 条 {region} {days} 天路线：路线A/B/C"


@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。city 为城市名。"""
    return f"{city}：晴 25°C"


@tool
def generate_gear_list(route_difficulty: str, weather: str) -> str:
    """根据路线难度和天气生成装备清单。"""
    return f"难度{route_difficulty}、天气{weather} → 装备：登山鞋/雨衣/头灯"


# 一个 Agent 扛下所有事
agent = create_agent(
    model="ollama:qwen2.5:7b",
    tools=[search_routes, get_weather, generate_gear_list],
    system_prompt="你是徒步规划助手，可以检索路线、查天气、生成装备清单。",
    checkpointer=InMemorySaver(),
)
```

工具只有 3 个时，Agent 跑得很好。但真实业务里，一个出行规划系统远不止这些——路线检索、天气查询、装备生成、行程安排、实时导航、多语言翻译、笔记记录、海拔查询、食宿预订、紧急救援……工具数量很容易冲到 10+。这时候单 Agent 开始翻车。

### 1.2 痛点一：工具选择困惑

LLM 在每次推理时都要把**所有工具的描述**塞进上下文。10 个工具的 name + description + args_schema 加起来可能占掉 2000+ token。模型要在这一大坨里选出"这次该用哪个"，错误率随工具数量上升。

```
用户问："川西天气怎么样？"
Agent 看到 10 个工具描述，选了 generate_gear_list
理由：description 里都有"天气"两个字
结果：生成了装备清单而不是查天气
```

> **实测规律：** 当工具数 ≤ 5 时，主流模型选择准确率 > 90%；工具数到 10 时掉到 70%；到 15+ 时可能低于 50%。这不是模型笨，是上下文里干扰项太多。

### 1.3 痛点二：上下文膨胀

单 Agent 只有一个 messages 列表。每次工具调用的**完整结果**都会追加进去。查个路线返回 500 字、查个天气返回 100 字、装备清单 300 字……几轮下来，上下文轻松突破 8000 token。

```python
# 单 Agent 的 messages 不断膨胀
messages = [
    {"role": "system", "content": "你是徒步规划助手...（200 token）"},
    {"role": "user", "content": "帮我规划川西3天行程"},
    {"role": "tool", "content": "路线A：详细描述...（500 token）"},  # ← 全堆进来
    {"role": "tool", "content": "川西：晴 25°C（100 token）"},
    {"role": "tool", "content": "装备清单：登山鞋/雨衣...（300 token）"},
    # 第二轮对话，上面历史还在 → user 问"装备精简一点"时
    # Agent 要读 1170+ token 才能回答，路线描述那 500 token 是纯噪声
]
```

问题在于：用户问"装备能不能精简"时，**路线描述那 500 token 是纯噪声**——跟装备无关，但 Agent 不得不带着它一起发给模型。上下文越长，模型越容易"遗忘"前面的关键信息，token 成本也越高。

### 1.4 痛点三：领域混杂

天气查询和路线检索是两个完全不同的知识域。路线检索需要理解海拔、难度、里程、季节；天气查询需要理解气象术语、降水概率、风力等级。一个 system_prompt 要同时装下两套知识域，结果是两边都讲不深。

```python
# 一个 prompt 试图同时指导两个领域，结果都浅尝辄止
system_prompt = """
你是徒步规划助手。
天气方面：注意降水、风力、温差，雨季提醒带雨具。
路线方面：注意海拔、难度系数、总里程，进阶路线提醒体能要求。
装备方面：根据难度和天气组合推荐，分基础/进阶/极端三档。
"""  # prompt 越长越杂，模型越容易"走神"——该查天气时跑去想路线的事
```

### 1.5 痛点四：无法并行

单 Agent 的 ReAct 循环是**串行**的：调模型 → 看结果 → 执行工具 → 再调模型。查天气和生成装备清单如果互不依赖，理论上可以同时做，但单 Agent 只能一个一个来。

```
单 Agent 串行执行（7 步）：
  ① 调模型 → 决定查天气        ② 执行 get_weather
  ③ 调模型 → 决定查路线        ④ 执行 search_routes
  ⑤ 调模型 → 决定生成装备      ⑥ 执行 generate_gear_list
  ⑦ 调模型 → 综合回答

多 Agent 并行执行（3 步）：
  天气专家┐
  路线专家┼→ 同时执行，各自返回结论 → 主 Agent 综合
  装备专家┘
```

### 1.6 单 Agent vs 多 Agent 的上下文对比

```
【单 Agent】所有信息堆在一个上下文里
┌───────────────────────────────────────────┐
│ system: 路线+天气+装备全装  tool_result×3  │ ← 装备专家不需要看路线结果
│ user: 装备精简一点                          │ ← 模型要读全部历史（带噪声）
└───────────────────────────────────────────┘

【多 Agent】每个 Agent 上下文隔离
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ 路线专家      │  │ 天气专家      │  │ 装备专家      │  ← 各自独立上下文（无噪声）
│ sys+tool+历史 │  │ sys+tool+历史 │  │ sys+tool+历史 │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       └────────┬───────┴────────┬────────┘
                ▼                ▼
         ┌──────────────────────┐
         │     主 Agent          │  ← 只接收"结论"，不接收推理过程
         │ sys:协调者+结论摘要   │
         └──────────────────────┘
```

关键区别：多 Agent 场景下，主 Agent 的上下文里只有"路线专家推荐了路线A/B/C""天气专家说川西晴25°C"这样的**结论摘要**，而不是每个子 Agent 内部几千 token 的完整推理过程。

---

## 二、多 Agent 的核心：上下文工程

### 2.1 多 Agent 不是"多个 Agent 凑一起"

很多人第一次接触多 Agent 会以为是"把活儿拆给多个 Agent 各干各的"。这只说对了一半。多 Agent 真正解决的问题是**上下文工程**（Context Engineering）——通过把上下文切分到独立的窗口里，让每个 Agent 只看它需要的信息。

> **核心论点：** 多 Agent 的价值不在"多"，而在"分"。分的是上下文，不是工作量。一个塞了 15 个工具的单 Agent，和一个主 Agent 协调 3 个各有 5 个工具的子 Agent，处理的总信息量差不多，但后者的每个子 Agent 上下文干净得多——只看自己的 5 个工具、自己的对话历史、自己的领域知识。

### 2.2 上下文隔离：每个 Agent 有独立窗口

多 Agent 系统里，每个子 Agent 有自己独立的：

| 组件 | 内容 | 隔离效果 |
|------|------|----------|
| system prompt | 只写自己的专长领域 | 不被其他领域的指令干扰 |
| tools | 只有自己领域的工具 | 选错工具概率大幅下降 |
| 对话历史 | 只有自己的交互记录 | 上下文不膨胀 |
| 推理过程 | 子 Agent 内部的 ReAct 循环 | 主 Agent 看不到中间步骤 |

主 Agent 的职责是**协调**：决定派给哪个子 Agent、接收子 Agent 的结论、综合后回应用户。它只接收子 Agent 的"结论"而非全部推理过程。

### 2.3 单 Agent vs 多 Agent 上下文对比

| 维度 | 单 Agent | 多 Agent（上下文隔离） |
|------|----------|----------------------|
| 上下文数量 | 1 个（所有信息堆一起） | N+1 个（每个子 Agent 独立 + 1 个主 Agent） |
| 单个上下文长度 | 随工具数和对话轮数膨胀 | 每个子 Agent 只有自己的领域信息，短而聚焦 |
| 工具选择干扰 | 10 个工具互相干扰 | 每个子 Agent 只看 3-5 个工具 |
| 历史污染 | 上轮路线结果污染本轮装备问答 | 装备专家看不到路线专家的历史 |
| 可并行性 | 串行 ReAct 循环 | 子 Agent 可并行执行 |

### 2.4 徒步规划场景：上下文怎么分

用具体例子说明。徒步规划系统拆成三个子 Agent：

```python
"""多 Agent 上下文隔离示例（伪代码，展示结构差异）"""
from langchain.agents import create_agent
from langchain.tools import tool

@tool
def search_routes(region: str, days: int) -> str:
    """检索徒步路线。region 为区域，days 为天数。"""
    return f"{region} {days}天路线：A/B/C"

@tool
def get_weather(city: str) -> str:
    """查询城市天气。city 为城市名。"""
    return f"{city}：晴 25°C"

# 子 Agent 1：路线专家，只有路线工具，system prompt 只讲路线
route_agent = create_agent(model="ollama:qwen2.5:7b", tools=[search_routes],
    system_prompt="你是路线专家，只负责检索和推荐徒步路线。")

# 子 Agent 2：天气专家，只有天气工具
weather_agent = create_agent(model="ollama:qwen2.5:7b", tools=[get_weather],
    system_prompt="你是天气专家，只负责查询天气和给出穿衣建议。")

# 主 Agent：协调者，工具不是路线/天气，而是"调用子 Agent"（子 Agent 被包装成 tool）
# 它的上下文里没有路线详情和天气数据，只有子 Agent 回传的结论
main_agent = create_agent(model="ollama:qwen2.5:7b", tools=[route_agent, weather_agent],
    system_prompt="你是徒步规划协调者，把任务派给路线专家和天气专家。")
```

路线专家的上下文里：system prompt 只讲路线 + 只有 `search_routes` 工具 + 只有路线相关对话历史。天气专家同理。主 Agent 的上下文里只有"路线专家推荐了 A/B/C""天气专家说川西晴25°C"这样的结论，看不到子 Agent 内部的推理过程。**这就是上下文工程。**

---

## 三、2026 四大模式概览

### 3.1 Subagents：主 Agent 把子 Agent 包装成 tool

**机制：** 主 Agent 把每个子 Agent 包装成一个 tool。主 Agent 调用"调用路线专家"这个 tool 时，内部启动子 Agent 跑完整 ReAct 循环，子 Agent 返回最终结论，主 Agent 拿到结论继续推理。

```
                ┌─────────────┐
                │   主 Agent   │  ← 用户只和它交互
                └──────┬──────┘
                       │ 调用 "call_route_agent" tool
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ 路线专家  │ │ 天气专家  │ │ 装备专家  │  ← 独立上下文，可并行
    └────┬─────┘ └────┬─────┘ └────┬─────┘
         └────────────┴────────────┘
                     │ 只回传"结论"
                     ▼
                ┌─────────────┐
                │   主 Agent   │  ← 综合，回应用户
                └─────────────┘
```

**特点：** 集中控制（主 Agent 决定派活）、可并行（多个子 Agent 同时跑）、用户不直接和子 Agent 交互（用户只跟主 Agent 说话）。

**适用：** 多领域任务、需要并行处理、希望集中控制。本周 Day 02 会深入这个模式。

### 3.2 Handoffs：状态驱动，Agent 间交接控制权

**机制：** Agent A 处理到某一步，通过状态触发把控制权交给 Agent B。和 Subagents 的关键区别是——控制权真的"交出去"了，接下来用户直接和 Agent B 对话，Agent A 退场。

```
  用户："我要退款"
       │
       ▼
  ┌──────────────┐
  │ 售前 Agent A  │ ── 状态触发：检测到退款意图 → handoff
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ 售后 Agent B  │  ← 接管控制权，用户现在直接跟 B 说话
  └──────────────┘

  Subagents：主 Agent 始终在场，子 Agent 是它的"手"
  Handoffs：  控制权交接，A 退场 B 上场，用户直接跟 B 对话
```

**特点：** 用户可能直接和当前 Agent 交互（控制权交接后）、有状态流转（交接时传递上下文摘要）。

**适用：** 多轮对话、角色会切换的场景（客服流转、多步骤审批）。本周 Day 03 会深入。

### 3.3 Skills：单 Agent 按需加载专门知识

**机制：** Agent 保持单 Agent 结构，不拆子 Agent。但当遇到特定领域问题时，通过工具**动态加载**该领域的 prompt 或知识。本质是"单 Agent + 动态知识注入"。

```
  ┌─────────────────────────────┐
  │        单 Agent              │
  │  tools: [search, calc,       │
  │    load_route_skill,         │  ← "技能"是一种工具
  │    load_weather_skill]       │
  └──────────┬──────────────────┘
             │ 用户问路线问题 → 调用 load_route_skill()
             ▼  返回路线领域的专门 prompt
  ┌─────────────────────────────┐
  │  Agent 有了路线领域知识       │  ← 还是同一个 Agent，只是临时加载了"技能"
  └─────────────────────────────┘
```

**特点：** 不是真的多 Agent，而是单 Agent + 动态知识。结构简单，不用拆 Agent，但上下文会随技能加载而变化。

**适用：** 任务简单但需要专业知识、不想拆 Agent 的场景。本周 Day 04 会深入。

### 3.4 Router：路由分类后分发给专门 Agent

**机制：** 先有一个 Router Agent 做分类，判断用户意图属于哪个领域，然后分发给对应的专家 Agent 处理。Router 不处理业务，只做"分流"。

```
  用户输入
     │
     ▼
  ┌──────────┐
  │  Router   │  ← 只做分类："这是路线问题"
  └────┬─────┘
       ├── 路线类 ──► 路线专家 ──► 回答用户
       ├── 天气类 ──► 天气专家 ──► 回答用户
       └── 装备类 ──► 装备专家 ──► 回答用户
```

**特点：** 分类明确、分类后可并行分发。和 Subagents 的区别：Subagents 是主 Agent 主动决定派给谁（运行时动态决策）；Router 是先分类再分发（先判断再路由）。

**适用：** 分类明确的多场景（客服分流、工单分发）。本周 Day 04 会和 Skills 一起讲。

### 3.5 四大模式对比表

| 模式 | 核心机制 | 适合场景 | 并行能力 | 用户交互程度 | 状态管理 |
|------|---------|---------|---------|------------|---------|
| **Subagents** | 子 Agent 包装成 tool，主 Agent 调用 | 多领域、需并行 | 高（多子 Agent 同时跑） | 低（只跟主 Agent 说话） | 主 Agent 集中管理 |
| **Handoffs** | 状态触发，交接控制权 | 多轮对话、角色切换 | 低（串行交接） | 高（直接跟当前 Agent 说话） | 交接时传递上下文摘要 |
| **Skills** | 单 Agent 按需加载知识 | 简单聚焦、不想拆 Agent | 中（多个技能可并行加载） | 高（始终同一个 Agent） | 单 Agent 内部，无交接 |
| **Router** | 先分类再分发 | 分类明确的多场景 | 高（分类后并行分发） | 中（Router 后转专家） | Router 分流后各自独立 |

> **一句话记忆：** Subagents 是"老板派活"，Handoffs 是"接力赛交接棒"，Skills 是"临时请顾问"，Router 是"前台分流"。

---

## 四、四大模式速选指南

### 4.1 决策树

```
你的任务需要拆成多个独立子任务吗？
├── 否 → 用 Skills（单 Agent 按需加载知识即可）
└── 是 → 子任务之间需要并行吗？
    ├── 是 → 用户会直接和某个子 Agent 对话吗？
    │   ├── 否 → Subagents（主 Agent 集中控制，子 Agent 后台跑）
    │   └── 是 → Router（先分类，再转给对应专家，用户直接对话）
    └── 否 → 是多轮对话且角色会切换吗？
        ├── 是 → Handoffs（状态驱动交接控制权）
        └── 否 → 回去用 Skills
```

### 4.2 速选规则

| 你需要… | 选这个 | 理由 |
|--------|--------|------|
| 并行处理多个独立任务 | Subagents | 主 Agent 同时派多个子 Agent，集中收口 |
| 多轮对话且角色会切换 | Handoffs | 控制权交接，用户直接和当前角色对话 |
| 任务简单但需要专业知识 | Skills | 不拆 Agent，按需加载领域知识 |
| 先分类再处理 | Router | Router 分类后分发给专家，清晰分流 |

### 4.3 副线对比：三大 AI 编程工具用的是什么模式

| 工具 | 主用模式 | 具体做法 |
|------|---------|---------|
| **Claude Code** | Subagents | 主 Agent 调用子 Agent 做代码搜索、测试运行、代码审查，用户只跟主 Agent 交互 |
| **Cursor** | Router + Skills | 先分类问题类型（代码生成/解释/修复），再加载对应技能，Composer 模式偏 Subagents |
| **Aider** | 单 Agent + Skills | 保持单 Agent 结构，按需加载 Git 操作、文件读写等知识，不拆子 Agent |

> **洞察：** 三个工具选了不同模式，没有谁对谁错——Claude Code 追求"集中控制"，Cursor 追求"分类精准"，Aider 追求"极简"。模式选择取决于产品的控制粒度需求和复杂度。

---

## 动手实验

### 🟢 青铜：观察工具过多时 Agent 选错率

用 Week 06 的 `create_agent` 给一个 Agent 配 10 个工具，然后问 5 个问题，记录每次是否选对工具。核心是观察工具数=10 时的选择准确率。

```python
"""青铜实验：工具过多时观察选错率"""
from langchain.agents import create_agent
from langchain.tools import tool

# 10 个工具，描述故意写得有些重叠，增加选错概率
@tool
def search_routes(region: str, days: int) -> str:
    """检索徒步路线。当用户要找路线时使用。"""
    return f"{region}路线：A/B/C"

@tool
def get_weather(city: str) -> str:
    """查询天气。当用户问天气时使用。"""
    return f"{city}：晴25°C"

@tool
def generate_gear(difficulty: str, weather: str) -> str:
    """生成装备清单。根据难度和天气。"""
    return "装备：登山鞋/雨衣"

@tool
def plan_schedule(start: str, end: str) -> str:
    """安排行程时间表。"""
    return f"{start}-{end}行程表"

@tool
def navigate(from_loc: str, to_loc: str) -> str:
    """导航到目的地。"""
    return f"{from_loc}→{to_loc}路线"

# 再定义 5 个工具：translate / take_note / get_altitude / book_lodging / emergency_call
# （结构相同，每个都是 @tool + 简单函数 + mock 返回，此处省略重复代码）
all_tools = [search_routes, get_weather, generate_gear, plan_schedule, navigate,
             # translate, take_note, get_altitude, book_lodging, emergency_call
             ]  # 实际实验中补齐这 5 个工具

agent = create_agent(
    model="ollama:qwen2.5:7b",
    tools=all_tools,  # 共 10 个工具
    system_prompt="你是徒步出行助手，可使用上述工具。",
)

# 测试 5 个问题，记录选对/选错
test_cases = [
    ("川西天气怎么样？", "get_weather"),
    ("帮我找川西3天路线", "search_routes"),
    ("四姑娘山海拔多少？", "get_altitude"),
    ("帮我记一下明天出发", "take_note"),
    ("把'你好'翻译成英文", "translate"),
]
# 跑完记录：选对几个？选错的选成了什么？观察工具数=10时的准确率
```

### 🟡 白银：写 patterns_overview.py

用伪代码展示四大模式的最小结构差异。不需要真正调模型，重点是**结构对比**——每个模式的"谁调谁、控制权在谁手里"长什么样。

```python
"""patterns_overview.py — 四大模式最小结构对比

用伪代码展示 Subagents / Handoffs / Skills / Router 的结构差异。
每个模式只写骨架，重点看"谁调用谁、控制权怎么流转"。
"""
from langchain.agents import create_agent
from langchain.tools import tool

# ── 模式 1：Subagents —— 主 Agent 把子 Agent 包装成 tool 调用 ──
def demo_subagents():
    """子 Agent 被包装成 tool，主 Agent 调用它拿结论。"""
    @tool
    def call_route_agent(query: str) -> str:
        """调用路线专家，返回路线推荐结论。"""
        return "路线专家推荐：川西3天路线A"  # 内部启动子Agent跑完整ReAct
    @tool
    def call_weather_agent(city: str) -> str:
        """调用天气专家，返回天气结论。"""
        return "天气专家结论：川西晴25°C"
    # 主 Agent 的工具是"调度子 Agent"，而非路线/天气本身
    main_agent = create_agent(model="ollama:qwen2.5:7b",
        tools=[call_route_agent, call_weather_agent],
        system_prompt="你是规划协调者，把路线和天气任务派给专家。")
    print("Subagents: 主Agent调用子Agent包装的tool，集中控制，可并行")

# ── 模式 2：Handoffs —— 状态驱动，交接控制权 ──
def demo_handoffs():
    """Agent A 检测到状态，把控制权交给 Agent B。"""
    @tool
    def route_to_after_sales(user_intent: str) -> str:
        """检测到退款/售后意图时，交接给售后Agent。"""
        return "已交接给售后Agent，控制权转移"  # 交接后用户直接跟售后对话
    pre_sales = create_agent(model="ollama:qwen2.5:7b", tools=[route_to_after_sales],
        system_prompt="你是售前客服，遇到退款转给售后。")
    print("Handoffs: 状态触发交接控制权，用户直接跟新Agent对话")

# ── 模式 3：Skills —— 单 Agent 按需加载专门知识 ──
def demo_skills():
    """单 Agent 通过工具加载领域知识，不拆子 Agent。"""
    @tool
    def load_route_skill() -> str:
        """加载路线规划领域知识。遇到路线问题时使用。"""
        return "路线知识：海拔/难度/里程/季节注意事项..."
    @tool
    def load_weather_skill() -> str:
        """加载气象领域知识。遇到天气问题时使用。"""
        return "气象知识：降水/风力/温差/穿衣建议..."
    single_agent = create_agent(model="ollama:qwen2.5:7b",
        tools=[load_route_skill, load_weather_skill],
        system_prompt="你是通用助手，遇到专业问题时先加载对应技能。")
    print("Skills: 单Agent按需加载领域知识，不拆子Agent")

# ── 模式 4：Router —— 先分类再分发 ──
def demo_router():
    """Router 先分类，再分发给对应专家 Agent。"""
    @tool
    def classify_intent(query: str) -> str:
        """分类用户意图，返回 route/weather/gear 之一。"""
        if "天气" in query or "下雨" in query: return "weather"
        if "装备" in query or "带什么" in query: return "gear"
        return "route"
    router = create_agent(model="ollama:qwen2.5:7b", tools=[classify_intent],
        system_prompt="你是路由器，只负责分类用户意图。")
    print("Router: 先分类意图，再分发给对应专家Agent")

if __name__ == "__main__":
    print("=" * 50 + "\n四大模式最小结构对比\n")
    demo_subagents(); demo_handoffs(); demo_skills(); demo_router()
    print("\n" + "=" * 50)
    print("结构差异总结：")
    print("  Subagents: 主Agent → call子Agent工具 → 结论回传（集中控制）")
    print("  Handoffs:  AgentA → 状态触发 → AgentB接管（控制权交接）")
    print("  Skills:    单Agent → load技能工具 → 加载知识（不拆Agent）")
    print("  Router:    Router分类 → 分发专家Agent → 回答（先分类再处理）")
```

### 🔴 王者：实测四种模式 token 消耗对比

用 mock 模型记录每次调用的 token 数，对比四种模式处理同一个问题的 token 总消耗。

```python
"""王者实验：四大模式 token 消耗对比（mock 版）"""

class MockModel:
    """记录每次调用 token 数的 mock 模型。"""
    def __init__(self):
        self.call_count = 0
        self.total_tokens = 0

    def invoke(self, messages, **kwargs):
        self.call_count += 1
        tokens = sum(len(m.get("content", "")) // 3 for m in messages)
        self.total_tokens += tokens
        return {"content": "mock回答", "tool_calls": None}

# 思考题：
# 1. "规划川西3天行程"，四种模式各调几次模型？
# 2. Subagents 并行时，token 是串行模式的几分之几？
# 3. Skills 加载技能后 prompt 膨胀，会不会比 Subagents 更费 token？
# 4. 填表对比五种模式（单Agent/Subagents/Handoffs/Skills/Router）的调用次数和总token
```

---

## 踩坑记录 🕳️

### 坑 1：多 Agent 不是银弹——协调开销可能比单 Agent 更大

拆成多 Agent 后，主 Agent 要决定"派给谁"、子 Agent 之间可能要传上下文、每次交接都有开销。如果任务很简单（比如就查个天气），单 Agent 一次搞定，多 Agent 反而要先"分类→派发→子Agent推理→回传→综合"，绕一大圈。

**解决：** 工具数 < 5、领域单一时，用单 Agent。工具数 5-10 且有明显领域划分时，考虑拆。工具数 > 10 时，拆多 Agent 收益明显。别为了"多 Agent"而多 Agent。

### 坑 2：模式混用的陷阱

四种模式不是互斥的，可以混用。但混用时容易踩坑：Router + Subagents 混用时，Router 分发后还想用主 Agent 收口，结果控制流混乱——到底谁在等谁？

**解决：** 混用时画清楚控制流图，明确"谁在调谁、控制权在谁手里"。常见安全组合：Router（分流）+ Subagents（每个分支内部用子 Agent）。不安全组合：Handoffs（交接控制权）+ Subagents（主 Agent 集中控制）——两者控制权模型冲突。

### 坑 3：工具过多时 LLM 选择准确率断崖式下降

```
工具数 3 → 95%    工具数 5 → 88%    工具数 8 → 75%
工具数 12 → 55% ← 断崖    工具数 15 → 40%
```

**解决：** 这正是多 Agent 的价值——把 15 个工具分给 3 个各持 5 个工具的子 Agent，每个子 Agent 准确率回到 88%。但注意：主 Agent 现在要选"派给哪个子 Agent"，如果子 Agent 也有 10+ 个，主 Agent 又会犯选择困难。层数别超过 2-3 层。

### 坑 4：子 Agent 回传的不是结论而是整个推理过程

子 Agent 把完整 ReAct 推理过程（几千 token）回传给主 Agent，主 Agent 上下文又膨胀了，多 Agent 的"上下文隔离"白做了。

**解决：** 子 Agent 应该只回传**最终结论**（比如"推荐路线A，难度中等，3天"），而不是中间的 tool_calls 和 tool_results。在包装子 Agent 为 tool 时，明确指定返回的是 `result["messages"][-1].content`（最终回答），而非整个 messages 列表。

---

## 副线笔记：三大 AI 编程工具的多 Agent 架构

对比 Claude Code、Cursor、Aider 三个 AI 编程工具的多 Agent 架构——它们选了完全不同的模式，正好对应今天学的四大模式。

### Claude Code：Subagents 模式

主 Agent 负责理解需求、规划任务，然后调用子 Agent 做代码搜索、代码修改、测试运行。用户始终只跟主 Agent 交互，子 Agent 在后台跑。这是典型的 Subagents——集中控制、可并行、子 Agent 不直接面对用户。

### Cursor：Router + Skills 混合

先判断用户意图（Chat / Edit / Agent / Composer），再加载对应能力。Router 在最外层分流，Composer 模式内部又用 Subagents。模式混用但控制流清晰——先分类再处理。

### Aider：单 Agent + Skills

走极简路线——保持单 Agent，按需加载知识（Git / 文件 / 代码理解）。不拆子 Agent，所有事一个 Agent 干。这是典型的 Skills 模式——单 Agent + 动态知识。

### 三者对比

| 维度 | Claude Code | Cursor | Aider |
|------|------------|--------|-------|
| 主用模式 | Subagents | Router + Skills | 单 Agent + Skills |
| 控制粒度 | 高（主 Agent 全程在场） | 中（Router 分流后各自处理） | 低（单 Agent 包揽） |
| 适合场景 | 复杂多步任务 | 多模式切换 | 简单代码修改 |

> **洞察：** 模式选择没有标准答案。Claude Code 选 Subagents 是因为它定位"复杂任务的自主完成"；Cursor 选 Router+Skills 是因为它要支持多种交互模式；Aider 选单 Agent+Skills 是因为它定位"极简命令行工具"。你选模式时也要从产品定位出发，而不是追"哪个更先进"。

---

## 检查清单

- [ ] 能说出单 Agent 的四大痛点（工具选择困惑、上下文膨胀、领域混杂、无法并行）并举例
- [ ] 理解上下文工程是多 Agent 的核心——不是"凑多个 Agent"，而是"分隔离上下文"
- [ ] 能画出四大模式的 ASCII 结构图，说出各自的核心机制
- [ ] 能区分 Subagents（集中控制）和 Handoffs（控制权交接）的关键差异
- [ ] 完成了 `patterns_overview.py`，用伪代码跑出四大模式的结构对比
- [ ] 知道什么场景选什么模式（并行→Subagents、多轮切换→Handoffs、简单专业→Skills、先分类→Router）
- [ ] 了解了 Claude Code / Cursor / Aider 分别用了什么多 Agent 模式

---

## 下课预告

> **Day 02 — Subagents：主 Agent 协调子 Agent。** 今天我们概览了四大模式，明天深入最主流的 Subagents 模式——主 Agent 把子 Agent 包装成 tool 调用。你会学到：怎么用 `create_agent` 创建子 Agent 并包装成 `@tool`、主 Agent 如何并行调度多个子 Agent、子 Agent 回传结论而非推理过程的实践、以及徒步规划场景的 Subagents 完整实现。副线对比"单 dispatch tool"模式——用一个统一的 dispatch tool 路由到不同子 Agent，和每个子 Agent 各一个 tool 的差异。
