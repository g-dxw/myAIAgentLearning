# Day 06 — Context Engineering + 调试多 Agent

## 学习目标

Day 01 我们抛过一个论点：多 Agent 的本质不是"把多个 Agent 凑一起"，而是**上下文工程**——给每个 Agent 只看它需要的信息。过去五天我们一直在"搭骨架"：Day 02 Subagents 把子 Agent 包装成 tool，Day 03 Handoffs 让控制权在 Agent 间流转，Day 04 Router 分类后分发、Skills 按需加载知识，Day 05 Deep Agents 一行创建带文件系统的超级 Agent。骨架搭完了，但有个问题一直被我们一笔带过——每个 Agent 到底该看到什么信息？给多了上下文膨胀，给少了信息丢失；共享了会串味，隔离了又断片。今天我们把这层"窗户纸"捅破，正面聊 **Context Engineering（上下文工程）**，并解决多 Agent 系统最头疼的问题：**调试**。

多 Agent 跑起来容易，跑对难。单 Agent 出问题你盯着一个 stream_events 看就行；多 Agent 出问题，你得在主 Agent、子 Agent、状态传递、工具调用这一长串链路里定位"到底是哪个环节挂了"。今天给你一套"调试三板斧"，把多 Agent 的黑盒拆开。

学完今天你能：
1. 理解 Context Engineering（上下文工程）是多 Agent 系统设计的核心：决定每个 Agent 看到什么信息
2. 掌握上下文隔离、上下文压缩、上下文共享三种策略及适用场景
3. 能用 LangSmith trace 和 stream_events 调试多 Agent 协作流程，定位"哪个 Agent 出了问题"
4. 掌握多 Agent 调试三板斧：trace 追踪、上下文检查、工具调用日志

---

## 一、Context Engineering：多 Agent 的核心设计

### 1.1 回到 Day 01 的那句话

Day 01 我们讲过一个核心论断：**多 Agent 的价值不在"多"，而在"分"。分的是上下文，不是工作量。** 这五天我们搭了各种模式，但每次落地时，真正决定系统好坏的不是"用了哪种模式"，而是一个更底层的问题——每个 Agent 的上下文里该放什么？

这个问题在单 Agent 时代根本不存在：所有信息堆在一个 messages 里，给就给了。但多 Agent 系统里，信息有了"去哪个 Agent"的选择空间，于是"给谁、给多少、怎么给"就成了一门需要设计的工程。这就是 Context Engineering。

> **一句话定义：** 上下文工程 = 对每个 Agent 看到的信息做有意识的设计。不是把所有 messages 一股脑塞进去，而是主动决定"这条信息该不该被这个 Agent 看到"。

### 1.2 上下文工程的三层决策

把"每个 Agent 看到什么"拆开，其实是三层决策。这三层决策贯穿了 Day 02-05 的所有模式：

| 层级 | 决策 | 典型示例 |
|------|------|----------|
| 分配 | 哪些信息给哪个 Agent | 路线专家只看路线工具，不看天气 API |
| 压缩 | 给多少信息 | 子 Agent 只返回结论，不返回推理过程 |
| 传递 | 信息怎么共享 | Handoffs 共享 messages，Subagents 只传结论 |

Subagents 的上下文隔离是"分配 + 压缩"的体现——主 Agent 只拿结论；Handoffs 的共享 messages 是"传递"的体现——所有 Agent 看同一份对话；Deep Agents 的虚拟文件系统则是"压缩"的极致——把中间结果写文件，上下文里只留一个文件路径。

### 1.3 好的上下文工程长什么样

一句话：**每个 Agent 恰好看到它需要的信息，不多不少。**

"不多"好理解——冗余信息会让上下文膨胀、分散模型注意力。"不少"才是难点——关键信息漏了，Agent 就会基于不完整的上下文做决策，得出错误结论。举个徒步规划的例子：主 Agent 派给天气专家时只传了"川西"两个字，没传天数，天气专家就只能给个笼统的"川西多云"，而不是"未来3天逐日天气"——信息给少了，结论就没用。

