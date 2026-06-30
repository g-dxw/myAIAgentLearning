# Day 05 — 持久化与人机交互：Checkpointer / interrupt

## 学习目标

Day 04 我们用条件边 + 循环把 Agent Loop 编排成了一张可执行的图，但这张图还活在内存里——进程一重启，对话历史、中间状态、执行到哪一步全部蒸发；更别提遇到"删除路线"这种危险操作，Agent 一路冲到底没人拦得住。今天给图装上两个生产级特性：**Checkpointer 持久化**（每个节点执行后自动给状态存档，重启/中断后能从断点恢复）和 **human-in-the-loop 的 interrupt**（在节点内暂停执行，等人确认后再用 `Command(resume=...)` 恢复）。这两个能力是手写 Agent Loop 永远做不到的——因为它们依赖"图执行引擎"对状态的可观测、可存档、可恢复的掌控。学完今天你的 Agent 才算从"能跑的玩具"走向"敢上生产的工具"。

学完今天你能：
1. 说清楚 Checkpointer 的存档机制（每个节点执行后自动保存状态快照），并区分 `MemorySaver`（内存，重启丢失）与 `SqliteSaver`（SQLite，持久化）的适用场景，能默写 `compile(checkpointer=...)` + `config={"configurable": {"thread_id": ...}}` 的标准用法
2. 用同一个 `thread_id` 多次 `invoke` 实现多轮对话记忆，对比 Week 03 手动维护 `messages` 列表的痛苦，说清"状态存档 = 记忆"的本质
3. 用 `app.get_state(config)` 查看当前状态、用 `state.next` 定位卡在哪个节点、用 `app.update_state(config, values)` 手动改状态，把这套当成调试断点恢复的利器
4. 用 `interrupt()` 在危险操作前暂停图执行，等人工确认后用 `Command(resume=...)` 恢复，完成"删除路线前要人确认"的完整人机交互闭环

---

## 一、为什么需要持久化：重启即丢的 Agent

### 1.1 Week 03 / Day 04 的图都活在内存里

回忆 Week 03 的 `agent_loop.py` 和 Day 04 的 `react_agent_graph.py`，它们有一个共同的致命弱点：**所有状态都活在进程内存里**。`messages` 列表、工具调用结果、中间分类标签——全是内存变量。一旦发生下面任何一种情况，执行进度就彻底丢失：

| 场景 | 后果 |
|------|------|
| 进程重启 / 服务器重新部署 | 整个对话历史清零，用户得从头再说一遍 |
| 跑到一半抛异常崩溃 | 已经执行了几步的工具调用结果全没，没法续跑 |
| 长任务中途想暂停（比如要等人确认） | 内存里的状态没法"挂起"，只能要么跑完要么放弃 |
| 同一个用户开了多个会话 | 没有"会话隔离"，状态全混在一个 list 里 |

Week 03 我们靠手动把 `messages` 序列化存盘来缓解，但那是**侵入式的**——业务代码里到处塞 `json.dump`，而且只能存"最终结果"，存不了"执行到哪一步"这种过程状态。

### 1.2 无持久化 vs 有持久化

LangGraph 的 Checkpointer 把存档这件事从业务代码里彻底抽出来，下沉到执行引擎层：

| 维度 | 无持久化（Week 03 / Day 04） | 有持久化（Checkpointer） |
|------|----------------------------|------------------------|
| 存档时机 | 手动 `json.dump`，只能存最终结果 | 每个节点执行后**自动**存档中间状态 |
| 重启恢复 | ❌ 重启即丢，从头再来 | ✅ 用同一 `thread_id` 续跑，状态完整 |
| 多会话隔离 | ❌ 自己管 session_id，容易串 | ✅ `thread_id` 天然隔离，互不干扰 |
| 断点恢复 | ❌ 崩溃后无法续跑 | ✅ 从最近一次存档点恢复 |
| 人机交互挂起 | ❌ 内存状态没法"暂停等输入" | ✅ `interrupt` 挂起，状态留在检查点 |
| 业务侵入 | 高（到处塞存盘代码） | 零（`compile(checkpointer=...)` 一行） |

> **关键认知：** Checkpointer 存的不是"对话记录"，而是**图的完整状态快照（State Snapshot）**——包括 messages、业务字段、当前执行到哪个节点、下一步要往哪走。这意味着哪怕图执行到一半被杀掉，重启后引擎知道"上次停在 `respond` 节点之前，下一步该执行 `respond`"。

