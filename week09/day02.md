# Day 02 — Langfuse / LangSmith trace 实战

## 学习目标

Day 01 我们把评估指标体系搭起来了——成功率、平均步数、工具准确率、成本、延迟，还用 Claude Code 设计了 20 个测试任务。但指标只能告诉你"Agent 跑了 62 分"，回答不了"为什么只跑了 62 分、到底哪一步出了问题"。要回答这个问题，得把 Agent 的执行过程录下来，能回放、能放大、能下钻。这就是**可观测性（Observability）**。

Week 06 你学过 `stream_events(version="v3")`，能看 token 流、状态快照、中断事件；Week 07 Day 06 的多 Agent 调试三板斧里，trace 也露过脸，但当时只是"三板斧之一"，没单独展开。今天我们把 trace 单拎出来，系统讲透——为什么 stream_events 不够用、Langfuse 和 LangSmith 这两个 trace 平台怎么选怎么接、怎么用 trace 把 Agent 故障从"黑盒"变成"白盒"。

学完今天你能：

1. 理解可观测性的核心：从 Week 06 的 stream_events（运行时看一眼）升级到完整的 trace 体系（持久化 + 可视化 + 指标化）
2. 掌握 Langfuse（开源可自托管）和 LangSmith（LangChain 官方 SaaS）的接入方式，能说清两者的差异和选型依据
3. 能用 trace 定位 Agent 故障：看 trace 树就知道失败发生在哪一步，不用再靠 print 大法
4. 能看 trace 回答那个最关键的问题——"失败发生在 prompt、工具、检索、模型还是状态管理"

---

## 一、从 stream_events 到 trace：可观测性升级

### 1.1 stream_events 回顾：能看到，但留不下

Week 06 Day 06 我们用 `stream_events(version="v3")` 消费过 Agent 的执行流。它的 typed projections 给了几个不同粒度的视角：

| 属性 | 内容 | 粒度 |
|------|------|------|
| `.messages` | LLM 生成的逐 token 消息 | token 级 |
| `.values` | 每个节点执行后的全状态快照 | 节点级 |
| `.interrupts` | 中断信息列表 | 中断级 |
| `.output` | 图的最终输出 | 图级 |

当时我们用它能做的事：前端打字机效果、看节点状态更新、捕获 interrupt。在 Week 07 Day 06 的调试三板斧里，stream_events 是"第二板斧"——先看 trace 定位层级，再用 stream_events 细看那一层的推理。

但你有没有发现一个问题？stream_events 是"直播"——你必须盯着它实时看，一旦运行结束，这些事件就随风而逝了。你想复盘 10 分钟前那次失败的调用？没有了。你想对比昨天和今天两次跑的结果？没有存档。多 Agent 场景下，事件量还大得惊人，你得在滚滚洪流里捞那几条关键的 `on_tool_end`。

### 1.2 stream_events 的三个局限

把 stream_events 放到生产场景，它的短板马上暴露：

```
stream_events 的三大局限
┌──────────────────────────────────────────────────────┐
│  ① 易失性：运行结束数据就没了，不能回放、不能复盘     │
│  ② 无界面：纯文本输出，没有可视化，调用链全靠脑补     │
│  ③ 无指标：token/cost/latency 要自己算，不自动统计     │
└──────────────────────────────────────────────────────┘
```

展开说：

**局限一：只在运行时看，结束后数据没了。** stream_events 是个迭代器，你 `for snapshot in stream` 消费完就没了。生产环境一次调用跑挂了，你想事后查"那一刻 LLM 收到的 prompt 是什么""工具返回了什么"，对不起，已经丢了。除非你手动把每条事件都写日志——那不就等于自己造一个 trace 系统吗？

**局限二：没有可视化界面。** 多 Agent 调试时，主 Agent → 子 Agent → 工具 → 子工具的嵌套调用链，纯文本打出来是这样的：

```
on_tool_start: route_expert
  on_chat_model_stream: ...
  on_tool_start: search_routes
    on_tool_end: [...]
  on_chat_model_stream: ...
on_tool_end: ...
```