### 1.4 上下文工程的三个原则

把"不多不少"落地成可执行的原则：

**原则一：最小化原则**——能不给的信息就不给。子 Agent 只需要回答主 Agent 的问题，不需要知道主 Agent 跟用户的前序闲聊。每次传递前问一句"这条信息对这个 Agent 完成任务必需吗"，不是就砍掉。

**原则二：隔离原则**——子 Agent 的内部推理不泄漏给主 Agent。Day 02 我们强调过，子 Agent 内部"调工具→看结果→再思考"的过程是它的私事，主 Agent 只该看到最终结论。一旦过程泄漏，主 Agent 上下文又被撑爆，多 Agent 的隔离价值就归零了。

**原则三：结构化原则**——信息以结构化方式传递，不是原始 messages 堆叠。与其把一坨 JSON 扔给主 Agent，不如让子 Agent 返回"路线专家结论：川西3天推荐路线A，难度中等"这样的结构化摘要。结构化信息既省 token，又方便主 Agent 理解和综合。

```
反例（违反三原则）：
  主Agent上下文 = 原始messages堆叠 + 子Agent完整推理过程 + 冗余闲聊
  → 膨胀 + 噪声 + 难综合

正例（遵循三原则）：
  主Agent上下文 = system(协调者) + user问题 + 各子Agent结构化结论
  → 精简 + 聚焦 + 易综合
```

---

## 二、三种上下文管理策略

理解了原则，接下来看具体怎么落地。多 Agent 系统的上下文管理基本就三种策略，对应 Day 02-05 学过的不同模式。

### 2.1 上下文隔离（Subagents 模式）

**机制：** 每个子 Agent 有独立的上下文窗口，主 Agent 只看子 Agent 的返回值（结论），不看子 Agent 内部的推理过程。

这是我们 Day 02 Subagents 模式的核心。主 Agent 调用包装成 tool 的子 Agent 时，子 Agent 在自己的上下文里跑完整 ReAct 循环——调工具、看结果、思考——这些过程全部留在子 Agent 的 messages 里。主 Agent 拿到的只是 tool 的返回值，也就是子 Agent 的最终结论。

```python
# 上下文隔离示例：Subagents 模式
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

model = init_chat_model("gpt-4o-mini", temperature=0)

# 路线专家子 Agent，独立上下文
route_expert = create_agent(
    model=model,
    tools=[...],  # 路线相关工具
    system_prompt="你是路线专家，只负责检索和推荐徒步路线。",
    checkpointer=InMemorySaver(),  # 独立实例，和主 Agent 隔离
)

@tool
def ask_route_expert(query: str) -> str:
    """向路线专家提问，获取徒步路线推荐。query 为路线相关需求。"""
    # 子 Agent 的内部推理（工具调用、思考过程）不会暴露给主 Agent
    result = route_expert.invoke({"messages": [{"role": "user", "content": query}]})
    # 主 Agent 只看到这个返回值——最终结论
    return result["messages"][-1].content
```

**优点：** 上下文精简（主 Agent 只存结论）、可并行（多个子 Agent 同时跑各自上下文）。

**缺点：** 信息丢失——子 Agent 的推理过程对主 Agent 不可见，如果子 Agent 推理出了问题，主 Agent 无从知晓。

适用场景：多领域并行任务，主 Agent 专注综合决策。

### 2.2 上下文共享（Handoffs 模式）

**机制：** 所有 Agent 共享同一份 messages，上下文连续，但会随对话轮次膨胀。

这是 Day 03 Handoffs 模式的特点。因为控制权在 Agent 间交接，用户始终和"当前接管的 Agent"对话，所以对话历史必须连续——新接手的 Agent 得能看到前面聊了什么，否则就"失忆"了。