---

## 二、Checkpointer 机制：每个节点后自动存档

### 2.1 存档发生在哪

Checkpointer 的工作原理一句话：**图在每执行完一个节点、状态合并完成后，就把当前全状态写一份快照到检查点存储里。** 这个过程对业务代码完全透明——你照常 `add_node` / `add_edge` / `invoke`，存档是引擎自动做的。

```
节点执行 + 状态存档的时间线

START ──► [node_a 执行] ──► 合并 state ──► ✅ 存档快照 #1
                                    │
                                    ▼
        [node_b 执行] ──► 合并 state ──► ✅ 存档快照 #2
                                    │
                                    ▼
        [node_c 执行] ──► 合并 state ──► ✅ 存档快照 #3 ──► END

崩溃发生在 node_c 之后？重启时从快照 #3 恢复，知道下一步是 END。
```

### 2.2 MemorySaver vs SqliteSaver

LangGraph 提供多种 Checkpointer 实现，本周掌握两种就够：

| 维度 | MemorySaver | SqliteSaver |
|------|-------------|-------------|
| 导入 | `from langgraph.checkpoint.memory import MemorySaver` | `from langgraph.checkpoint.sqlite import SqliteSaver` |
| 存储 | 进程内存 | SQLite 文件（`checkpoints.sqlite`） |
| 重启后 | ❌ 丢失（内存清空） | ✅ 保留（落盘了） |
| 适用 | 开发调试、单次会话原型 | 生产、需要跨重启续跑 |
| 性能 | 最快（无 IO） | 略慢（有磁盘写） |
| 并发 | 单进程 | SQLite 文件锁，适合中小并发 |

经验法则：**开发阶段用 MemorySaver 图个快，上线前切 SqliteSaver（或 PostgresSaver）做真持久化**。切换只需改一行 checkpointer 实例，业务代码零改动。

### 2.3 compile(checkpointer=...) + thread_id 标准用法

```python
"""checkpointer 基础用法：编译时挂上 checkpointer，调用时带 thread_id"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from typing import Annotated, TypedDict


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]


def echo_node(state: ChatState) -> dict:
    """简单回显节点：把用户的话原样回一遍。"""
    last = state["messages"][-1].content
    return {"messages": [{"role": "assistant", "content": f"你说的是：{last}"}]}


# 1. 建图
graph = StateGraph(ChatState)
graph.add_node("echo", echo_node)
graph.add_edge(START, "echo")
graph.add_edge("echo", END)

# 2. 编译时挂上 checkpointer —— 这是今天的关键一行
checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)

# 3. 调用时必须带 config，里面塞 thread_id
#    thread_id = 会话标识，不同对话用不同 id，互不干扰
config = {"configurable": {"thread_id": "user-001"}}

result = app.invoke(
    {"messages": [{"role": "user", "content": "你好"}]},
    config=config,   # ← 带 checkpointer 调用，状态自动存档
)
print(result["messages"][-1]["content"])   # 你说的是：你好
```

> **关键认知：** `thread_id` 是 Checkpointer 的"会话主键"。引擎用 `(thread_id, checkpoint_id)` 给每个快照编址。同一个 `thread_id` 下的多次 `invoke` 共享同一份状态历史；换一个 `thread_id` 就是开了一个全新会话，互不干扰。可以把它理解成"聊天窗口的 session id"。

---

## 三、多轮对话记忆：同一 thread_id 多次 invoke

### 3.1 对比 Week 03 手动维护 messages

Week 03 做多轮对话，我们必须自己把上一轮的 messages 带进下一轮：

```python
# Week 03 的痛苦：手动维护 messages 列表
messages = [system_prompt, {"role": "user", "content": "第一轮问题"}]
messages.append(call_llm(messages))               # 手动加第一轮回复
messages.append({"role": "user", "content": "第二轮问题"})  # 手动加第二轮
messages.append(call_llm(messages))               # 手动加第二轮回复
# 想存盘？自己 json.dump。想恢复？自己 json.load 再拼回来。
# 多用户？自己管 session_id → messages 的映射字典。
```

这套手写方案能跑，但每加一个用户、每多一轮对话、每次重启，都要写一堆胶水代码，还容易把 session 串了。

### 3.2 Checkpointer 让"状态存档 = 记忆"

