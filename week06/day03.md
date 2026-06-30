# Day 03 — LangGraph 入门：StateGraph / Node / Edge

## 学习目标

Day 01-02 我们用 LangChain 的 LCEL 链和 `bind_tools` 把 Week 03 手写的 httpx 调用换成了框架写法——更短、更规范，但控制流还是"一条链往下走"。今天进入本周核心：**LangGraph**。它把 Week 03 那个 `while True: call → parse → execute → append` 的隐式循环，升级成一张"节点 + 边"的**显式状态图**。控制流从代码里藏在循环体里的 if/else，变成了可以画出来、可以可视化、可以插桩调试的图结构。

学完今天你能：
1. 说清楚 LangGraph 的三要素 State / Node / Edge 各自的职责，以及它们如何替代 Week 03 手写的 `messages` 列表 + `while True` 循环
2. 用 `TypedDict` + `Annotated[list, add_messages]` 定义带 reducer 的状态，并解释"节点返回 partial state、reducer 决定如何合并到全状态"的机制
3. 写出包含 `START` / `add_node` / `add_edge` / `END` / `compile()` / `invoke()` 的完整线性图，并能把它画成 ASCII 草图
4. 把 Day 01 的 LCEL 链改写成 LangGraph 图（单节点图 + 两节点"分类→回复"图），完成今天的产出文件 `langgraph_intro.py`

---

## 一、为什么需要 LangGraph：从"隐式循环"到"显式图"

### 1.1 Week 03 的 while True 是"隐式控制流"

回忆 Week 03 / Day 03 的 `agent_loop.py`，核心是这么一段：

```python
# Week 03 的 Agent Loop（隐式控制流）
def agent_loop(user_input):
    messages = [system_prompt, {"role": "user", "content": user_input}]
    while True:
        response = call_llm(messages, tools)      # 调 LLM
        if response 有 tool_calls:                # 分支藏在 if 里
            for tc in tool_calls:
                result = execute_tool(tc)          # 执行工具
                messages.append({"role": "tool", ...})  # 手动追加
            continue                               # 回到 while 顶部
        elif response 有文本回答:
            return response.text                   # 退出
        else:
            handle_unexpected()
```

这段代码能跑，但它的控制流是**藏在代码缩进和 `continue`/`return` 里的**。你没法一眼看出："这个 Agent 有几个步骤？哪一步会循环？哪一步会终止？在哪个点可以插入人工确认？"。这些问题都要通读代码、在脑子里模拟执行才能回答。

### 1.2 隐式控制流的三个痛点

| 痛点 | Week 03 手写循环的表现 | LangGraph 怎么解决 |
|------|----------------------|-------------------|
| **难以可视化** | 控制流藏在 if/else/continue 里，画不出图 | 图本身就是结构，`graph.get_graph().draw_*` 可直接可视化 |
| **难以插入人机交互** | 想在"执行工具前问用户确认"要硬插代码、改循环 | 在边上加 `interrupt()`，图自然暂停在该节点 |
| **难以持久化** | `messages` 是内存里的 list，进程一死全丢 | Checkpointer 自动给每一步状态存档，断点恢复 |
| **难以并行** | 想并行调两个工具要自己写 `asyncio.gather` | 多条边指向同一节点就是并行，框架自动调度 |

### 1.3 LangGraph 把控制流显式化成"图"

LangGraph 的核心思想：**控制流 = 图（Graph）**。一个 Agent 就是一张有向图：

- **节点（Node）** = 一步操作（调 LLM、执行工具、分类、回复……）
- **边（Edge）** = 控制流的走向（从 A 走到 B、从 B 走到 END）
- **状态（State）** = 在节点之间流动的"共享数据"，每经过一个节点就更新一次