```python
# 上下文共享示例（Handoffs）
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import add_messages

class HandoffState(TypedDict):
    # 所有 Agent 共享同一份 messages，add_messages 做追加合并
    messages: Annotated[list, add_messages]
    current_agent: str  # 当前握有控制权的 Agent

# 路线 Agent 和天气 Agent 看到的是同一份 messages
# 接管时不需要手动传递上下文，天然连续
```

**优点：** 信息连续、适合多轮对话，交接的 Agent 能"接着上一个人的话往下说"。

**缺点：** 上下文随轮次越来越长，token 消耗递增；所有领域的信息混在一起，可能互相干扰。

适用场景：多轮对话、角色会切换的场景（客服流转、多步骤审批）。

### 2.3 上下文压缩（通用策略）

**机制：** 不论哪种模式，都可以对上下文做压缩——主动减少传递的信息量，只保留关键部分。

上下文压缩不是一种独立模式，而是给上面两种策略打的"补丁"。Subagents 天然做了压缩（只传结论），Handoffs 则必须主动压缩（否则 messages 无限膨胀）。三种常见压缩手段：

```python
# 上下文压缩示例：子 Agent 返回结构化摘要而非完整对话
@tool
def ask_route_expert(query: str) -> str:
    """向路线专家提问，获取徒步路线推荐。query 为路线相关需求。"""
    result = route_expert.invoke({"messages": [{"role": "user", "content": query}]})
    full_response = result["messages"][-1].content
    # 只返回结构化结论，不返回推理过程
    # 策略1：只传结论不传过程（Subagents 天然实现）
    return f"路线专家结论：{full_response}"
```

**策略一：只传结论不传过程。** 子 Agent 内部可能调了三五次工具、思考了半天，但回传给主 Agent 的只有一句话结论。Subagents 模式天然实现了这个策略。

**策略二：摘要压缩。** 对长对话做摘要后传递。比如 Handoffs 里 messages 累积到 20 轮，可以在交接前让 LLM 把前 15 轮总结成一段摘要，只带着摘要 + 最近 5 轮进入下一个 Agent。

```python
# 策略2：摘要压缩（伪代码，展示思路）
def compress_messages(messages, keep_recent=5):
    """把历史消息压缩成摘要 + 最近几轮。"""
    if len(messages) <= keep_recent:
        return messages  # 不够长不用压
    # 让 LLM 把前面的历史总结成一段
    history = messages[:-keep_recent]
    summary = summarize(history)  # 调 LLM 做摘要
    recent = messages[-keep_recent:]
    return [{"role": "system", "content": f"历史摘要：{summary}"}] + recent
```

**策略三：文件系统转储。** Deep Agents 的做法——把中间结果写到虚拟文件系统，上下文里只留一个文件路径。需要时再读出来。这是"压缩"的极致：上下文里几乎不存大块信息，全靠文件系统承载。

### 2.4 三种策略对比

| 策略 | 代表模式 | 信息可见性 | 上下文长度 | 并行能力 | 信息丢失风险 |
|------|---------|-----------|-----------|---------|-------------|
| 上下文隔离 | Subagents | 主 Agent 只看结论 | 短而精简 | 高 | 高（过程不可见） |
| 上下文共享 | Handoffs | 所有 Agent 看同一份 | 随轮次膨胀 | 低 | 低（信息连续） |
| 上下文压缩 | 通用补丁 | 主动裁剪后传递 | 可控 | 取决于主模式 | 中（压缩可能丢关键信息） |

实际系统里三种策略经常组合用：Subagents 做隔离，子 Agent 返回时做压缩，长对话场景再叠加摘要。关键是根据场景权衡"信息完整度"和"上下文精简度"。

---

## 三、调试多 Agent 系统（重点）

### 3.1 多 Agent 调试的挑战

Week 06 调试单 Agent 时，你盯着一个 Agent 的 `stream_events` 看就够了——模型想了什么、调了哪个工具、工具返回什么，一目了然。但多 Agent 系统里，执行链路是这样的：