有了 Checkpointer，多轮对话变成"用同一个 `thread_id` 多次 `invoke`"——引擎会自动把上一轮的最终状态作为这一轮的起点，messages 自然就累积下来了：

```python
"""多轮对话：同一 thread_id 多次 invoke，历史自动保留"""
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from typing import Annotated, TypedDict


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]


model = init_chat_model("gpt-4o-mini", temperature=0)


def chat_node(state: ChatState) -> dict:
    """LLM 节点：把全部历史发给模型，回复追加到 messages。"""
    response = model.invoke(state["messages"])
    return {"messages": [response]}


graph = StateGraph(ChatState)
graph.add_node("chat", chat_node)
graph.add_edge(START, "chat")
graph.add_edge("chat", END)

app = graph.compile(checkpointer=MemorySaver())
config = {"configurable": {"thread_id": "conv-001"}}

# 第一轮：注意只传"本轮新消息"，历史由 checkpointer 从存档补回来
app.invoke(
    {"messages": [
        SystemMessage(content="你是一个简洁的徒步助手。"),
        HumanMessage(content="川西有哪些入门雪山？"),
    ]},
    config=config,
)

# 第二轮：只传本轮的新问题，引擎自动带上第一轮的全部历史
r2 = app.invoke(
    {"messages": [HumanMessage(content="那第一条路线需要什么装备？")]},
    config=config,   # 同一个 thread_id → 自动记得第一轮聊过什么
)
print(r2["messages"][-1].content)   # 模型能正确引用"第一条路线"

# 第三轮：换个 thread_id，开新会话，历史是空的
config_b = {"configurable": {"thread_id": "conv-002"}}
r3 = app.invoke(
    {"messages": [HumanMessage(content="那第一条路线需要什么装备？")]},
    config=config_b,
)
# r3 里模型不知道"第一条路线"指什么，因为 conv-002 是全新会话
```

| 维度 | Week 03 手动维护 | Checkpointer 自动记忆 |
|------|----------------|---------------------|
| 历史传递 | 每轮手动拼 messages | 同一 thread_id 自动带 |
| 多会话 | 自己管 session 字典 | thread_id 天然隔离 |
| 存盘恢复 | 自己 json.dump/load | 引擎自动存，重启续跑 |
| 业务侵入 | 高（到处是胶水） | 零（只改 config） |

> **关键认知：** 第二轮 `invoke` 时只传了"本轮新消息"，但模型回答时却能"记得"第一轮——这是因为引擎在执行 `chat_node` 前，先把存档里的历史 messages 合并进了当前状态。**记忆的本质就是状态存档**，这是 Checkpointer 送给多轮对话最大的礼物。

---

## 四、状态查看与修改：调试利器

### 4.1 get_state：看当前状态长什么样

Checkpointer 不光会存档，还允许你随时"偷看"当前状态。这是调试断点恢复的核心入口：

```python
"""get_state / next / update_state 三件套"""
# 接续第三节的 app 和 config（conv-001）

# 1. get_state：查看当前会话的完整状态快照
snapshot = app.get_state(config)
print(snapshot.values)        # 当前全状态 dict（含 messages、业务字段）
print(snapshot.next)          # 下一步要执行的节点元组，() 表示已结束
print(snapshot.config)        # 这份快照对应的 config
```

### 4.2 next 字段：定位"卡在哪"

`state.next` 是调试时最该盯的字段。它告诉你**图现在停在哪、下一步该走哪个节点**：

| `snapshot.next` 的值 | 含义 | 排查方向 |
|---------------------|------|---------|
| `()` 空元组 | 图已正常结束 | 没问题，看最终输出即可 |
| `("chat",)` | 停在 chat 节点之前，待执行 | 检查 chat 节点是否阻塞/抛异常 |
| `("tools",)` | 停在 tools 节点前 | 检查是不是 interrupt 挂起了，等人确认 |
| `("node_a", "node_b")` | 多个节点待执行 | 并行节点场景，检查是否都就绪 |

当 Agent "卡住不动"时，第一步永远是 `print(app.get_state(config).next)`——它直接告诉你卡在哪个节点。

### 4.3 update_state：手动改状态再续跑

`update_state` 允许你**绕过节点逻辑、直接改状态**，然后让图从新状态继续。这是人工干预的底牌：