你得在脑子里把这坨缩进还原成调用树。Week 07 Day 06 我们就说过，多 Agent 调试的难点是"链路太长、症状和根因隔得远"。纯文本日志让这个难点雪上加霜。

**局限三：多 Agent 场景事件量爆炸。** 一个有 3 个子 Agent 的系统，跑一次能产生几百条事件。你在里面捞"哪步出错了"，像大海捞针。Week 07 踩坑记录里也提过这条——stream_events 输出量爆炸，得靠过滤只盯 `on_tool_start` / `on_tool_end` / `on_chat_model_stream` 三类。

### 1.3 Trace 的升级：持久化 + 可视化 + 指标化

Trace 要解决的，正是 stream_events 的三个短板。一个完整的 trace 体系给你三样东西：

| 能力 | 说明 | 对应 stream_events 的局限 |
|------|------|--------------------------|
| **持久化** | 每次调用都存档，可随时回放、对比、检索 | 解决"易失性" |
| **可视化** | Web UI 展示完整调用链，树状结构一目了然 | 解决"无界面" |
| **指标化** | 自动统计 token / cost / latency，无需手算 | 解决"无指标" |

```
运行时                        运行后
┌─────────────┐              ┌─────────────────────────────┐
│ stream_events│   ──存档──►  │   Trace 平台（Web UI）       │
│  (直播)      │              │                              │
└─────────────┘              │  ┌────────────────────┐     │
                             │  │ 调用链树状图        │     │
                             │  │ 每步耗时/token/cost│     │
                             │  │ prompt & completion│     │
                             │  │ 错误高亮          │     │
                             │  └────────────────────┘     │
                             │   可回放 / 可检索 / 可对比   │
                             └─────────────────────────────┘
```

> **一句话区分：** stream_events 是"看直播"，trace 是"看回放 + 数据面板"。直播当然有用（前端打字机、实时调试），但生产环境的故障复盘、性能优化、回归测试，靠的是回放和指标。这就是为什么 Week 09 把 trace 单拎一天——评估指标（Day 01）告诉你"几分"，trace（今天）告诉你"为什么几分"。

### 1.4 stream_events vs trace 对比

把两者的差异拉个总表，这是今天最重要的认知之一：

| 维度 | stream_events | Langfuse / LangSmith trace |
|------|---------------|---------------------------|
| 数据留存 | 运行结束即丢失 | 持久化存储，可回放 |
| 界面 | 纯文本 / 终端 | Web UI，树状调用链 |
| 接入成本 | 零（LangGraph 原生） | 配置环境变量或装饰器 |
| 指标统计 | 手动计算 | 自动统计 token/cost/latency |
| 多 Agent 表现 | 事件爆炸，靠脑补树 | 自动嵌套成树，清晰 |
| 实时性 | 实时（适合打字机） | 事后查看（非实时） |
| 成本 | 免费 | LangSmith 有额度限制 / Langfuse 自托管 |
| 典型场景 | 前端流式、实时调试 | 故障复盘、性能分析、回归测试 |

注意最后一行——这不是"trace 取代 stream_events"，而是**两者互补**。stream_events 管实时（前端打字机、线上调试），trace 管事后（故障复盘、性能优化）。生产 Agent 两个都要：stream_events 给用户看流式输出，trace 给你看后台发生了什么。

---

## 二、Langfuse 实战（开源首选）

### 2.1 Langfuse 是什么

Langfuse 是一个开源的 LLM 可观测性平台，最大的特点是**可以自托管**——你把它部署在自己的服务器上，所有 trace 数据不出你的机房。这一点对隐私敏感场景（医疗、金融、企业内网）至关重要。我们 Week 07 Day 07 做过护理系统的多 Agent，那种场景的 trace 数据涉及患者隐私，自托管几乎是硬需求。

Langfuse 有云版和自托管版两种部署方式：

| 部署方式 | 说明 | 适合 |
|----------|------|------|
| Langfuse Cloud | 官方托管的 SaaS | 个人学习、快速上手 |
| 自托管 | Docker 部署到自己服务器 | 隐私敏感、企业内网 |