```
用户输入
  → 主 Agent 思考 → 调用 ask_route_expert tool
    → 路线子 Agent 思考 → 调用 search_routes tool
      → search_routes 返回路线数据
    → 路线子 Agent 总结 → 返回结论给主 Agent
  → 主 Agent 再思考 → 综合回复用户
```

一条链路上有三四层调用，任何一个环节出错都会导致最终结果不对。而表现出来的"症状"往往一样——用户拿到一个错误的回复。你得倒推：是主 Agent 派错了人？还是子 Agent 返回了不相关的结果？还是上下文传递丢了关键信息？

常见的多 Agent 故障模式：

| 故障 | 症状 | 根因 |
|------|------|------|
| 主 Agent 调错子 Agent | 用户问天气，主 Agent 派给了路线专家 | tool 的 docstring 不够清晰 |
| 子 Agent 返回无关结果 | 主 Agent 派对了人，但结论牛头不对马嘴 | 子 Agent 上下文信息不足或工具能力不够 |
| 上下文传递丢失信息 | 子 Agent 拿到的 query 缺关键字段，答非所问 | tool 参数设计或上下文压缩过度 |
| Agent 间死循环 | Handoffs 里两个 Agent 互相踢皮球，乒乓不停 | 交接条件设计有冲突 |

单 Agent 调试是"看一个点"，多 Agent 调试是"追一条链"。难度不在单个环节，而在链路太长、环节太多。

### 3.2 调试三板斧

针对多 Agent 的链路调试，给你一套三板斧，按顺序用。

**第一板斧：stream_events 追踪全链路**

用 Week 06 学过的 `stream_events(version="v3")` 追踪多 Agent 的完整执行流。在 Subagents 模式下，它能让你看到"主 Agent 调用 tool → 子 Agent 内部执行 → 返回结果"的全过程，而不只是最终的返回值。

```python
# 第一板斧：用 stream_events 追踪多 Agent 全链路
from uuid import uuid7

config = {"configurable": {"thread_id": str(uuid7())}}
input_data = {"messages": [{"role": "user", "content": "川西3天路线和天气怎么样？"}]}

# stream_events(version="v3") 会吐出每个节点的快照
stream = main_agent.stream_events(input_data, config, version="v3")
for snapshot in stream:
    # 打印每一步的 messages 内容（截断到100字符避免刷屏）
    if snapshot.messages:
        for msg in snapshot.messages:
            content_preview = (msg.content or "")[:100]
            print(f"[{msg.type}]: {content_preview}")
    # 打印当前 state 的字段，看上下文怎么变化
    if snapshot.values:
        print(f"[state keys]: {list(snapshot.values.keys())}")
```

`stream_events` 的输出量在多 Agent 场景下会很大（每个子 Agent 的内部循环都会刷出来），所以要学会过滤——只看关键节点：主 Agent 的 tool_call、子 Agent 的最终返回、state 字段的变化。

> **过滤技巧：** 别把每条 event 都打印，重点盯三类：`on_tool_start`（谁调了什么 tool）、`on_tool_end`（tool 返回了什么）、`on_chat_model_stream`（模型在想什么）。其他事件可以静默。

**第二板斧：上下文检查**

在关键节点手动打印当前 Agent 的 messages 内容和长度，检查传递给子 Agent 的上下文是否包含了不必要的信息，或者漏了关键信息。这一招最朴素，但在定位"信息丢失"类问题时最有效。