```
循环 vs 图 的对比

Week 03（循环）                    LangGraph（图）
┌─────────────────┐              ┌───┐    ┌──────┐    ┌─────┐    ┌───┐
│ while True:     │              │ S │───►│ LLM  │───►│工具?│───►│ E │
│   call_llm()    │   ───────►   │ T │    │ node │    │节点 │    │ N │
│   if tool:      │              │ A │    └──────┘    └─────┘    │ D │
│     continue    │              │ R │                            └───┘
│   else: return  │              │ T │
└─────────────────┘              └───┘
  控制流藏在代码里                  控制流就是图结构本身
```

> **关键认知：** LangGraph 不是"又一个 Agent 框架"，它是一个**通用状态机执行引擎**。你定义图（状态结构 + 节点 + 边），它负责按图执行、管理状态、支持暂停/恢复/持久化。Agent 只是图的一种特例——带循环边的图。

---

## 二、State 状态定义（重点）

State 是 LangGraph 的地基。理解了 State，Node 和 Edge 都顺理成章。

### 2.1 为什么需要 State：对比 Week 03 手动管理 messages

Week 03 我们手动管理一个 `messages` 列表：

```python
# Week 03：手动管理状态
messages = [system_prompt, {"role": "user", "content": q}]
# ... 每轮手动 append
messages.append(assistant_msg)           # 手动加 assistant
messages.extend(tool_messages)           # 手动加 tool 结果
# 想加个 "分类结果" 字段？只能塞进某条 message 的 content 里，很丑
```

问题：状态散落在变量里，没有 schema，加字段要改一堆代码，多节点共享状态全靠手动传递。

LangGraph 用一个 **TypedDict** 把状态结构显式声明出来，所有节点共享同一份状态，每个节点只返回它想更新的字段。

### 2.2 TypedDict + Annotated + reducer

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END


class MyState(TypedDict):
    # messages 字段：用 add_messages reducer
    # 含义：节点返回新消息时，不是"覆盖"，而是"追加"到已有列表
    messages: Annotated[list, add_messages]
    # 普通字段：没有 reducer，节点返回什么就覆盖什么
    category: str
```

**reducer 是什么？** 它是一个函数 `reducer(旧值, 新值) -> 合并值`，决定节点返回的 partial state 如何合并到全状态：

| 字段类型 | reducer | 合并行为 | 典型场景 |
|---------|---------|---------|---------|
| `Annotated[list, add_messages]` | `add_messages` | 追加（append） | 聊天历史，越聊越长 |
| `Annotated[list, operator.add]` | `operator.add` | 列表拼接 | 累积收集的检索结果 |
| 无 Annotated（普通字段） | 默认（覆盖） | 直接覆盖 | 分类标签、最终答案 |

### 2.3 节点返回 partial state，reducer 决定怎么合并

这是 LangGraph 最核心的机制，必须理解透：

```python
def classify_node(state: MyState) -> dict:
    """分类节点：只更新 category 字段，不碰 messages。"""
    last_msg = state["messages"][-1].content
    category = "技术" if "代码" in last_msg or "Python" in last_msg else "闲聊"
    # ✅ 返回 partial state：只包含要更新的字段
    return {"category": category}


def respond_node(state: MyState) -> dict:
    """回复节点：往 messages 里追加一条 AI 回复。"""
    reply = f"这是{state['category']}类问题，我的回答是……"
    # ✅ 因为 messages 用了 add_messages reducer，这里返回的新消息会被"追加"
    return {"messages": [HumanMessage(content=reply)]}  # 实际用 AIMessage
```

**执行流程**：

```
全状态 state = {messages: [...], category: ""}
        │
        ▼
  classify_node 执行，返回 {"category": "技术"}
        │
        ▼
  LangGraph 合并：category 无 reducer → 直接覆盖 → category = "技术"
        │
        ▼
  state = {messages: [...], category: "技术"}
        │
        ▼
  respond_node 执行，返回 {"messages": [新消息]}
        │
        ▼
  LangGraph 合并：messages 有 add_messages reducer → 追加
        │
        ▼
  state = {messages: [..., 新消息], category: "技术"}