### 2.2 核心概念：Trace / Span / Generation / Event

Langfuse 的数据模型有四个核心概念，理解它们你就理解了 trace 长什么样：

| 概念 | 说明 | 类比 |
|------|------|------|
| **Trace** | 一次完整的 Agent 调用（从入口到返回） | 一次 HTTP 请求 |
| **Span** | Trace 内的一步操作（LLM 调用、工具调用、子函数） | 一次函数调用 |
| **Generation** | 一种特殊的 Span，专指 LLM 生成（记录 prompt/completion/usage） | 一次 LLM API 调用 |
| **Event** | 自定义事件（日志点，无时长） | 一行 console.log |

```
一次 Trace 的结构（川西徒步规划）
Trace: run_agent("川西3天徒步路线推荐")          ← 根 trace
│
├── Span: agent.invoke                          ← Agent 主循环
│   │
│   ├── Generation: LLM 第一轮思考               ← LLM 调用
│   │   prompt: system + user query
│   │   completion: "我需要先查路线"
│   │   usage: {input: 120, output: 15}
│   │
│   ├── Span: tool_call(search_routes)          ← 工具调用
│   │   └── Event: "查询数据库..."               ← 自定义事件
│   │
│   ├── Generation: LLM 第二轮思考
│   │
│   └── Generation: LLM 最终回复
│
└── End: 返回 "推荐长穿毕3日..."
```

> **前端类比：** Trace 就像一次完整的页面加载，Span 是其中的每个网络请求和组件渲染，Generation 是其中的关键 API 调用，Event 是你埋的 console.log。Langfuse 的 Web UI 把这棵树画出来，你能像看浏览器 DevTools 的 Network 面板一样看 Agent 的执行。

### 2.3 接入方式：装饰器自动埋点

Langfuse 提供了 `@observe()` 装饰器，给任何函数套上就自动生成 trace 和 span。这是它和 LangSmith 最大的接入差异——Langfuse 要你显式装饰，LangSmith 靠环境变量自动接管。

```python
"""trace_demo.py — Langfuse trace 接入

演示内容：
1. 用 Langfuse 装饰器给 Agent 加 trace
2. 在 trace 中记录每一步操作
3. 在 Langfuse Web UI 查看调用链
4. 用 trace 定位故障
"""
from langfuse import Langfuse
from langfuse.decorators import observe
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

# 初始化 Langfuse（读取环境变量 LANGFUSE_SECRET_KEY 等）
langfuse = Langfuse()


# 先定义两个工具（Week 06 的 @tool）
from langchain.tools import tool

@tool
def search_routes(region: str, days: int) -> str:
    """搜索徒步路线。region 为区域，days 为天数。"""
    return f"{region} {days}天路线：长穿毕3日 / 四姑娘山二峰3日"

@tool
def get_weather(region: str) -> str:
    """查询区域天气。"""
    return f"{region}未来3天：晴 / 多云 / 小雨"


@observe()  # 这个装饰器自动给函数加 trace，函数变成一个 Span
def run_agent(query: str) -> str:
    """运行 Agent，Langfuse 自动记录 trace"""
    agent = create_agent(
        model=init_chat_model("gpt-4o-mini"),
        tools=[search_routes, get_weather],
        system_prompt="你是徒步规划助手，根据用户需求推荐路线并提示天气",
    )
    result = agent.invoke({"messages": [{"role": "user", "content": query}]})
    return result["messages"][-1].content


# 运行后去 Langfuse Web UI 看 trace
result = run_agent("川西3天徒步路线推荐")
print(result)
```

`@observe()` 的机制：每次 `run_agent` 被调用，Langfuse 就创建一个 Span，记录函数的输入、输出、耗时。函数内部如果有别的 `@observe()` 装饰的函数，会自动嵌套成子 Span。配合 Langfuse 的 LangChain 集成（`CallbackHandler`），Agent 内部的 LLM 调用、工具调用也会被自动捕获成 Generation 和 Span。