```python
# 第二板斧：在 tool 包装层插桩打印上下文
@tool
def ask_route_expert(query: str) -> str:
    """向路线专家提问，获取徒步路线推荐。query 为路线相关需求。"""
    # 检查传给子 Agent 的 query 是否包含足够信息
    print(f"[DEBUG] 传给路线专家的query: {query}")
    print(f"[DEBUG] query长度: {len(query)} 字符")

    result = route_expert.invoke({"messages": [{"role": "user", "content": query}]})

    # 检查子 Agent 返回了什么
    returned = result["messages"][-1].content
    print(f"[DEBUG] 路线专家返回: {returned[:200]}")
    print(f"[DEBUG] 返回长度: {len(returned)} 字符")

    # 检查子 Agent 内部调了几次工具（看 messages 里 tool 类消息的数量）
    tool_calls = [m for m in result["messages"] if m.type == "tool"]
    print(f"[DEBUG] 路线专家内部调了 {len(tool_calls)} 次工具")

    return returned
```

这种插桩打印能帮你快速定位：query 是不是太简略？子 Agent 是不是没调工具就瞎答？返回的结论是不是太长或太短？

**第三板斧：LangSmith trace**

`stream_events` 是在代码里看，LangSmith 则是可视化地看完整调用链——每个 Agent 的输入输出、每次工具调用、每一步的 token 消耗，全部以树状图展示。多 Agent 场景下，LangSmith 的树状 trace 能让你一眼看出"哪个分支出了问题"。

配置方式很简单，设好环境变量后，之后所有 invoke / stream_events 都会自动被 trace：

```python
# 第三板斧：配置 LangSmith 自动追踪
import os

os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_API_KEY"] = "your-langsmith-key"
os.environ["LANGSMITH_PROJECT"] = "week07-multi-agent"

# 之后所有 invoke / stream_events 都会自动上报到 LangSmith
# 打开 LangSmith 控制台就能看到完整的调用链树状图
result = main_agent.invoke(
    {"messages": [{"role": "user", "content": "川西3天路线和天气怎么样？"}]},
    config={"configurable": {"thread_id": "debug-001"}},
)
# 去 langsmith.com 看 trace，每个子 Agent 的调用都是一个子节点
```

LangSmith trace 的树状结构在多 Agent 调试里特别好用：主 Agent 是根节点，每个子 Agent 的调用是它的子节点，子 Agent 内部的工具调用又是子节点的子节点。哪一层出问题，顺着树往下找就行。

> **三板斧怎么配合用：** 先用 LangSmith trace 看整体链路，定位"大概哪一层出问题"；再用 stream_events 细看那一层的执行流；最后用上下文检查插桩，确认传递的信息对不对。从粗到细，逐层下钻。

### 3.3 实战调试示例

来看一个有 bug 的真实场景。我们有个多 Agent 系统：路线专家、天气专家、装备专家三个子 Agent，主 Agent 协调它们。用户问"去川西徒步要带什么装备"，结果主 Agent 居然派给了路线专家——答非所问。

**第一步：LangSmith trace 看整体。** 打开 trace 树状图，发现主 Agent 的第一个 tool_call 是 `ask_route_expert`，而不是应该的 `ask_gear_expert`。问题定位在"主 Agent 选错子 Agent"这一层。

**第二步：stream_events 细看主 Agent 的思考。** 看 `on_chat_model_stream` 事件，主 Agent 的推理过程是"用户提到川西徒步，应该先查路线"——它把"川西徒步"理解成了路线问题，忽略了"要带什么装备"这个真正的意图。

**第三步：上下文检查。** 看 tool 的 docstring：

```python
# 有 bug 的 tool 定义：docstring 没说清"什么时候用"
@tool
def ask_gear_expert(query: str) -> str:
    """向装备专家提问。"""
    ...
```

docstring 太简略，主 Agent 不知道"要带什么装备"该找装备专家。根因找到了。

**修复：优化 tool 的 docstring，让主 Agent 选择更准确。**

```python
# 修复后：docstring 写清触发条件和参数含义
@tool
def ask_gear_expert(query: str) -> str:
    """向装备专家提问，获取徒步装备清单。当用户问"带什么装备""需要准备什么""穿什么"时调用。query 为装备相关需求描述。"""
    ...
```