```

> **对比 Week 03：** Week 03 是"手动 append 到同一个 list"；LangGraph 是"节点只声明自己改了什么，reducer 自动合并"。后者让节点变成纯函数——输入 state、输出 partial state、无副作用，因此**极易单元测试**。

### 2.4 两种内置/自定义 State 示例

**示例 1：用内置 MessagesState（最省事）**

```python
from langgraph.graph import StateGraph, MessagesState, START, END

# MessagesState 是官方预置状态，等价于：
# class MessagesState(TypedDict):
#     messages: Annotated[list, add_messages]
# 适合纯对话场景，不想自定义字段时直接用

def chat_node(state: MessagesState) -> dict:
    """一个最简单的对话节点：把最后一条消息原样回显。"""
    last = state["messages"][-1]
    return {"messages": [{"role": "assistant", "content": f"你说的是：{last.content}"}]}

graph = StateGraph(MessagesState)   # 直接用内置 State
graph.add_node("chat", chat_node)
graph.add_edge(START, "chat")
graph.add_edge("chat", END)
app = graph.compile()
```

**示例 2：自定义 State（带业务字段）**

```python
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]   # 对话历史（追加）
    category: str                              # 分类标签（覆盖）
    confidence: float                          # 置信度（覆盖）

# 需要在节点间传递"分类结果""置信度"这类业务字段时，必须自定义 State
```

---

## 三、Node 节点：接收 state 返回 partial state 的纯函数

### 3.1 节点就是一个普通函数

节点没有任何魔法——它就是一个 `def node(state) -> dict` 的函数。LangGraph 调用它时把当前全状态传进去，它返回想更新的字段。

```python
def classify_node(state: MyState) -> dict:
    """分类节点：根据最后一条消息判断类别。"""
    last_msg = state["messages"][-1].content
    if any(kw in last_msg for kw in ["代码", "Python", "报错"]):
        category = "技术"
    elif any(kw in last_msg for kw in ["你好", "天气", "吃饭"]):
        category = "闲聊"
    else:
        category = "其他"
    return {"category": category}   # 只更新 category


def respond_node(state: MyState) -> dict:
    """回复节点：根据分类生成回复。"""
    cat = state["category"]
    if cat == "技术":
        reply = "这是一个技术问题，让我帮你看看代码。"
    elif cat == "闲聊":
        reply = "闲聊很开心呀！"
    else:
        reply = "我不太确定这是什么类型，但我会尽力回答。"
    return {"messages": [{"role": "assistant", "content": reply}]}
```

### 3.2 add_node 注册节点

定义好函数后，用 `add_node(名字, 函数)` 注册到图里。**节点的名字是字符串**，边的连接用的是这个名字而不是函数对象。

```python
graph = StateGraph(MyState)
graph.add_node("classify", classify_node)   # 名字 "classify" → 函数 classify_node
graph.add_node("respond", respond_node)     # 名字 "respond"  → 函数 respond_node
```

### 3.3 节点是纯函数，易于测试

这是 LangGraph 设计上最香的一点。因为节点只依赖入参 state、只返回 partial state，你可以脱离图单独测试它：

```python
# 单元测试 classify_node，不需要编译图、不需要真调 LLM
def test_classify_node():
    state = {"messages": [{"role": "user", "content": "我的 Python 代码报错了"}], "category": ""}
    result = classify_node(state)
    assert result == {"category": "技术"}

test_classify_node()   # 秒过
```

对比 Week 03：那时的逻辑和 `call_llm`、`messages` 列表、循环体耦合在一起，想单独测"分类逻辑"得 mock 一大堆东西。

| 特性 | Week 03 手写循环 | LangGraph 节点 |
|------|----------------|---------------|
| 单元测试 | 要 mock LLM、构造 messages | 直接传 state 调函数 |
| 复用 | 逻辑焊死在循环里 | 节点函数可在多个图里复用 |
| 副作用 | 直接改外部 messages 列表 | 只返回 partial state，无副作用 |
| 可读性 | 控制流和业务逻辑混在一起 | 一个节点只干一件事 |

---

## 四、Edge 边与 START / END

### 4.1 三种边 + 两个特殊节点

```python
from langgraph.graph import StateGraph, START, END