```python
# 2. update_state：手动改状态（比如修正一个错误的中分类结果）
app.update_state(
    config,
    values={"messages": [HumanMessage(content="（人工修正）刚才那条忽略，改成问装备")]},
)
# 改完后 get_state 能看到新值，下次 invoke 会从新状态继续

# 3. 续跑：从修正后的状态继续执行
result = app.invoke(None, config=config)   # 传 None 表示"不追加新输入，接着跑"
print(result["messages"][-1].content)
```

| 操作 | API | 典型用途 |
|------|-----|---------|
| 查看状态 | `app.get_state(config)` | 调试时看 messages / 业务字段对不对 |
| 看下一步 | `snapshot.next` | 定位卡在哪个节点 |
| 改状态 | `app.update_state(config, values)` | 人工修正错误状态后续跑 |
| 续跑 | `app.invoke(None, config=config)` | 从断点/修正点继续执行 |

> **关键认知：** `get_state` / `update_state` 把"图执行"从黑盒变成了白盒。Week 03 手写循环时，你想看中间状态只能在循环体里塞 `print`；现在引擎把每一步状态都存档了，随时可查、可改、可续。这是"框架编排"相比"手写循环"在可观测性上的质的飞跃。

---

## 五、human-in-the-loop interrupt（重点）

### 5.1 为什么需要 interrupt

Agent 自主性越高，越要在"危险操作"前插一道人工闸门。典型场景：

- 删数据库、删路线、删用户——删了不可逆，必须人确认
- 发邮件、发短信、付款——对外有副作用，发错了收不回
- 调用花钱的 API（如付费模型、云函数）——成本敏感，要人点头

Week 03 手写循环要实现"执行前问人"，得自己写 `input()` 阻塞、自己处理恢复——既没法跨重启，也没法服务化（FastAPI 里不能 `input()` 阻塞）。LangGraph 的 `interrupt` 把这件事做成了引擎级能力：**节点内调用 `interrupt()`，图执行暂停，状态留在检查点；人确认后用 `Command(resume=...)` 恢复，图从中断处继续。**

### 5.2 interrupt + Command 的执行模型

```
用户 invoke
    │
    ▼
[node_a 执行] ──► [node_b 执行] ──► interrupt() 在这里暂停！
                                        │
                                        ▼
                              状态存档（停在 node_b 中间）
                              invoke 返回，next = ("node_b",)
                                        │
                          ┌─────────────┴──────────────┐
                          ▼                            ▼
                   人工看 get_state              人工确认 yes/no
                          │                            │
                          └────────────┬───────────────┘
                                       ▼
                  app.invoke(Command(resume="yes"), config)
                                       │
                                       ▼
                  interrupt() 返回 "yes"，node_b 继续往下执行
                                       │
                                       ▼
                                   [node_c] ──► END
```

### 5.3 完整示例：删除路线前要人确认

这是今天的核心产出 `persistent_agent.py` 的重点片段——一个"删除路线前要人确认"的完整闭环：