### 2.4 Langfuse Web UI 能看到什么

运行完上面的代码，打开 Langfuse Web UI，你能看到：

```
Langfuse Web UI 的 trace 视图
┌──────────────────────────────────────────────────────────┐
│ Trace: run_agent("川西3天徒步路线推荐")   总耗时 3.2s      │
│ 总 token: 480   总 cost: $0.002                            │
├──────────────────────────────────────────────────────────┤
│ ┌─ Span: run_agent                       3.2s            │
│ │  ┌─ Generation: LLM 第一轮             1.1s  120 tok   │
│ │  │  prompt: [system, user]                          │
│ │  │  completion: "我需要先查路线..."                  │
│ │  ├─ Span: search_routes                0.3s          │
│ │  ├─ Generation: LLM 第二轮             1.2s  180 tok │
│ │  └─ Generation: LLM 最终回复           0.6s  180 tok │
│ │     completion: "推荐长穿毕3日，注意..."            │
│ └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

具体能看到的东西：

- **完整调用链**：Agent → LLM → Tool → LLM → 回复，嵌套树一目了然
- **每步的耗时、token、cost**：哪一步慢、哪一步烧钱，一眼看出
- **prompt 和 completion 的完整内容**：LLM 到底收到了什么、生成了什么
- **错误和异常**：哪一步抛了异常，红色高亮
- **标签和元数据**：可以给 trace 打标签（如 `version=v1`、`env=prod`）方便筛选

对比 Week 07 Day 06 的纯文本 stream_events 调试，这套可视化强太多了。当时你得在脑子里把缩进还原成树，现在树直接画给你看。

---

## 三、LangSmith 实战（LangChain 官方）

### 3.1 LangSmith 是什么

LangSmith 是 LangChain 官方的 trace 平台，和 LangGraph 是一家人。它的最大优势是**接入零成本**——因为是同一家做的，只要设几个环境变量，所有 `create_agent` 的 `invoke` 都自动被 trace，不用改一行业务代码。

代价是：LangSmith 是 SaaS，不开源，免费额度有限（每月 5000 traces）。对于学习阶段够用，但生产环境高频调用会很快撑爆额度。

### 3.2 Langfuse vs LangSmith 对比

把两者的差异拉个总表，这是选型的核心依据：

| 维度 | Langfuse | LangSmith |
|------|----------|----------|
| 开源 | 是（MIT 协议，可自托管） | 否（SaaS） |
| 免费额度 | 自托管无限 / 云版有额度 | 每月 5000 traces |
| LangChain 集成 | 装饰器 / CallbackHandler | 原生（环境变量自动接入） |
| 接入成本 | 需要装饰或配 handler | 设环境变量即可，零改码 |
| UI | 独立 Web | 独立 Web |
| 数据隐私 | 自托管数据不出机房 | 数据上 LangChain 服务器 |
| 适合场景 | 自托管、隐私敏感、企业内网 | 快速接入、LangChain 重度用户 |
| 评估能力 | 内置 eval + 可接 RAGAS（Day 03） | 内置 eval + Dataset |

**怎么选？** 一句话：学习阶段用 LangSmith（接入快，零配置）；要上线或涉及隐私，用 Langfuse 自托管。今天两个都接一遍，感受差异。

### 3.3 LangSmith 接入：环境变量自动接管

LangSmith 的接入简单到令人发笑——三行环境变量，之后所有 LangGraph 的调用都自动被 trace：

```python
"""langsmith_demo.py — LangSmith trace 接入

对比 Langfuse：完全不用改业务代码，只设环境变量。
"""
import os

# 三个环境变量搞定
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_API_KEY"] = "your-key"
os.environ["LANGSMITH_PROJECT"] = "week09-trace-demo"

# 之后所有 create_agent 的 invoke 都自动被 trace
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

agent = create_agent(
    model=init_chat_model("gpt-4o-mini"),
    tools=[search_routes, get_weather],
    system_prompt="你是徒步规划助手",
)