graph = StateGraph(MyState)
graph.add_node("node_a", node_a_fn)
graph.add_node("node_b", node_b_fn)

# ① 入口边：START → node_a（图从哪开始）
graph.add_edge(START, "node_a")
# ② 普通边：node_a → node_b（固定走向）
graph.add_edge("node_a", "node_b")
# ③ 终止边：node_b → END（图在哪结束）
graph.add_edge("node_b", END)
```

- **`START`**：虚拟入口节点，图执行的起点。每个图必须有至少一条 `START → 某节点` 的边。
- **`END`**：虚拟终止节点，执行到 `END` 图就停了，返回最终状态。
- **普通边**：固定的"A 完了去 B"，今天只学这种。明天 Day 04 学**条件边**（根据 state 动态决定去哪）。

### 4.2 最简单的线性图：完整编译 + 调用

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END


class LinearState(TypedDict):
    value: int


def add_one(state: LinearState) -> dict:
    """节点 A：把 value 加 1。"""
    return {"value": state["value"] + 1}


def double(state: LinearState) -> dict:
    """节点 B：把 value 翻倍。"""
    return {"value": state["value"] * 2}


# 建图
graph = StateGraph(LinearState)
graph.add_node("add_one", add_one)
graph.add_node("double", double)

# 连边：START → add_one → double → END
graph.add_edge(START, "add_one")
graph.add_edge("add_one", "double")
graph.add_edge("double", END)

# 编译成可执行图（compile 后才能 invoke）
app = graph.compile()

# 调用：invoke 接收初始 state
result = app.invoke({"value": 10})
print(result["value"])   # (10 + 1) * 2 = 22
```

对应的 ASCII 图：

```
            ┌─────────┐    ┌────────┐
 START ───► │ add_one │──► │ double │ ───► END
            │  +1     │    │  *2    │
            └─────────┘    └────────┘

执行轨迹：value: 10 ──► 11 ──► 22
```

### 4.3 compile() 之后才能 invoke

`StateGraph` 是"图的定义"，还不能直接跑。`graph.compile()` 把它编译成一个可执行的 `CompiledGraph`（习惯上赋值给 `app`）。编译时会做校验：比如有没有节点没连边、有没有死循环（无 END 的纯循环）等。**只有编译过的图才能 `invoke` / `stream`。**

---

## 五、动手实现第一个图：从 LCEL 链到 LangGraph

### 5.1 回顾 Day 01 的 LCEL 链

Day 01 我们用 LCEL 写过这样的链：

```python
# Day 01 的 LCEL 链（回顾）
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

model = init_chat_model("gpt-4o-mini", temperature=0)
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个简洁的助手，回答不超过两句话。"),
    ("human", "{question}"),
])
# LCEL 用 | 串起来
chain = prompt | model | StrOutputParser()
answer = chain.invoke({"question": "什么是 LangGraph？"})
```

LCEL 链是一条**单向流水线**，没有状态、没有分支、没有循环。今天我们把它"升级"成 LangGraph 图。

### 5.2 单节点图：一个 LLM 节点 + END

最简单的图：只有一个 LLM 节点，等价于一次普通调用，但已经具备了图的骨架。

```python
"""langgraph_intro.py — LangGraph 入门：第一个图"""
from typing import TypedDict, Annotated
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages


# ─── 1. 定义状态 ───
class ChatState(TypedDict):
    messages: Annotated[list, add_messages]   # 用 reducer 自动追加


# ─── 2. 定义节点 ───
model = init_chat_model("gpt-4o-mini", temperature=0)


def llm_node(state: ChatState) -> dict:
    """LLM 节点：把全部历史发给模型，把回复追加到 messages。"""
    # 约定：第一条是 system，其余是对话
    response = model.invoke(state["messages"])
    # 返回 partial state，add_messages 会自动把 reply 追加进去
    return {"messages": [response]}


# ─── 3. 建图 ───
graph = StateGraph(ChatState)
graph.add_node("llm", llm_node)
graph.add_edge(START, "llm")     # 入口
graph.add_edge("llm", END)       # 出口

# ─── 4. 编译 + 调用 ───
app = graph.compile()

result = app.invoke({
    "messages": [
        SystemMessage(content="你是一个简洁的助手，回答不超过两句话。"),
        HumanMessage(content="什么是 LangGraph？"),
    ],
})
print(result["messages"][-1].content)
```