修完再跑，主 Agent 正确地把"去川西徒步要带什么装备"派给了装备专家。这就是三板斧的完整流程：trace 定位层级 → stream_events 看推理 → 上下文检查找根因 → 修 docstring。

> **经验：** 多 Agent 系统里，tool 的 docstring 不仅是给开发者看的文档，更是给主 Agent LLM 看的"路由指令"。docstring 写得越清晰（什么时候用、参数是什么），主 Agent 选对的概率越高。这是 Day 02 就强调过的坑，在调试时尤其要复查。

---

## 动手实验

### 🟢 青铜：给 Day 02 的 Subagents demo 加 stream_events 追踪

把 Day 02 的 `subagents_demo.py` 拿过来，给主 Agent 的调用加上 `stream_events(version="v3")` 追踪。重点不是看最终回复，而是观察多 Agent 执行链路：

1. 主 Agent 何时决定调用子 Agent（看 `on_tool_start` 事件）
2. 子 Agent 内部调了哪些底层工具（看子 Agent 的 tool 事件）
3. 子 Agent 的返回值何时回到主 Agent（看 `on_tool_end` 事件）
4. 把执行链路画成一张 ASCII 图，标注每一步发生的事

目标：从"只看最终结果"升级到"能看懂全链路执行流"。

### 🟡 白银：完成 context_eng.py — 上下文隔离实验

写一个 `context_eng.py`，对比单 Agent vs Subagents 模式下，主上下文的长度差异：

```python
"""context_eng.py — 上下文隔离实验：对比单 Agent vs Subagents 的上下文长度"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver


@tool
def search_routes(region: str, days: int) -> str:
    """检索徒步路线。region 为区域，days 为天数。"""
    return f"{region}{days}天路线：D1 成都→康定→新都桥；D2 新都桥→塔公；D3 塔公→丹巴"


@tool
def get_weather(city: str) -> str:
    """查询城市天气。city 为城市名。"""
    return f"{city}：多云转晴，5-18°C，风力2级"


model = init_chat_model("gpt-4o-mini", temperature=0)
question = "川西3天路线和天气怎么样？"

# ---- 方案 A：单 Agent，所有工具塞给它 ----
single = create_agent(model=model, tools=[search_routes, get_weather],
                      system_prompt="你是徒步规划助手，查路线和天气。",
                      checkpointer=InMemorySaver())
res_a = single.invoke({"messages": [{"role": "user", "content": question}]},
                      config={"configurable": {"thread_id": "a"}})

# ---- 方案 B：Subagents，子 Agent 隔离 ----
route_expert = create_agent(model=model, tools=[search_routes],
                            system_prompt="你是路线专家，只给路线结论。",
                            checkpointer=InMemorySaver())
weather_expert = create_agent(model=model, tools=[get_weather],
                              system_prompt="你是天气专家，只报天气。",
                              checkpointer=InMemorySaver())


@tool
def ask_route_expert(query: str) -> str:
    """向路线专家提问，获取路线推荐。"""
    return route_expert.invoke({"messages": [{"role": "user", "content": query}]})["messages"][-1].content


@tool
def ask_weather_expert(query: str) -> str:
    """向天气专家提问，获取天气信息。"""
    return weather_expert.invoke({"messages": [{"role": "user", "content": query}]})["messages"][-1].content


multi = create_agent(model=model, tools=[ask_route_expert, ask_weather_expert],
                     system_prompt="你是徒步规划主助手，把路线和天气任务派给专家。",
                     checkpointer=InMemorySaver())
res_b = multi.invoke({"messages": [{"role": "user", "content": question}]},
                     config={"configurable": {"thread_id": "b"}})


# ---- 对比主上下文长度 ----
def count_tokens(messages):
    """粗略估算 token：按字符数 / 1.5（中文系数）。"""
    total_chars = sum(len(m.content) if hasattr(m, "content") and m.content else 0
                     for m in messages)
    return int(total_chars / 1.5)


print("=== 上下文长度对比 ===")
print(f"单 Agent messages 条数: {len(res_a['messages'])}")
print(f"单 Agent 估算 token: ~{count_tokens(res_a['messages'])}")
print(f"Subagents 主 Agent messages 条数: {len(res_b['messages'])}")
print(f"Subagents 主 Agent 估算 token: ~{count_tokens(res_b['messages'])}")
print("\n=== 结论 ===")
print("单 Agent 主上下文含原始工具返回，Subagents 主上下文只有结论摘要")
```