# 这次 invoke 会被自动 trace，去 LangSmith Web UI 看
result = agent.invoke({"messages": [{"role": "user", "content": "川西3天徒步路线"}]})
```

注意对比：Langfuse 要你给 `run_agent` 套 `@observe()`，业务代码有改动；LangSmith 一个环境变量，业务代码一行不动。这就是"原生集成"的力量——LangGraph 内部知道 LangSmith 的存在，调用时自动上报。

> **前端类比：** Langfuse 像 Sentry，要你手动 `Sentry.init()` 并在关键函数埋点；LangSmith 像 Next.js 自带的 telemetry，框架内置，配个开关就开跑。

### 3.4 LangSmith 的 trace 视图

LangSmith 的 Web UI 长得和 Langfuse 类似，也是树状调用链。但因为它和 LangGraph 深度集成，对 LangGraph 特有概念的展示更细：

```
LangSmith trace 视图（LangGraph 感知）
┌──────────────────────────────────────────────────────────┐
│ Project: week09-trace-demo                                │
├──────────────────────────────────────────────────────────┤
│ Run: agent.invoke                          3.2s          │
│ └─ LangGraph 节点: agent                    3.2s         │
│    ├─ ChatModel: gpt-4o-mini                1.1s  120 tok│
│    │  tools_called: [search_routes]                      │
│    ├─ Tool: search_routes                   0.3s         │
│    ├─ ChatModel: gpt-4o-mini                1.2s  180 tok│
│    └─ ChatModel: gpt-4o-mini                0.6s  180 tok│
└──────────────────────────────────────────────────────────┘
```

LangSmith 会把 LangGraph 的节点（agent、tools）、每轮 LLM 调用、工具调用都分别展示，还能看到状态（State）在节点间的流转。对于 Week 07 的多 Agent 系统，主 Agent 调子 Agent 的嵌套也会清晰呈现。

---

## 四、用 trace 定位故障

### 4.1 故障定位的五步法

trace 最大的价值不是"看 Agent 跑得有多漂亮"，而是"Agent 挂了的时候，告诉你挂在哪"。给你一套五步法，照着走能定位绝大多数故障：

```
故障定位五步法
┌──────────────────────────────────────────────────────┐
│  1. 看 trace 树：哪一步失败了（红色标记）             │
│     → 定位"症状在哪一层"                             │
│                                                      │
│  2. 看 prompt：LLM 收到的输入对不对                   │
│     → 检查 system + user + history 有没有问题        │
│                                                      │
│  3. 看 tool_call：Agent 选对工具了吗                  │
│     → 检查 LLM 决定调哪个工具、参数对不对             │
│                                                      │
│  4. 看 tool result：工具返回了什么                    │
│     → 检查工具的输出是不是预期的                      │
│                                                      │
│  5. 看 completion：LLM 最终生成了什么                 │
│     → 检查最终回复，对照预期                          │
└──────────────────────────────────────────────────────┘
```

这五步对应 Week 07 Day 06 三板斧的"从粗到细下钻"思路，但更聚焦于 trace 本身。Week 07 的三板斧是"trace 定位层级 → stream_events 看推理 → 上下文检查找根因"，今天我们用 trace 一步到位——因为 trace 里已经有 prompt、tool_call、tool result、completion 的完整内容，不用再开 stream_events。

### 4.2 五类故障的 trace 特征

不同根因的故障，在 trace 上的"长相"不一样。记住下面这张表，看 trace 就能初步判断故障类型：

| 故障类型 | trace 上的特征 | 定位方法 |
|----------|----------------|----------|
| **prompt 问题** | LLM 收到的输入有错别字/缺上下文/注入 | 看 Generation 的 prompt 字段 |
| **工具选错** | tool_call 选了不该选的工具 | 看 LLM 的 tool_calls 决策 |
| **工具返回错** | tool result 内容错误/为空 | 看 Span 的输出 |
| **检索失败** | RAG 检索的 chunk 不相关 | 看检索 Span 的输入输出 |
| **模型能力不足** | completion 质量差但输入都对 | 看 Generation 的 completion |
| **状态管理错** | messages 历史异常累积/丢失 | 看各 Span 间的 state 流转 |

这就是学习目标第 4 条——"能用 trace 回答失败发生在 prompt、工具、检索、模型还是状态管理"。

### 4.3 实战案例：用 trace 定位 Week 07 多 Agent 故障

我们拿 Week 07 Day 06 调试过的那个故障来实战。复盘一下当时的情况：

**故障现象：** 主 Agent 收到"去川西徒步要带什么装备"，却把它派给了路线专家（而不是装备专家），最终给的回答是路线推荐，没回答装备问题。

**Week 07 的定位方式（三板斧）：** trace 看整体链路定位到"主 Agent 选错子 Agent"这一层 → stream_events 看主 Agent 的推理 → 上下文检查看 tool 的 docstring → 发现 docstring 写得不清。

**今天用 trace 一步到位：**

```
Trace 树（故障复现）
run_agent("去川西徒步要带什么装备")
└─ Span: agent.invoke
   ├─ Generation: LLM 第一轮思考
   │  prompt: [system, user="去川西徒步要带什么装备"]
   │  completion: "我需要调用工具"
   │  tool_calls: [route_expert(...)]   ← 🔴 这里就看出选错了！
   │
   ├─ Span: route_expert("川西")        ← 选了路线专家
   │  └─ 返回 "推荐长穿毕3日..."
   │
   └─ Generation: LLM 最终回复
      completion: "推荐你走长穿毕3日..."  ← 没回答装备问题