ASCII 图：

```
 START ───► ┌─────┐ ───► END
            │ llm │
            └─────┘
```

### 5.3 两节点图：分类 → 回复

进阶：加一个分类节点。先判断用户问题类别，再根据类别生成回复。这就是"多步推理"的雏形。

```python
# 接续上面的 ChatState，加一个 category 字段
class ClassifyState(TypedDict):
    messages: Annotated[list, add_messages]
    category: str                              # 新增：分类标签（覆盖式）


def classify_node(state: ClassifyState) -> dict:
    """分类节点：根据最后一条用户消息判断类别。不调 LLM，纯规则。"""
    last = state["messages"][-1].content
    if any(kw in last for kw in ["代码", "Python", "报错", "LangGraph"]):
        category = "技术"
    elif any(kw in last for kw in ["你好", "天气", "吃饭", "玩"]):
        category = "闲聊"
    else:
        category = "其他"
    print(f"  [classify] 判定类别: {category}")
    return {"category": category}   # 只更新 category


def respond_node(state: ClassifyState) -> dict:
    """回复节点：根据 category 调 LLM 生成针对性回复。"""
    cat = state["category"]
    guide = {
        "技术": "请用专业但易懂的语言解释技术概念。",
        "闲聊": "请用轻松友好的语气闲聊。",
        "其他": "请中立地回答。",
    }[cat]
    messages = state["messages"] + [SystemMessage(content=guide)]
    reply = model.invoke(messages)
    print(f"  [respond] 生成回复: {reply.content[:40]}...")
    return {"messages": [reply]}


# 建图：START → classify → respond → END
graph2 = StateGraph(ClassifyState)
graph2.add_node("classify", classify_node)
graph2.add_node("respond", respond_node)
graph2.add_edge(START, "classify")
graph2.add_edge("classify", "respond")
graph2.add_edge("respond", END)

app2 = graph2.compile()

# 调用
result = app2.invoke({
    "messages": [HumanMessage(content="我的 LangGraph 图跑不通，报错了")],
})
print("\n最终回复:", result["messages"][-1].content)
print("分类结果:", result["category"])
```

ASCII 图：

```
            ┌───────────┐    ┌──────────┐
 START ───► │ classify  │──► │ respond  │ ───► END
            │ (规则分类) │    │ (LLM回复) │
            └───────────┘    └──────────┘

状态流转：
  messages: [用户问题]
     ──► category="技术", messages 不变
     ──► messages=[用户问题, AI回复], category="技术"
```

### 5.4 今天的完整产出文件

把上面的单节点图 + 两节点图整合进 `langgraph_intro.py`，加上 `if __name__ == "__main__"` 跑通两个例子。这就是今天的产出物。完整代码见本节 5.2 / 5.3 的拼接，运行前确认已安装 `langgraph` 和 `langchain`：

```bash
pip install -U langgraph langchain
```

---

## 六、动手实验

### 🟢 青铜级：跑通单节点图

把 5.2 的单节点图跑起来，输入"什么是 LangGraph？"，确认能拿到模型的回复。然后改 `temperature=0.7` 再跑一次，观察回复的变化。目标：熟悉 `StateGraph → add_node → add_edge → compile → invoke` 这条最小闭环。

### 🟡 白银级：扩展两节点图为三节点