实验要求：
1. 跑通两个方案，记录主上下文的 messages 条数和估算 token
2. 验证：Subagents 主 Agent 的 messages 里有没有出现 `search_routes` / `get_weather` 这两个底层工具名（应该没有）
3. 单独打印子 Agent 内部的 messages，对比"过程"和"结论"的体量差异
4. 把对比结果整理成表格，作为上下文隔离的量化证据

### 🔴 王者：故意写一个有 bug 的多 Agent 系统，用三板斧定位并修复

挑战题：故意写一个有 bug 的多 Agent 系统，然后用今天的三板斧定位并修复。

1. 故意把某个 tool 的 docstring 写得很模糊（比如装备专家的 docstring 只写"问专家"），让主 Agent 容易选错子 Agent
2. 用 LangSmith trace 跑一次，观察主 Agent 选了哪个子 Agent，定位"选错"这一层
3. 用 stream_events 看主 Agent 的推理过程，理解它为什么选错
4. 用上下文检查插桩，确认 tool 的 docstring 是根因
5. 优化 docstring 后重跑，验证主 Agent 选对了
6. 记录整个"定位→修复"过程，形成一份调试报告

进阶：再人为制造一个"上下文传递丢信息"的 bug（比如主 Agent 派给天气专家时只传了城市名没传天数），用三板斧定位并修复。

---

## 踩坑记录 🕳️

### 坑 1：多 Agent 调试比单 Agent 难 3 倍

单 Agent 调试盯着一个 Agent 看就行，多 Agent 要追一条链路。链路越长，"症状"和"根因"隔得越远——用户看到的是最终回复不对，但根因可能在三四层之前的某个子 Agent 选错工具。

**解决：** 养成"从粗到细下钻"的调试习惯。先用 LangSmith trace 看整体链路定位大致层级，再用 stream_events 细看那一层，最后用上下文检查插桩确认。别一上来就钻进单个 Agent 的代码里。

### 坑 2：stream_events 在多 Agent 场景下输出量爆炸

单 Agent 的 stream_events 输出就不少了，多 Agent 场景下每个子 Agent 的内部循环都会刷出来，几十上百条 event 看得人眼花。

**解决：** 学会过滤。只盯三类关键事件：`on_tool_start`（谁调了什么 tool）、`on_tool_end`（tool 返回了什么）、`on_chat_model_stream`（模型在想什么）。其他事件静默。也可以在打印时加 `[DEBUG]` 前缀和内容截断（`[:100]`），避免一条 event 刷满半屏。

### 坑 3：LangSmith trace 免费额度有限

LangSmith 免费版有调用次数和 trace 存储量限制。多 Agent 系统一次 invoke 可能产生十几条 trace（主 Agent + 多个子 Agent + 每个的工具调用），调试时如果反复跑，额度很快就用光。

**解决：** 调试时控制调用次数——先把代码逻辑跑通（用 mock 数据，不调真模型），再用 LangSmith trace 做几次"精调试"。别一边改代码一边反复 invoke 刷 trace。可以临时关掉 tracing（`os.environ["LANGSMITH_TRACING"] = "false"`），只在需要看链路时打开。

### 坑 4：上下文压缩过度导致信息丢失

压缩是好事，但压过头就坏事。子 Agent 只回传一句话结论，如果结论太简略，主 Agent 综合时就缺关键信息。比如路线专家只回"推荐路线A"，主 Agent 没法告诉用户路线A 的难度和里程——这些信息被压没了。