```

看 trace 树，第一步的 `tool_calls` 字段就露馅了——`route_expert` 被选中，而问题明明问的是"装备"。定位到这一层，下一步直接看 `route_expert` 和 `gear_expert` 两个 tool 的描述（docstring），对比 Week 07 Day 06 的上下文检查，发现 `route_expert` 的 docstring 里写了"川西"相关字样，把主 Agent 误导了。

**根因：** 子 Agent 的 tool description 写得不够清晰，主 Agent 的 LLM 看到用户提"川西"就匹配到了 `route_expert`。

**修复：** 改 `gear_expert` 的 docstring，明确"装备问题"这个意图：

```python
# 修复前：docstring 太模糊
@tool
def gear_expert(query: str) -> str:
    """徒步装备相关。"""   # ← 主 Agent 不知道什么时候该用它
    ...

# 修复后：docstring 明确意图和触发条件
@tool
def gear_expert(query: str) -> str:
    """回答徒步装备问题，如"带什么装备""穿什么""需要什么装备"。
    当用户询问装备、衣物、背包、睡袋等具体物品时调用此工具。"""
    ...
```

修完再跑一次，看 trace 树，这次 `tool_calls` 变成了 `gear_expert`，故障排除。

> **和 Week 07 的对比：** Week 07 三板斧要切换三个工具（trace → stream_events → 上下文检查），今天用 trace 平台一个界面就看完——prompt、tool_calls、tool result、completion 全在 trace 里。这就是 trace 平台相比手动 stream_events 的效率提升：从"三个工具接力"变成"一个界面下钻"。

### 4.4 副线呼应：多 Agent 协作链路可视化

承接 Week 07 的多 Agent，Langfuse trace 对多 Agent 系统的可视化特别有价值。主 Agent → 子 Agent 的嵌套调用链，在 trace 里长这样：

```
多 Agent 的 trace 树（嵌套）
run_agent("规划川西3天徒步")
└─ Span: 主 Agent
   ├─ Generation: 主 Agent 思考 → 调 route_expert
   ├─ Span: route_expert (子 Agent，作为 tool)
   │  ├─ Generation: 子 Agent 思考 → 调 search_routes
   │  ├─ Span: search_routes (工具)
   │  └─ Generation: 子 Agent 总结 → "推荐长穿毕3日"
   ├─ Generation: 主 Agent 思考 → 调 weather_expert
   ├─ Span: weather_expert (子 Agent)
   │  └─ ...
   └─ Generation: 主 Agent 最终回复