在 `classify → respond` 之间插入一个 `enrich_node`（信息丰富节点）：它根据 `category` 往 messages 里追加一条 system 提示（比如技术类追加"注意代码示例要正确"）。要求：
1. 定义 `enrich_node` 函数
2. 用 `add_node` 注册，用 `add_edge` 把图改成 `START → classify → enrich → respond → END`
3. 画出新的 ASCII 图，验证 state 在每个节点后的变化

### 🔴 王者级：自定义 reducer 累积检索结果

自定义一个 State，里面有一个 `findings: Annotated[list, operator.add]` 字段（用 `operator.add` 做 reducer，列表拼接）。写两个节点：`search_node`（模拟检索，返回 `{"findings": ["结果A"]}`）和 `analyze_node`（把累积的 findings 拼成总结）。图结构 `START → search → analyze → END`。验证：analyze 节点能拿到 search 节点累积的所有 findings。思考：如果想让图循环执行 search 三次再 analyze，应该怎么改（提示：明天 Day 04 的条件边）。

---

## 七、踩坑记录 🕳️

### 坑 1：节点返回了全状态而不是 partial state

```python
# ❌ 错误：返回了整个 state，而且 messages 没有 reducer 行为会被覆盖
def bad_node(state):
    state["category"] = "技术"
    return state   # 把整个 state 返回回去

# ✅ 正确：只返回要更新的字段（partial state）
def good_node(state):
    return {"category": "技术"}
```

**后果：** 如果返回了全 state，且某字段没有 reducer，会用你返回的值**覆盖**掉别的节点更新过的值，导致状态丢失。记住：**节点只返回它"动过"的字段。**

### 坑 2：忘记给 messages 加 add_messages reducer

```python
# ❌ 没用 Annotated，messages 变成"覆盖式"
class BadState(TypedDict):
    messages: list    # 没有 reducer！

def node(state):
    return {"messages": [新消息]}   # 直接覆盖！旧消息全没了

# ✅ 必须用 Annotated + add_messages
from langgraph.graph.message import add_messages
class GoodState(TypedDict):
    messages: Annotated[list, add_messages]
```

**症状：** 多节点图里，前一个节点加的 message 在下一个节点后消失了，模型"失忆"。十有八九是漏了 reducer。偷懒的话直接用内置的 `MessagesState`。

### 坑 3：边连到了未注册的节点名

```python
graph.add_node("classify", classify_node)
graph.add_edge(START, "classify")
graph.add_edge("classify", "respond")   # ❌ "respond" 还没 add_node！
graph.add_edge("respond", END)

app = graph.compile()   # 报错：找不到 "respond" 节点
```

**解决：** 先把所有 `add_node` 写完，再写 `add_edge`。节点名是字符串，拼错了不会立刻报错，要等 `compile()` 才炸，调试时容易懵。

### 坑 4：对 invoke 返回值结构不熟

```python
result = app.invoke({"messages": [HumanMessage(content="hi")]})

# ❌ 以为 result 就是最后一条回复文本
print(result)   # 其实是整个最终 state（dict）

# ✅ result 是最终状态，回复在 messages 列表最后一条
print(result["messages"][-1].content)
```

**记忆：** `invoke` 返回的是**最终的全状态 dict**，不是某个节点的返回值。想拿哪部分就 `result["字段名"]`。

### 坑 5：State 字段类型和节点返回值不匹配

```python
class MyState(TypedDict):
    confidence: float

def node(state):
    return {"confidence": "高"}   # ❌ 声明是 float，返回 str

# TypedDict 在运行时不强制类型，但下游节点 state["confidence"] > 0.5 会 TypeError
```

**解决：** TypedDict 只是"声明"，运行时不校验。类型不符的 bug 要等下游节点用到才暴露。写节点时对着 State 定义核对返回值类型，或上 Pydantic 做严格校验。

---

## 八、副线笔记：用 Claude Code 画状态机草图

### 8.1 先画图再写代码：一个被低估的工程习惯

写 LangGraph 图最容易翻车的地方，不是节点函数写错，而是**图的拓扑结构一开始就没想清楚**——边连错了、节点顺序乱了、忘了连 END。等你写完一坨代码 `compile()` 报错，再去定位是哪条边的问题，很费时间。