**解决：** 压缩时保留"结论 + 关键属性"。路线专家的回传应该是"路线专家结论：川西3天推荐路线A，难度中等，总里程45km，D1 成都→康定→新都桥..."。结构化返回，既精简又保留了决策所需的关键字段。压缩的度要在"信息完整"和"上下文精简"之间找平衡，没有标准答案，靠实验调。

---

## 副线笔记：用 Claude Code 调试多 Agent trace

今天的副线是把"调试多 Agent"这件事本身也交给一个多 Agent 系统来做——用 Claude Code 辅助调试我们写的多 Agent 代码。

Claude Code 本身就是一个多 Agent 系统（Day 02 副线分析过它的 Subagents 架构）。我们可以利用它来分析我们多 Agent 系统的 stream_events 输出和 LangSmith trace，让它帮我们定位协作异常。

**做法一：让 Claude Code 分析 stream_events 输出**

把你的多 Agent 代码和 stream_events 的输出日志一起喂给 Claude Code，让它分析：

```
"这是我写的 Subagents 多 Agent 代码，这是 stream_events 的输出日志。
 用户问了'川西3天路线和天气'，但最终回复只提了路线没提天气。
 请分析执行链路，定位是哪个环节出了问题。"
```

Claude Code 会顺着日志链路推理：主 Agent 调了哪几个 tool？天气专家的子 Agent 有没有被调用？如果没被调用，是主 Agent 漏调了，还是调了但返回空？

**做法二：让 Claude Code 读 LangSmith trace 的 JSON**

LangSmith 支持导出 trace 的 JSON。把 JSON 给 Claude Code，让它解读树状结构，指出异常分支。比人工在网页上逐层点开看快得多。

**对比手动调试 vs AI 辅助调试：**

| 维度 | 手动调试 | AI 辅助调试（Claude Code） |
|------|---------|---------------------------|
| 速度 | 慢，要逐层点开看 | 快，一次性分析整条链路 |
| 深度 | 能看到所有细节 | 依赖喂给它的信息量 |
| 适合场景 | 复杂/底层问题 | 链路梳理、模式识别 |
| 局限 | 人容易看漏 | 给的信息不全它也会漏判 |

**今日观察任务：**

- 用 Claude Code 处理一个你写的多 Agent 调试任务，把 stream_events 输出交给它分析
- 对比你自己手动调试和 AI 辅助调试的效率差异
- 思考：Claude Code 自己作为多 Agent 系统，它在帮你调试时，它的子 Agent 是怎么协作的？你能从它的行为里观察到上下文隔离吗？

---

## 检查清单

- [ ] 理解上下文工程的三层决策（分配、压缩、传递）和三个原则（最小化、隔离、结构化）
- [ ] 掌握三种上下文管理策略：隔离（Subagents）、共享（Handoffs）、压缩（通用）
- [ ] 能说出三种策略各自的优缺点和适用场景
- [ ] 能用 stream_events(version="v3") 追踪多 Agent 的完整执行链路
- [ ] 完成了 `context_eng.py`，量化对比单 Agent vs Subagents 的上下文长度
- [ ] 知道多 Agent 调试三板斧：stream_events 追踪、上下文检查、LangSmith trace
- [ ] 能用三板斧按"从粗到细下钻"的顺序定位多 Agent 故障
- [ ] 尝试用 Claude Code 辅助分析多 Agent trace

---

## 下车预告

Day 06 我们把上下文工程和调试这两块"地基"夯实了。Day 07 是本周的综合实战——用 Subagents 模式构建完整的多 Agent 徒步出行规划系统。你会把路线专家、天气专家、装备专家、规划主 Agent 组装起来，配上上下文隔离、LangSmith trace、FastAPI 服务化，做一个能跑、能调、能扩展的完整系统。本周所有学的东西都在这一天落地。