```

这棵树像调用栈一样，主 Agent 是根，子 Agent 是枝，工具是叶。对比 Week 07 Day 06 我们手动用 stream_events 追踪这条链路，trace 的可视化效果强得多——不用在脑子里还原缩进，树直接画给你看。这也是 Day 01-07 副线设计里写的"用 trace 分析 Week 07 多 Agent 的协作链路"的落地点。

---

## 动手实验

### 🟢 青铜：注册 LangSmith，看 Week 06 Agent 的 trace

1. 注册 LangSmith 免费账号（smith.langchain.com）
2. 拿到 API Key，配三个环境变量（`LANGSMITH_TRACING`、`LANGSMITH_API_KEY`、`LANGSMITH_PROJECT`）
3. 把 Week 06 的 `create_agent` 代码搬过来跑一次（比如 `day06.py` 的徒步规划 Agent）
4. 打开 LangSmith Web UI，找到这次调用的 trace
5. 在 trace 里找到：调用链树、每次 LLM 调用的 prompt/completion、token 统计

目标：第一次见到 trace 长什么样，理解"持久化 + 可视化"比 stream_events 强在哪。

### 🟡 白银：完成 trace_demo.py，定位一个故障

1. 完成 `trace_demo.py`，用 Langfuse（云版或自托管）给 Week 07 的多 Agent 系统加 trace
2. 故意制造一个故障：把 `gear_expert` 的 docstring 改模糊，让主 Agent 选错子 Agent
3. 用 trace 定位这个故障：看 trace 树找到选错的 `tool_call`
4. 修复 docstring，重跑验证 trace 里 `tool_call` 变对了
5. 截图对比修复前后的 trace 树

目标：完整走一遍"故障定位五步法"，亲手用 trace 把一个故障从发现到修复。

### 🔴 王者：对比 Langfuse 和 LangSmith 的 trace 展示

1. 把同一个 Agent（比如 Week 07 的多 Agent）分别接入 Langfuse 和 LangSmith
2. 跑同一个 query，对比两个平台的 trace 展示：
   - 调用链树的展示方式有什么不同
   - prompt/completion 的呈现哪个更清晰
   - token/cost/latency 的统计粒度差异
   - 错误高亮和筛选功能
3. 写一份对比笔记：哪个平台更适合你的场景，为什么

目标：建立对两个平台的选型判断力，能根据场景（隐私 / 成本 / 集成度）给出选型理由。

---

## 踩坑记录 🕳️

### 坑 1：Langfuse 自托管需要 Docker 部署

Langfuse 云版开箱即用，但自托管要 Docker Compose 部署，涉及 Postgres、ClickHouse 等多个服务，对没碰过 Docker 的人有门槛。

**解决：** 学习阶段直接用 Langfuse Cloud（免费额度够），等真要上线或涉及隐私再折腾自托管。自托管时按官方 docker-compose.yml 一键拉起，注意端口冲突和持久化卷配置。

### 坑 2：LangSmith 免费额度有限（5000 traces/月）

调试时反复跑，5000 条很快用完。一旦超额，新 trace 不再上报，你以为接好了其实没数据。

**解决：** 调试时控制跑的次数；不同实验用不同 project 隔离（`LANGSMITH_PROJECT` 分开）；生产环境考虑升级或换 Langfuse 自托管。可以在 LangSmith 设置里给 project 配采样率，只上报一部分 trace。

### 坑 3：trace 数据量很大，长会话生成大量 span

一个有 5 轮工具调用的 Agent 会话，能产生几十个 span 和 generation。长会话（几十轮对话）的 trace 树深到看不过来，Web UI 加载都卡。

**解决：** 学会过滤——按 span 类型、按状态（成功/失败）、按耗时筛选。Langfuse 和 LangSmith 都支持按 tag/metadata 筛选，给 trace 打标签（如 `version=v1`、`bug=tool_select`）方便定位。调试时聚焦看失败的那一次，别每次都翻全部。

### 坑 4：多 Agent 场景 trace 树太深

主 Agent → 子 Agent → 子 Agent 的工具 → ... 嵌套三四层，trace 树深到要滚好几屏。Week 07 的多 Agent 尤其明显。

**解决：** 学会用 trace 平台的"折叠"功能——把成功的子树折叠掉，只展开有问题的分支。另外给 trace 起个好认的名字（`@observe(name="主Agent-川西规划")`），别让它显示成一串哈希。

### 坑 5：Langfuse 装饰器和 LangChain 集成要配合

光给 `run_agent` 套 `@observe()` 只能记录函数的输入输出，Agent 内部的 LLM 调用、工具调用不会被自动捕获。要让 trace 完整，还得把 Langfuse 的 `CallbackHandler` 传给 Agent。

**解决：** 用 Langfuse 的 LangChain 集成（`langfuse.callbacklangchain.CallbackHandler`），传给 `create_agent` 的 config，或者用全局的 `@observe()` 自动注入。否则 trace 里只有一个空 Span，看不到 Agent 内部细节。

---

## 副线笔记

### 用 trace 分析 Week 07 多 Agent 的协作链路

把 Week 07 Day 02-05 的几种多 Agent 模式都跑一遍 trace，对比它们的链路形状：

```
Subagents 模式：主 Agent 调子 Agent（嵌套深）
run_agent
└─ 主 Agent
   ├─ Span: route_expert (子 Agent)
   │  └─ 内部 LLM + 工具
   └─ Span: weather_expert (子 Agent)