```python
"""persistent_agent.py — Checkpointer 持久化 + interrupt 人机交互"""
from typing import Annotated, TypedDict
from langgraph.checkpoint.sqlite import SqliteSaver   # 用 SQLite 做真持久化
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command


class RouteState(TypedDict):
    messages: Annotated[list, add_messages]
    route_to_delete: str          # 待删除的路线 id（覆盖式）
    deletion_result: str          # 删除结果（覆盖式）


# 模拟的路线数据库
ROUTES_DB = {"route_001": "四姑娘山大峰", "route_002": "贡嘎大环线"}


def parse_intent_node(state: RouteState) -> dict:
    """解析用户意图：从消息里提取要删的路线 id。"""
    last = state["messages"][-1].content
    # 简化：假设用户消息里直接含 route_xxx
    route_id = "route_001" if "大峰" in last else "route_002" if "贡嘎" in last else "route_001"
    return {"route_to_delete": route_id}


def delete_route_node(state: RouteState) -> dict:
    """删除路线节点：危险操作前用 interrupt 要人确认。"""
    route_id = state["route_to_delete"]

    # ✅ interrupt：图在这里暂停，把问题抛给调用方
    # 返回值是后续 Command(resume=...) 传入的内容
    approval = interrupt({
        "question": f"确认删除路线 {route_id}（{ROUTES_DB.get(route_id, '未知')}）？此操作不可逆！",
        "route_id": route_id,
    })

    if approval == "yes":
        name = ROUTES_DB.pop(route_id, None)
        result = f"已删除路线 {route_id}（{name}）"
    else:
        result = f"已取消删除路线 {route_id}"
    return {"deletion_result": result}


def report_node(state: RouteState) -> dict:
    """汇报节点：把删除结果告诉用户。"""
    return {"messages": [{"role": "assistant", "content": state["deletion_result"]}]}


# 建图：START → 解析意图 → 删除(含 interrupt) → 汇报 → END
graph = StateGraph(RouteState)
graph.add_node("parse_intent", parse_intent_node)
graph.add_node("delete_route", delete_route_node)
graph.add_node("report", report_node)
graph.add_edge(START, "parse_intent")
graph.add_edge("parse_intent", "delete_route")
graph.add_edge("delete_route", "report")
graph.add_edge("report", END)

# 用 SqliteSaver 做真持久化（重启不丢）
checkpointer = SqliteSaver.from_conn_string("checkpoints.sqlite")
app = graph.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "delete-001"}}

# 第一次 invoke：会停在 delete_route 节点的 interrupt 处
result = app.invoke(
    {"messages": [{"role": "user", "content": "帮我删掉贡嘎大环线"}]},
    config=config,
)
# 此时图被 interrupt 暂停，result 是暂停时的状态
# 检查 next，确认卡在 delete_route
print("当前 next:", app.get_state(config).next)   # ('delete_route',)

# 人工确认：用 Command(resume=...) 恢复执行
result = app.invoke(Command(resume="yes"), config=config)
print(result["messages"][-1]["content"])   # 已删除路线 route_002（贡嘎大环线）
```

### 5.4 interrupt 的三段式用法

把上面的流程抽象成通用模式，所有"危险操作要人确认"都套这个模板：

| 阶段 | 代码 | 发生了什么 |
|------|------|-----------|
| ① 中断 | `approval = interrupt({...})` | 图暂停，状态存档，`invoke` 返回，`next` 指向当前节点 |
| ② 确认 | 人工看 `get_state`，决定 yes/no | 人检查要删的东西对不对 |
| ③ 恢复 | `app.invoke(Command(resume="yes"), config)` | `interrupt()` 返回 `"yes"`，节点继续执行 |

> **关键认知：** `interrupt` 和 Week 03 手写 `input()` 的本质区别——`input()` 阻塞的是进程线程，没法跨重启、没法服务化；`interrupt` 暂停的是**图的执行**，状态留在检查点里，可以跨重启、跨进程恢复。这就是为什么说"人机交互是手写 Agent 永远做不到的"——它依赖引擎对执行状态的掌控。

---

## 六、动手实验

### 🟢 青铜级：MemorySaver 跑通多轮记忆

用 `MemorySaver` 编译一个单节点 chat 图，用同一个 `thread_id` 连续 `invoke` 三轮（第一轮"我叫小明"，第二轮"我叫什么"，第三轮"换个话题，今天天气如何"）。验证第二轮模型能答出"小明"，证明历史被自动保留。然后换个 `thread_id` 再问"我叫什么"，验证模型答不出——证明会话隔离生效。

### 🟡 白银级：get_state + update_state 人工干预

接青铜级的图。在第二轮 `invoke` 之后，用 `app.get_state(config)` 打印 `values` 和 `next`；接着用 `app.update_state(config, values={"messages": [HumanMessage(content="忽略上面，其实我叫小红")]})` 手动改状态，再用 `app.invoke(None, config=config)` 续跑，验证模型改口叫"小红"。理解"改状态再续跑"这条人工干预路径。

### 🔴 王者级：SqliteSaver + interrupt 跨重启恢复

把第五节的"删除路线"示例跑通，但分两个进程跑：进程 A `invoke` 到 `interrupt` 暂停后**直接退出进程**（模拟崩溃）；进程 B 重新启动，用同一个 `thread_id` 和同一个 sqlite 文件，先 `get_state` 确认状态还在，再 `invoke(Command(resume="yes"))` 恢复执行。验证：崩溃重启后，图能从中断点继续，路线被正确删除。这就是生产级断点恢复。

---

## 七、踩坑记录 🕳️

### 坑 1：忘记带 config，状态根本没存档

```python
# ❌ 编译时挂了 checkpointer，但 invoke 时没传 config
app = graph.compile(checkpointer=MemorySaver())
app.invoke({"messages": [...]})   # 没传 config！

# 后果：引擎拿不到 thread_id，要么报错要么状态不存档，多轮记忆失效
```