解决之道：**在动手写图之前，先用自然语言让 Claude Code 帮你把节点和边画成 ASCII 草图，确认控制流正确再写代码。** 这就是"先画图再写代码"。

### 8.2 怎么让 Claude Code 画草图

在 Claude Code 里直接用自然语言描述你的意图，让它输出 ASCII 图：

```
你（对 Claude Code 说）：
  我要写一个 LangGraph 图，流程是：
  1. 先分类用户问题（技术/闲聊/其他）
  2. 根据分类结果，走不同的回复策略
  3. 最后输出回复
  帮我画一张 ASCII 状态机草图，标出节点名、边、START/END，
  并指出哪条边需要条件边（明天才学，今天先标注出来）。

Claude Code 输出：
            ┌───────────┐
 START ───► │ classify  │ ──┬─(技术)─► ┌──────────┐
            │ (规则分类) │   │          │ tech_     │
            └───────────┘   ├─(闲聊)─► │ respond   │ ──► END
                            │          └──────────┘
                            └─(其他)─► ┌──────────┐
                                       │ other_    │
                                       │ respond   │ ──► END
                                       └──────────┘
  注意：classify → 三个 respond 是"条件边"（按 category 路由），
  今天 Day 03 还做不到，明天 Day 04 用 add_conditional_edges 实现。
  今天先做线性版：classify → respond → END（无条件）。
```

### 8.3 草图先行的好处

| 好处 | 说明 |
|------|------|
| **提前发现拓扑错误** | 草图上一眼能看出"有没有忘连 END""有没有孤立节点" |
| **区分今天能做/明天才做** | 草图会标出哪些是条件边，提醒你今天先用线性版占位 |
| **变成文档** | 草图直接贴进打卡文件的 ASCII 图位置，省得另画 |
| **降低心智负担** | 写代码时照着图连边，不用边写边在脑子里模拟控制流 |

### 8.4 一个实操建议

养成习惯：**每写一个新图，先用 Claude Code 画三样东西**——
1. 节点列表（每个节点干什么）
2. 边列表（谁连到谁，是否条件边）
3. ASCII 草图（含 START/END）

确认这三样无误后，再打开编辑器写 `add_node` / `add_edge`。你会发现，画图花 5 分钟，能省下 30 分钟的调试时间。这也正是 LangGraph 相比 Week 03 手写循环的最大优势——**控制流变得可见、可画、可讨论**。

> **类比记忆：** Week 03 的 while True 是"先写代码再猜控制流"，LangGraph 是"先画图再写代码"。从"代码即控制流"到"图即控制流"，这是从手写 Agent 到框架编排的关键一跃。

---

## 今日产出检查清单

- [ ] 能说清 State / Node / Edge 三要素的职责，以及它们如何替代 Week 03 的 messages 列表 + while True
- [ ] 能用 `TypedDict` + `Annotated[list, add_messages]` 定义带 reducer 的状态，解释 partial state 合并机制
- [ ] 写出包含 `START` / `add_node` / `add_edge` / `END` / `compile()` / `invoke()` 的完整线性图
- [ ] `langgraph_intro.py` 跑通单节点图（LLM 节点 + END）和两节点图（分类 → 回复）
- [ ] 能画出自己图的 ASCII 草图，并标注每个节点后 state 的变化
- [ ] 用 Claude Code 画过至少一张状态机草图，确认"先画图再写代码"的流程

---

> **下一课预告：Day 04 — LangGraph 进阶：条件边 / 循环 / create_react_agent**。今天我们只学了固定的线性边（A 完了去 B）。明天加上**条件边**（`add_conditional_edges`，根据 state 动态选下一条边），就能实现真正的 ReAct Agent 循环——LLLM 决定调工具就走工具节点，决定回答就走 END。最后用 `create_react_agent` 一行起手，对比手写图的差别。今天画的"分类→三分支"草图，明天亲手把它实现出来。