Handoffs 模式：控制权流转（链式，非嵌套）
run_agent
├─ Span: agent_A → handoff
└─ Span: agent_B → handoff
   └─ Span: agent_C

Router 模式：分类后分发（扇出）
run_agent
└─ Router 节点
   ├─ Span: route_expert
   └─ Span: gear_expert
```

不同模式的 trace 树形状不一样，反过来——看 trace 树的形状也能反推 Agent 用的是哪种协作模式。这是个有意思的练习：先盲跑，看 trace 树猜模式，再对照代码验证。

对比 Week 07 Day 06 的手动 stream_events 追踪，trace 平台的可视化效果强得多。当时我们得在终端里盯着缩进脑补调用树，现在树直接画给你看，还能点开任意节点看 prompt/completion 的完整内容。这就是"工具升级"带来的效率跃迁——Week 07 你用三板斧能定位的故障，今天用 trace 一个界面就能定位。

### Day 01 评估指标的"为什么"

Day 01 的指标体系告诉你"Agent 跑了 62 分"，但回答不了"为什么 62 分"。今天的 trace 是 Day 01 指标的"下钻工具"——指标告诉你结果，trace 告诉你原因。比如 Day 01 算出"工具准确率 70%"，今天用 trace 能看到那 30% 错的调用具体是哪几次、每次错在哪（选错工具 / 参数错 / 工具返回错）。指标和 trace 配合，才是完整的可观测性闭环。

---

## 检查清单

- [ ] 理解 trace 和 stream_events 的区别（持久化 / 可视化 / 指标化）
- [ ] 接入了 Langfuse 或 LangSmith 至少一个
- [ ] 在 Web UI 看到了完整调用链（树状结构）
- [ ] 能在 trace 里找到 prompt / tool_call / tool result / completion
- [ ] 用 trace 定位了一个故障（走完五步法）
- [ ] 能根据 trace 特征判断故障类型（prompt / 工具 / 检索 / 模型 / 状态）
- [ ] 知道 Langfuse 和 LangSmith 的选型依据（开源 / 额度 / 集成度）

---

## 下课预告

> **Day 03 — RAGAS + Promptfoo：专门评估 RAG 系统质量的工具。** 今天我们用 trace 看 Agent 内部发生了什么，明天换一个视角——专门评估 RAG（检索增强生成）的质量。Week 04 你搭过 RAG 系统，当时靠人工看"检索得准不准""生成得对不对"。明天我们用 RAGAS 把这件事量化：faithfulness（忠实度）、answer_relevancy（答案相关性）、context_precision（检索精确率）。再用 Promptfoo 做提示词的批量回归测试。产出 `rag_eval.py`，量化对比 Week 04 RAG 的检索质量。