**解决：** 只要用了 checkpointer，每次 `invoke` / `stream` 都必须带 `config={"configurable": {"thread_id": "xxx"}}`。`thread_id` 是存档的主键，没它 checkpointer 不知道存给谁。

### 坑 2：thread_id 用了可变对象或忘了区分会话

```python
# ❌ 所有用户共用一个 thread_id，会话全串了
config = {"configurable": {"thread_id": "default"}}
app.invoke(user_a 的消息, config=config)
app.invoke(user_b 的消息, config=config)   # user_b 看到了 user_a 的历史！

# ✅ 每个会话/用户用唯一 thread_id
config_a = {"configurable": {"thread_id": f"session-{user_a_id}"}}
config_b = {"configurable": {"thread_id": f"session-{user_b_id}"}}
```

**症状：** 用户 A 发现 Agent"知道"了用户 B 的对话内容。十有八九是 thread_id 撞了。建议直接用业务实体 id（如 `session-{session_id}`）拼接，保证全局唯一。

### 坑 3：interrupt 恢复时又传了新输入

```python
# ❌ 恢复时既传了 Command(resume=...) 又传了新 messages
app.invoke(
    Command(resume="yes"),
    config=config,
    # 还想顺手加一条消息？不行！
)

# ✅ 恢复时只能传 Command(resume=...)，不能再塞新输入
app.invoke(Command(resume="yes"), config=config)
```

**解决：** `interrupt` 恢复和"追加新输入"是两种不同的 `invoke` 语义，不能混。想加新消息就先 `update_state` 改状态，再 `invoke(Command(resume=...))` 恢复。把两件事分开做。

### 坑 4：MemorySaver 上线，重启后用户"失忆"

```python
# 开发时用 MemorySaver 图快，没切就上线
checkpointer = MemorySaver()   # 内存！重启全丢
app = graph.compile(checkpointer=checkpointer)

# 上线后每次服务器重启，所有用户的对话历史清零，投诉雪崩
```

**解决：** 上线前必须换成持久化实现（`SqliteSaver` / `PostgresSaver`）。切换只改一行 checkpointer 实例，业务代码零改动。养成习惯：**开发用 Memory，上线前 grep 一遍 `MemorySaver` 确认都换掉了。**

### 坑 5：update_state 改了状态却没续跑

```python
# ❌ 以为 update_state 改完就自动往下跑了
app.update_state(config, values={"category": "技术"})
# 然后等半天没反应——图不会自己往下走

# ✅ update_state 只改状态，要续跑得显式 invoke(None, config)
app.update_state(config, values={"category": "技术"})
result = app.invoke(None, config=config)   # 传 None = 接着跑
```

**解决：** `update_state` 是"改状态"，`invoke` 才是"驱动执行"。改完状态必须显式 `invoke(None, config=config)` 才会从新状态继续。把"改"和"跑"分开记，就不会漏。

---

## 八、副线笔记：Claude Code 辅助调试断点恢复

### 8.1 Agent 卡住不动，先看 next 字段

今天最容易遇到的故障是"图跑着跑着不动了"——既没报错也没返回，或者 `invoke` 返回了但结果不对。这种"卡住"的排查，手写 Agent 时代只能靠在循环体里塞 `print` 猜，而 LangGraph 给了你一个直球入口：`app.get_state(config).next`。

```python
# Agent 卡住了？第一步永远是看 next
snapshot = app.get_state(config)
print("next:", snapshot.next)        # 卡在哪个节点
print("values:", snapshot.values)    # 当前状态长啥样
```

`next` 的值直接告诉你卡在哪：是停在某个节点前待执行，还是已经结束（空元组），还是被 `interrupt` 挂起了。这一个字段就能省掉大半的"通读代码脑补控制流"时间。

### 8.2 让 Claude Code 帮你分析状态快照

状态快照往往很大（messages 列表十几轮、业务字段一堆），人眼扫容易漏。这时候把快照丢给 Claude Code 让它帮你分析：

```
你（对 Claude Code 说）：
  我的 LangGraph Agent 卡住了，这是 get_state 的输出：
  next: ('delete_route',)
  values: {
    "messages": [...12 条...],
    "route_to_delete": "",          # ← 注意这里是空字符串
    "deletion_result": ""
  }
  delete_route 节点里我用了 state["route_to_delete"]，
  但它执行时报 KeyError 之外的异常。帮我分析状态哪里不对。

Claude Code（分析后）：
  问题在 route_to_delete 是空字符串。
  你的 parse_intent 节点应该给它赋值，但看 values 里它还是 ""，
  说明 parse_intent 的返回值没合并进去。
  可能原因：parse_intent 返回的 key 拼错了（比如写成了 route_id），
  和 State 里声明的 route_to_delete 对不上，reducer 当成无关字段丢了。
  建议：检查 parse_intent 的 return 字典的 key 是不是 "route_to_delete"。
```

Claude Code 擅长这种"对着状态快照做差异分析"——它能把 `values` 里的字段值和你的预期一一对照，找出哪个字段异常、哪个字段缺失，比人眼扫快得多。

### 8.3 配合 LangSmith trace 看全链路

`get_state` 只能看"当前这一刻"的状态，想看"从头到尾每一步状态怎么变的"，要上 LangSmith trace：

| 工具 | 看什么 | 适合 |
|------|--------|------|
| `get_state` | 当前状态快照、next 节点 | 卡住时定位现场 |
| `get_state_history` | 同一 thread 的历史快照序列 | 看状态怎么一步步演变的 |
| LangSmith trace | 每个节点的输入/输出/耗时/报错 | 全链路性能与异常排查 |

开启 LangSmith 只需设环境变量：

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=your_key
# 之后所有 app.invoke 自动上报 trace，去 LangSmith 网页看
```

### 8.4 一套调试断点恢复的标准流程

把今天的副线凝结成一个可复用的排查流程：

```
Agent 卡住 / 行为异常
        │
        ▼
① app.get_state(config).next   ← 定位卡在哪个节点
        │
        ├── next 非空且是预期节点 → 检查该节点逻辑 / 是否 interrupt 挂起
        ├── next 为空但结果不对   → 看 values 里哪个字段异常
        └── next 指向意外节点     → 检查条件边路由逻辑
        │
        ▼
② 把 values 丢给 Claude Code 做差异分析 ← 找异常字段
        │
        ▼
③ 必要时 update_state 修正状态，再 invoke(None) 续跑
        │
        ▼
④ 想看全链路 → 开 LangSmith trace，看每步输入输出
```

> **类比记忆：** Week 03 调试 Agent 像在黑屋子里摸象——只能靠 `print` 摸到局部；LangGraph + Claude Code 像打开了灯还配了 X 光——`get_state` 看现场、Claude Code 做诊断、LangSmith 看全链路。可观测性的提升，正是框架相比手写循环最实在的生产价值。

---

## 今日产出检查清单

- [ ] 能说清 Checkpointer 的存档机制（每节点后自动存快照），区分 `MemorySaver`（内存/重启丢）与 `SqliteSaver`（SQLite/持久）的适用场景
- [ ] 能默写 `compile(checkpointer=...)` + `config={"configurable": {"thread_id": ...}}` 标准用法，并解释 `thread_id` 作为会话主键的作用
- [ ] 用同一 `thread_id` 多次 `invoke` 跑通多轮对话记忆，对比 Week 03 手动维护 messages，说清"状态存档 = 记忆"
- [ ] 用 `get_state` 查看 `values` / `next`，用 `update_state` 手动改状态后 `invoke(None)` 续跑，跑通人工干预闭环
- [ ] `persistent_agent.py` 跑通"删除路线前要人确认"完整示例：`interrupt` 中断 → `get_state` 确认 → `Command(resume=...)` 恢复
- [ ] 能用 `get_state().next` + Claude Code 状态分析 + LangSmith trace 三件套定位"Agent 卡在哪"，复述断点恢复标准流程

---

> **下一课预告：Day 06 — 高级模式 + Claude Code 调试状态机**。今天我们让图能存档、能暂停、能恢复，但图本身还是"一条线走到底 + 单个 interrupt"。明天上高级模式：**子图**（把复杂图封装成单个节点复用）、**并行节点**（多条边指向同一节点同时执行）、**stream 流式输出**（边跑边吐 token）。副线正式让 Claude Code 上场——帮你把 Graph 结构可视化出来、定位卡死的节点、分析状态机流转。今天的 `get_state` 调试是热身，明天 Claude Code 才是调试状态机的主力。
