# Day 05 — 持久化：Checkpointer / Store / interrupt

## 学习目标

Day 04 我们用条件边 + 循环把 Agent 编排成了一张可执行的图，但这张图还活在内存里——进程一重启，对话历史、中间状态全部蒸发；更别提"删除路线"这种危险操作，Agent 一路冲到底没人拦得住；再进一步，每个用户的知识（偏好、已保存路线）只活在当前会话，换个 thread 就不认人。今天给图装上生产级的三件套：**Checkpointer 短时记忆**（每个节点后自动存档状态，重启/中断后能从断点恢复）、**Store 长期记忆**（跨会话持久读取/写入用户数据，同一个 store 多 thread 共享）、**interrupt 人机交互**（在节点内暂停执行，等人确认后再用 `Command(resume=...)` 恢复）。这三者加起来，你的 Agent 才算从"一次性的对话脚本"走向"有状态、可恢复、知人识面"的生产级应用。

学完今天你能：
1. 说清楚 LangGraph 持久化的两个层次——Checkpointer（短时/会话级）和 Store（长期/跨会话级），并默写对比表（作用域/生命周期/访问方式/使用场景）
2. 用 `InMemorySaver` 挂载 Checkpointer，用 `thread_id` 标识会话，通过同一 thread 多次 `invoke` 实现多轮对话记忆，对比 Week 03 手动维护 `messages` 列表的差异
3. 用 `InMemoryStore` 创建跨会话长期记忆，在 tool 内通过 `runtime.store.get/put` 读写持久化数据，验证同一 store 下不同 thread 共享用户信息
4. 用 `interrupt(payload)` 在危险操作前暂停图执行，用 `Command(resume=value)` 恢复，完成"删除路线前要人确认"的完整人机交互闭环；会用 `agent.get_state(config)` 查看状态/定位断点，用 `agent.update_state(config, values)` 手动修正状态

---

## 一、为什么需要持久化：重启即丢的 Agent

### 1.1 Week 03 / Day 04 的图都活在内存里

回忆 Week 03 的 `agent_loop.py` 和 Day 04 的 `react_agent_graph.py`，它们有一个共同的致命弱点：**所有状态都活在进程内存里**。`messages` 列表、工具调用结果、中间分类标签——全是内存变量。一旦发生下面任何一种情况，执行进度就彻底丢失：

| 场景 | 后果 |
|------|------|
| 进程重启 / 服务器重新部署 | 整个对话历史清零，用户得从头再说一遍 |
| 跑到一半抛异常崩溃 | 已经执行了几步的工具调用结果全没，没法续跑 |
| 长任务中途想暂停（如要等人确认） | 内存里的状态没法"挂起"，只能要么跑完要么放弃 |
| 同一用户开了多个会话 | 没有"会话隔离"，状态全混在一个 list 里 |
| 想跨会话记住用户偏好 | 每次都是陌生人，没有"长期记忆" |

Week 03 我们靠手动把 `messages` 序列化存盘来缓解，但那是**侵入式的**——业务代码里到处塞 `json.dump`，而且只能存"最终结果"，存不了"执行到哪一步"这种过程状态，更不用说"跨会话共享记忆"了。

### 1.2 LangGraph 持久化的两个层次

LangGraph 把持久化拆成了**两个正交的层次**，各自解决不同的问题：

| 维度 | Checkpointer（短时记忆） | Store（长期记忆） |
|------|------------------------|-----------------|
| **存储内容** | 图的完整状态快照（messages、节点状态、next 指针） | 应用级结构化数据（用户偏好、学识、配置） |
| **作用域** | 会话级（一个 thread_id 一套快照链） | 跨会话（同一 store 下所有 thread 可见） |
| **生命周期** | 会话结束可丢弃（或保留用于时间旅行） | 持久保留，应用生命周期 |
| **访问方式** | 引擎自动读/写，开发者无须手动操作 | 通过 tool 内的 `runtime.store` 手动 get/put |
| **核心 API** | `compile(checkpointer=...)` + `thread_id` | `InMemoryStore()` + `compile(store=store)` |
| **类比** | Web 应用的 Session 存储器 | 应用数据库 |
| **重启后** | 用 MemorySaver 会丢，用 SqliteSaver/PostgresSaver 不丢 | 用 InMemoryStore 会丢，用持久化 Store 实现不丢 |
| **使用场景** | 多轮对话记忆、中断恢复、时间旅行 | 用户偏好、已保存路线、知识图谱 |

> **关键认知：** Checkpointer 存的是"图执行的足迹"（方便续跑和回溯），Store 存的是"业务需要的持久数据"（用户偏好、学识记忆）。两者互补，不重叠。同一个应用往往两个都用——Checkpointer 负责让对话能接上，Store 负责让 Agent 记住用户的长期偏好。

### 1.3 无持久化 vs 有持久化（全貌）

| 维度 | 无持久化（Week 03 / Day 04） | 有 Checkpointer | 有 Checkpointer + Store |
|------|----------------------------|----------------|----------------------|
| 存档时机 | 手动 `json.dump`，只能存最终结果 | 每个节点后**自动**存档中间状态 | 同上 + 手动持久化业务数据 |
| 重启恢复 | 重启即丢 | 同一 thread_id 可续跑 | 恢复后还能从 Store 读取用户数据 |
| 多会话隔离 | 自己管 session_id | thread_id 天然隔离 | 隔离 + 共享 Store 中的公共数据 |
| 断点恢复 | 崩溃后无法续跑 | 从最近检查点恢复 | 恢复后 Store 数据仍在 |
| 人机交互 | 没法暂停 | interrupt 挂起，状态存档 | 中断时 Store 数据也可读 |
| 业务侵入 | 高（到处塞存盘代码） | 零（`compile(checkpointer=...)` 一行） | 极低（tool 内通过 runtime.store 访问） |

---

## 二、Checkpointer 基础：短时记忆

### 2.1 Checkpointer 的存档机制

Checkpointer 的工作原理一句话：**图在每执行完一个节点、状态合并完成后，就把当前全状态写一份快照到检查点存储里。** 这个过程对业务代码完全透明——你照常 `add_node` / `add_edge` / `invoke`，存档是引擎自动做的。

```
节点执行 + 状态存档的时间线

START ──► [node_a 执行] ──► 合并 state ──► 存档快照 #1
                                    │
                                    ▼
        [node_b 执行] ──► 合并 state ──► 存档快照 #2
                                    │
                                    ▼
        [node_c 执行] ──► 合并 state ──► 存档快照 #3 ──► END

崩溃发生在 node_c 之后？重启时从快照 #3 恢复，知道下一步是 END。
```

### 2.2 InMemorySaver vs 生产方案

| 维度 | InMemorySaver（开发用） | SqliteSaver / PostgresSaver（生产用） |
|------|------------------------|--------------------------------------|
| 导入路径 | `from langgraph.checkpoint.memory import InMemorySaver` | `from langgraph.checkpoint.sqlite import SqliteSaver`（依具体实现） |
| 存储 | 进程内存 | SQLite 文件 / PostgreSQL 表 |
| 重启后 | 丢失（内存清空） | 保留（落盘/落库） |
| 适用 | 开发调试、单次会话原型 | 生产、需要跨重启续跑 |
| 性能 | 最快（无 IO） | 略慢（有磁盘/网络 IO） |
| 并发 | 单进程 | SQLite 有文件锁，Postgres 支持高并发 |

> **注意：** `MemorySaver` 已在 2026 年更名为 `InMemorySaver`，`from langgraph.checkpoint.memory import MemorySaver` 已废弃。如果遇到 ImportError，请改用上面的新名。

### 2.3 Checkpointer 基础用法：create_agent 模式

2026 年起推荐用 `create_agent` 构造带 Checkpointer 的 Agent，比手动拼 StateGraph 更简洁：

```python
"""checkpointer_basic.py — Checkpointer 基础用法：create_agent + InMemorySaver"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver


# 1. 创建模型
model = init_chat_model("gpt-4o-mini", temperature=0)

# 2. 创建 Checkpointer 实例
checkpointer = InMemorySaver()

# 3. 编译 Agent 时传入 checkpointer
agent = create_agent(
    model,
    tools=[],                          # 暂无工具，后续再加
    checkpointer=InMemorySaver(),      # 直接传实例
)

# 4. 定义 thread_id = 会话标识
config = {"configurable": {"thread_id": "session-001"}}

# 5. 第一次 invoke
result = agent.invoke(
    {"messages": [{"role": "user", "content": "你好，我叫小明"}]},
    config=config,
)
print(result["messages"][-1].content)

# 6. 第二次 invoke（同一 thread_id，自动记忆上下文）
result = agent.invoke(
    {"messages": [{"role": "user", "content": "我叫什么名字？"}]},
    config=config,      # 同一 thread_id → Checkpointer 自动带历史
)
print(result["messages"][-1].content)   # 应该答出"小明"
```

> **关键认知：** `thread_id` 是 Checkpointer 的"会话主键"。引擎用 `(thread_id, checkpoint_id)` 给每个快照编址。同一个 `thread_id` 下的多次 `invoke` 共享同一份状态历史；换一个 `thread_id` 就是开了一个全新会话，互不干扰。可以把它理解成"聊天窗口的 session id"。

### 2.4 多轮对话记忆：同一 thread_id 多次 invoke

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

有了 Checkpointer，多轮对话变成"用同一个 `thread_id` 多次 `invoke`"——引擎会自动把上一轮的最终状态作为这一轮的起点：

```python
"""多轮对话 demo：同 thread_id 多次 invoke，历史自动保留"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver


model = init_chat_model("gpt-4o-mini", temperature=0)
agent = create_agent(model, tools=[], checkpointer=InMemorySaver())

config = {"configurable": {"thread_id": "conv-001"}}

# 第一轮：只传"本轮新消息"，历史由 checkpointer 从存档补回来
agent.invoke(
    {"messages": [
        {"role": "system", "content": "你是一个简洁的徒步助手。"},
        {"role": "user", "content": "川西有哪些入门雪山？"},
    ]},
    config=config,
)

# 第二轮：只传本轮的新问题，引擎自动带上第一轮的全部历史
r2 = agent.invoke(
    {"messages": [{"role": "user", "content": "那第一条路线需要什么装备？"}]},
    config=config,   # 同一个 thread_id → 自动记得第一轮聊过什么
)
print(r2["messages"][-1].content)   # 模型能正确引用"第一条路线"

# 第三轮：换个 thread_id，开新会话，历史是空的
config_b = {"configurable": {"thread_id": "conv-002"}}
r3 = agent.invoke(
    {"messages": [{"role": "user", "content": "那第一条路线需要什么装备？"}]},
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

> **关键认知：** 第二轮 `invoke` 时只传了"本轮新消息"，但模型回答时却能"记得"第一轮——这是因为引擎在执行节点前，先把存档里的历史 messages 合并进了当前状态。**会话记忆的本质就是状态存档**，这是 Checkpointer 送给多轮对话最大的礼物。

---

## 三、Store 长期记忆（重点——新概念）

### 3.1 为什么需要 Store

Checkpointer 解决了"会话内能延续"的问题，但有一个局限：**它的作用域是 thread 级别的**。同一个 thread 的历史可以累积，但换了 thread（即使还是同一个用户），Checkpointer 里存的 messages 就访问不到了。

但很多场景需要**跨会话的长期记忆**：
- 用户在 thread A 设置了"我偏好难度适中的徒步路线"，在 thread B 里 Agent 应该记得这个偏好
- 用户保存了一条路线到"我的收藏"，下次任何会话都能读到
- 系统需要累积用户的学识水平，跨多天跟踪进步

这就是 Store 的用武之地。Store 是一个**键值存储引擎**，独立于 Checkpointer 存在，所有 thread 共享同一份数据。

### 3.2 InMemoryStore 的基本操作

```python
"""store_basic.py — InMemoryStore 跨会话长期记忆"""
from langgraph.store.memory import InMemoryStore


# 1. 创建 Store（开发阶段用 InMemoryStore，生产可换持久化后端）
store = InMemoryStore()

# 2. 写数据：store.put(namespace, key, value)
#    namespace 是元组，用于逻辑分组，如 ("users",)
#    key 是字符串标识符
#    value 是任意可 JSON 序列化的 dict
store.put(("users",), "user_123", {"name": "小明", "preference": "中等难度"})

# 3. 读数据：store.get(namespace, key)
item = store.get(("users",), "user_123")
print(item.value)   # {"name": "小明", "preference": "中等难度"}

# 4. 搜索：store.search(namespace, filters)
#    返回同一 namespace 下匹配 filter 的条目
results = store.search(("users",), filter={"preference": "中等难度"})
for item in results:
    print(item.key, item.value)
```

Store 的数据结构非常直观：

| 概念 | 说明 | 示例 |
|------|------|------|
| namespace | 逻辑分组，元组形式，类似文件夹 | `("users",)`、`("users", "preferences")` |
| key | 条目唯一标识，字符串 | `"user_123"`、`"route_456"` |
| value | 存储的值，可 JSON 序列化的 dict | `{"name": "小明", "level": "中级"}` |
| get | 精确读取 | `store.get(("users",), "user_123")` |
| put | 写入/更新 | `store.put(("users",), "user_123", {...})` |
| search | 按 namespace + filter 搜索 | `store.search(("users",), filter={"level": "中级"})` |

### 3.3 在 create_agent 中挂载 Store

Store 需要和 Checkpointer 一起传入 `create_agent`，两者相辅相成：

```python
"""agent_with_store.py — create_agent 同时挂载 Checkpointer + Store"""
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore


model = init_chat_model("gpt-4o-mini", temperature=0)

# 创建 Checkpointer（短时记忆）
checkpointer = InMemorySaver()

# 创建 Store（长期记忆）
store = InMemoryStore()

# 编译 Agent，同时传入 checkpointer 和 store
agent = create_agent(
    model,
    tools=[],                # 工具稍后加上
    checkpointer=checkpointer,
    store=store,             # ← Store 参数
)
```

> **注意：** `store` 必须和 `checkpointer` 同时传入才能正常工作。Store 不依赖 Checkpointer 的 thread 隔离——它是全局共享的，所有 thread 读写同一份数据。

### 3.4 在 tool 内通过 runtime.store 读写 Store

挂载了 Store 之后，tool 函数可以通过 `runtime.store` 访问 Store。这是最关键的模式：

```python
"""tool 内使用 runtime.store 的完整示例"""
from langchain.agents import create_agent, tool
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore


# 1. 定义一个 tool，通过 runtime.store 读写用户偏好
@tool
def save_user_preference(runtime, preference: str) -> str:
    """
    保存用户对徒步路线的偏好（难度、类型等）。

    runtime.store 由 LangGraph 引擎自动注入。
    该数据跨会话持久，其他 thread 也能读到。
    """
    # 从 config 中获取用户标识（实际项目从 token 解析）
    user_id = runtime.config.get("configurable", {}).get("user_id", "anonymous")

    # 读取已有偏好
    existing = runtime.store.get(("users",), user_id)
    prefs = existing.value if existing else {}

    # 更新偏好
    prefs["preference"] = preference
    runtime.store.put(("users",), user_id, prefs)

    return f"已保存偏好：{preference}"


@tool
def get_user_preference(runtime) -> str:
    """
    读取用户保存的徒步偏好。

    注意：这个 tool 可以在完全不同的 thread 中调用，
    但只要 store 是同一个实例，数据就能读到。
    """
    user_id = runtime.config.get("configurable", {}).get("user_id", "anonymous")
    existing = runtime.store.get(("users",), user_id)
    if existing:
        return f"你的偏好：{existing.value.get('preference', '未设置')}"
    return "还未设置偏好"


# 2. 编译 Agent
model = init_chat_model("gpt-4o-mini", temperature=0)
agent = create_agent(
    model,
    tools=[save_user_preference, get_user_preference],
    checkpointer=InMemorySaver(),
    store=InMemoryStore(),
)

# 3. 线程 A：用户设置偏好
config_a = {"configurable": {"thread_id": "thread-a", "user_id": "user_123"}}
agent.invoke(
    {"messages": [{"role": "user", "content": "我喜欢中等难度的徒步路线"}]},
    config=config_a,
)

# 4. 线程 B：同一用户换了个会话，Agent 还记得偏好
config_b = {"configurable": {"thread_id": "thread-b", "user_id": "user_123"}}
result = agent.invoke(
    {"messages": [{"role": "user", "content": "帮我看看我的偏好是什么"}]},
    config=config_b,   # 不同 thread_id，但同一 store → 数据共享
)
print(result["messages"][-1].content)   # 应该答出"中等难度"
```

> **关键认知：** `runtime.store` 的注入是 LangGraph 引擎自动完成的。你不需要手动传递 store 实例到 tool 里。只要在 `create_agent` 时传入 `store=...`，所有 tool 函数就能通过 `runtime.store` 访问。**Store 的跨 thread 共享**是它与 Checkpointer 最本质的区别——同一 store 实例下，thread A 写的数据 thread B 能读到。

### 3.5 Checkpointer 与 Store 的协作关系

```
                ┌─────────────────────────────────────────┐
                │           Agent Runtime                  │
                │                                          │
                │  ┌─────────────────┐  ┌──────────────┐  │
                │  │  Checkpointer   │  │    Store     │  │
                │  │  (短时,会话级)   │  │  (长期,全局)  │  │
                │  │                 │  │              │  │
                │  │  thread_a 存档   │  │  ("users",   │  │
                │  │  thread_b 存档   │  │   user_123)  │  │
                │  │  thread_c 存档   │  │  ("routes",  │  │
                │  │                 │  │   route_456) │  │
                │  └─────────────────┘  └──────────────┘  │
                │                                          │
                └──────────────────────────────────────────┘
                           ▲           ▲
                           │           │
                ┌──────────┴───────────┴──────────┐
                │          Thread A               │
                │  get_state → 读取 thread 快照    │
                │  runtime.store → 读取全局数据    │
                └─────────────────────────────────┘
```

| 维度 | Checkpointer | Store |
|------|-------------|-------|
| 作用域 | 单 thread（会话级） | 全局（跨会话） |
| 读写方式 | 引擎自动（对开发者透明） | 开发者手动（tool 内通过 runtime.store） |
| 典型数据 | messages、节点执行状态 | 用户偏好、配置、学识 |
| 生命周期 | 随会话创建/结束 | 随应用创建/销毁 |
| 依赖关系 | 独立 | 依赖 Checkpointer 提供 config 上下文 |

---

## 四、State 查看与修改：调试利器

### 4.1 get_state：看当前状态长什么样

Checkpointer 不光会存档，还允许你随时**偷看**当前状态。这是调试断点恢复的核心入口：

```python
"""get_state / update_state 调试三件套"""
# 接续上面 agent 和 config

# 1. get_state：查看当前会话的完整状态快照
snapshot = agent.get_state(config)
print(snapshot.values)        # 当前全状态 dict（含 messages、业务字段）
print(snapshot.next)          # 下一步要执行的节点元组，() 表示已结束
print(snapshot.config)        # 这份快照对应的 config
```

### 4.2 next 字段：定位"卡在哪"

`snapshot.next` 是调试时最该盯的字段。它告诉你**图现在停在哪、下一步该走哪个节点**：

| `snapshot.next` 的值 | 含义 | 排查方向 |
|---------------------|------|---------|
| `()` 空元组 | 图已正常结束 | 没问题，看最终输出即可 |
| `("chat",)` | 停在 chat 节点之前，待执行 | 检查 chat 节点是否阻塞/抛异常 |
| `("tools",)` | 停在 tools 节点前 | 检查是不是 interrupt 挂起了，等人确认 |
| `("node_a", "node_b")` | 多个节点待执行 | 并行节点场景，检查是否都就绪 |

当 Agent "卡住不动"时，第一步永远是 `print(agent.get_state(config).next)`——它直接告诉你卡在哪个节点。

### 4.3 update_state：手动改状态再续跑

`update_state` 允许你**绕过节点逻辑、直接改状态**，然后让图从新状态继续。这是人工干预的底牌：

```python
# 2. update_state：手动改状态（比如修正一个错误）
agent.update_state(
    config,
    values={"messages": [{"role": "user", "content": "（人工修正）刚才那条忽略，改成问装备"}]},
)
# 改完后 get_state 能看到新值

# 3. 续跑：从修正后的状态继续执行
result = agent.invoke(None, config=config)   # 传 None = 不追加新输入，接着跑
print(result["messages"][-1].content)
```

| 操作 | API | 典型用途 |
|------|-----|---------|
| 查看状态 | `agent.get_state(config)` | 调试时看 messages / 业务字段对不对 |
| 看下一步 | `snapshot.next` | 定位卡在哪个节点 |
| 改状态 | `agent.update_state(config, values)` | 人工修正错误状态后续跑 |
| 续跑 | `agent.invoke(None, config=config)` | 从断点/修正点继续执行 |

> **关键认知：** `get_state` / `update_state` 把"图执行"从黑盒变成了白盒。Week 03 手写循环时，你想看中间状态只能在循环体里塞 `print`；现在引擎把每一步状态都存档了，随时可查、可改、可续。这是"框架编排"相比"手写循环"在可观测性上的质的飞跃。

---

## 五、interrupt 人机交互（重点）

### 5.1 为什么需要 interrupt

Agent 自主性越高，越要在"危险操作"前插一道人工闸门。典型场景：

- 删数据库、删路线、删用户——删了不可逆，必须人确认
- 发邮件、发短信、付款——对外有副作用，发错了收不回
- 调用花钱的 API（如付费模型、云函数）——成本敏感，要人点头

Week 03 手写循环要实现"执行前问人"，得自己写 `input()` 阻塞、自己处理恢复——既没法跨重启，也没法服务化（FastAPI 里不能 `input()` 阻塞）。LangGraph 的 `interrupt` 把这件事做成了引擎级能力：**节点或 tool 内调用 `interrupt()`，图执行暂停，状态留在检查点；人确认后用 `Command(resume=...)` 恢复，图从中断处继续。**

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
                  agent.invoke(Command(resume="yes"), config)
                                       │
                                       ▼
                  interrupt() 返回 "yes"，node_b 继续往下执行
                                       │
                                       ▼
                                   [node_c] ──► END
```

### 5.3 完整示例：发送邮件前 interrupt 等人确认

这是今天的核心产出 `persistent_agent.py` 的重点片段：

```python
"""persistent_agent.py — Checkpointer + Store + interrupt 完整示例"""
from typing import Annotated, TypedDict
from langchain.agents import create_agent, tool
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import interrupt, Command


# ─── 工具定义 ───

@tool
def send_confirmation_email(runtime, recipient: str, subject: str, body: str) -> str:
    """
    发送确认邮件。危险操作——发送前需人工确认。

    流程：interrupt(payload) 暂停 → 外部确认 → Command(resume=...) 恢复
    """
    # 1. 拼出要展示的 payload
    payload = {
        "action": "send_email",
        "recipient": recipient,
        "subject": subject,
        "body_preview": body[:100],
        "question": f"确认向 {recipient} 发送邮件「{subject}」？",
    }

    # 2. interrupt：图暂停，payload 返回给调用方
    #    恢复时 Command(resume=...) 的值作为 interrupt() 的返回值
    approval = interrupt(payload)

    # 3. 根据确认结果执行或取消
    if approval == "yes":
        # 这里调真实邮件服务
        return f"邮件已发送至 {recipient}，主题：{subject}"
    else:
        return f"已取消发送邮件至 {recipient}"


@tool
def get_user_email(runtime) -> str:
    """获取当前用户的邮箱地址。"""
    # 从 store 读取用户信息
    user_id = runtime.config.get("configurable", {}).get("user_id", "anonymous")
    item = runtime.store.get(("users",), user_id)
    if item and "email" in item.value:
        return item.value["email"]
    return "user@example.com"


# ─── 构建 Agent ───

model = init_chat_model("gpt-4o-mini", temperature=0)
agent = create_agent(
    model,
    tools=[send_confirmation_email, get_user_email],
    checkpointer=InMemorySaver(),
    store=InMemoryStore(),
)


# ─── 主流程：发邮件前 interrupt 等人确认 ───

config = {"configurable": {"thread_id": "email-001", "user_id": "user_123"}}

# 第一步：用户要求发邮件，Agent 调用 send_confirmation_email 触发 interrupt
try:
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "给 alice@example.com 发一封邮件，主题是周末徒步计划"}]},
        config=config,
    )
except Exception:
    # interrupt 导致 invoke 返回时可能以特殊形式退出
    pass

# 检查是否中断
snapshot = agent.get_state(config)
print("next:", snapshot.next)            # ('tools',) — 说明卡在 tools 节点
print("interrupted:", hasattr(snapshot, "interrupted") and snapshot.interrupted)

# 第二步：查看线程内挂起的 interrupt 负载
# 2026 年新版 stream_events 提供 stream.interrupts 读取 pending 中断
# 在 invoke 模式下，通过检查 state 来确认是否中断

# 第三步：人工确认，用 Command(resume=...) 恢复
result = agent.invoke(
    Command(resume="yes"),    # ← 关键：value "yes" 成为 interrupt() 的返回值
    config=config,
)
print(result["messages"][-1].content)   # 邮件已发送至 alice@example.com，...
```

### 5.4 stream_events 模式下的 interrupt 处理

2026 年新版推荐使用 `stream_events` 来处理 interrupt，它提供了更友好的属性访问：

```python
"""stream_events 模式下的 interrupt 处理"""
# 使用 stream_events 启动执行
stream = agent.stream_events(
    {"messages": [{"role": "user", "content": "给 bob@example.com 发邮件"}]},
    config,
    version="v3",           # 2026 年推荐版本
)

# 检查是否中断
if stream.interrupted:
    print("Agent 执行被中断")
    # 读取所有 pending 的 interrupt 负载
    for interrupt_payload in stream.interrupts:
        print("中断原因:", interrupt_payload)
    
    # stream.output 包含中断时的最终状态
    print("中断时状态:", stream.output)

# 恢复中断：传 Command(resume=...)
stream = agent.stream_events(
    Command(resume=True),    # resume=True 表示确认
    config,
    version="v3",
)
```

| stream_events 属性 | 类型 | 说明 |
|-------------------|------|------|
| `stream.output` | dict | 最终状态（中断或完成时） |
| `stream.interrupted` | bool | 是否被 interrupt 暂停 |
| `stream.interrupts` | list | 所有 pending 的 interrupt payload 列表 |
| `stream.messages` | list | LLM 消息流 |

### 5.5 interrupt 的三段式用法模板

| 阶段 | 代码 | 发生了什么 |
|------|------|-----------|
| ① 中断 | `approval = interrupt(payload)` | 图暂停，状态存档，`invoke` 返回，`next` 指向当前节点 |
| ② 确认 | 人工看 `get_state` 或 `stream.interrupts`，决定 yes/no | 人检查要执行的操作对不对 |
| ③ 恢复 | `agent.invoke(Command(resume="yes"), config)` | `interrupt()` 返回 `"yes"`，节点继续执行 |

> **关键认知：** `interrupt` 和 Week 03 手写 `input()` 的本质区别——`input()` 阻塞的是进程线程，没法跨重启、没法服务化；`interrupt` 暂停的是**图的执行**，状态留在检查点里，可以跨重启、跨进程恢复。这就是为什么说"人机交互是手写 Agent 永远做不到的"——它依赖引擎对执行状态的掌控。

---

## 六、动手实验

### 🟢 青铜级：InMemorySaver 跑通多轮记忆

用 `create_agent` 创建一个带 `InMemorySaver` 的 Agent（无 tools），用同一个 `thread_id` 连续 invoke 三轮：
1. 第一轮："你好，我叫小明"
2. 第二轮："我叫什么名字？"（验证模型能答出"小明"）
3. 换一个 thread_id 再问"我叫什么名字？"（验证新会话答不出）

**验证点：** 第二轮答出"小明"证明状态被自动存档和恢复；第三轮答不出证明 thread_id 隔离生效。

```bash
python -c "
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver

model = init_chat_model('gpt-4o-mini', temperature=0)
agent = create_agent(model, tools=[], checkpointer=InMemorySaver())

cfg = {'configurable': {'thread_id': 'bronze-test'}}
agent.invoke({'messages': [{'role': 'user', 'content': '你好，我叫小明'}]}, config=cfg)
r2 = agent.invoke({'messages': [{'role': 'user', 'content': '我叫什么名字？'}]}, config=cfg)
print('同一线程:', r2['messages'][-1].content)

cfg2 = {'configurable': {'thread_id': 'bronze-test-2'}}
r3 = agent.invoke({'messages': [{'role': 'user', 'content': '我叫什么名字？'}]}, config=cfg2)
print('新线程:', r3['messages'][-1].content)
"
```

### 🟡 白银级：Store 跨线程共享用户偏好

实现以下流程：
1. 创建带 Checkpointer + Store 的 Agent，定义两个 tool：`save_user_preference` 和 `get_user_preference`
2. 线程 A 保存偏好"中等难度"
3. 线程 B（不同 thread_id，同一 user_id）调用 `get_user_preference`，验证能读到"中等难度"
4. 线程 C（不同 user_id）调用 `get_user_preference`，验证返回"未设置"（不同用户隔离）

**验证点：** 理解 Store 的"跨 thread 共享 + 按 user_id 隔离"的设计——数据是全局的，但需要通过 key 做业务隔离。

### 🔴 王者级：完整持久化应用 + 中断恢复

综合今天全部知识点，完成一个完整的持久化 Agent：

1. **Store 层：** 初始化时给默认用户灌入两条路线偏好（"四姑娘山大峰"和"贡嘎大环线"）
2. **Agent 层：** 定义三个 tool：
   - `list_user_routes(runtime)` — 从 Store 读取用户已保存的路线列表
   - `delete_route(runtime, route_id: str)` — 删除路线，但 **发送前 interrupt** 等人确认
   - `save_route(runtime, route_name: str)` — 保存新路线到 Store
3. **中断恢复：** 请求删除时触发 interrupt，调用方检查 `agent.get_state(config).next` 确认卡在 `delete_route`，然后 `Command(resume="yes")` 恢复
4. **跨会话验证：** 同一个 user_id 换一个 thread_id，调用 `list_user_routes` 确认路线被删除或新增

**产出文件：** `persistent_agent.py`（参考第五节的完整示例）

---

## 七、踩坑记录 🕳️

### 坑 1：忘记带 config，状态根本没存档

```python
# ❌ 编译时挂了 checkpointer，但 invoke 时没传 config
agent = create_agent(model, tools=[], checkpointer=InMemorySaver())
agent.invoke({"messages": [...]})   # 没传 config！

# 后果：引擎拿不到 thread_id，要么报错要么状态不存档，多轮记忆失效
```

**解决：** 只要用了 checkpointer，每次 `invoke` / `stream` 都必须带 `config={"configurable": {"thread_id": "xxx"}}`。`thread_id` 是存档的主键，没它 checkpointer 不知道存给谁。

### 坑 2：thread_id 用了固定值，所有用户串会话

```python
# ❌ 所有用户共用一个 thread_id，会话全串了
config = {"configurable": {"thread_id": "default"}}
agent.invoke(user_a 的消息, config=config)
agent.invoke(user_b 的消息, config=config)   # user_b 看到了 user_a 的历史！

# ✅ 每个用户/会话用唯一 thread_id
config_a = {"configurable": {"thread_id": f"session-{user_a_id}"}}
config_b = {"configurable": {"thread_id": f"session-{user_b_id}"}}
```

**症状：** 用户 A 发现 Agent"知道"了用户 B 的对话内容。十有八九是 thread_id 撞了。建议直接拼接业务实体 id（如 `session-{session_id}-{user_id}`），保证全局唯一。

### 坑 3：interrupt 恢复时又传了新输入

```python
# ❌ 恢复时既传了 Command(resume=...) 又传了新 messages
agent.invoke(
    Command(resume="yes"),
    config=config,
    # 还想顺手加一条消息？不行！
)

# ✅ 恢复时只能传 Command(resume=...)，不能再塞新输入
agent.invoke(Command(resume="yes"), config=config)
```

**解决：** `interrupt` 恢复和"追加新输入"是两种不同的 `invoke` 语义，不能混。想加新消息就先 `update_state` 改状态，再 `invoke(Command(resume=...))` 恢复。把两件事分开做。

### 坑 4：InMemoryStore 上线后重启数据全丢

```python
# 开发时用 InMemoryStore 图方便，没切就上线
store = InMemoryStore()   # 内存！重启全丢
agent = create_agent(model, tools=tools, checkpointer=..., store=store)

# 上线后每次服务器重启，所有用户的偏好清零
```

**解决：** `InMemoryStore` 和 `InMemorySaver` 一样，仅供开发调试。上线前必须换成持久化 Store 实现（如基于 Redis 或 SQLite 的 Store 后端）。切换只改一行 store 实例化代码，业务零改动。养成习惯：**开发用 InMemory，上线前 grep 一遍 `InMemoryStore` 确认都换掉了。**

### 坑 5：`InMemorySaver` 和 `MemorySaver` 混用导致 ImportError

```python
# ❌ 旧版路径（2025 年），2026 年已废弃
from langgraph.checkpoint.memory import MemorySaver   # ImportError!

# ✅ 2026 年最新路径
from langgraph.checkpoint.memory import InMemorySaver

# 如果从旧项目迁移，全局替换 MemorySaver → InMemorySaver
```

**解决：** 2026 年官网确认 `MemorySaver` 已更名为 `InMemorySaver`。如果看到 `ModuleNotFoundError: No module named 'langgraph.checkpoint.memory.MemorySaver'`，检查 import 路径是否正确。同样的情况也适用于 `uuid7`——新位置是 `from langchain_core.utils.uuid import uuid7`。

---

## 八、副线笔记：Claude Code 辅助调试断点恢复

### 8.1 Agent 卡住不动，先看 next 字段

今天最容易遇到的故障是"图跑着跑着不动了"——既没报错也没返回，或者 `invoke` 返回了但结果不对。这种"卡住"的排查，手写 Agent 时代只能靠在循环体里塞 `print` 猜，而 LangGraph 给了你一个直球入口：`agent.get_state(config).next`。

```python
# Agent 卡住了？第一步永远是看 next
snapshot = agent.get_state(config)
print("next:", snapshot.next)        # 卡在哪个节点
print("values:", snapshot.values)    # 当前状态长啥样
```

`next` 的值直接告诉你卡在哪：是停在某个节点前待执行，还是已经结束（空元组），还是被 `interrupt` 挂起。这一个字段就能省掉大半的"通读代码脑补控制流"时间。

### 8.2 让 Claude Code 帮你分析状态快照

状态快照往往很大（messages 列表十几轮、业务字段一堆），人眼扫容易漏。这时候把快照丢给 Claude Code 让它帮你分析：

```
你（对 Claude Code 说）：
  我的 LangGraph Agent 卡住了，这是 get_state 的输出：
  next: ('tools',)
  values: {
    "messages": [...12 条...],
    "route_to_delete": "",          # ← 注意这里是空字符串
    "deletion_result": ""
  }
  delete_route 节点里我用了 state["route_to_delete"]，
  但它是空字符串。帮我分析状态哪里不对。

Claude Code（分析后）：
  问题在 route_to_delete 是空字符串。
  你的 parse_intent 节点应该给它赋值，但看 values 里它还是 ""，
  说明 parse_intent 的返回值没合并进去。
  可能原因：parse_intent 返回的 key 拼错了（比如写成了 route_id），
  和 State 里声明的 route_to_delete 对不上，reducer 当成无关字段丢了。
  建议：检查 parse_intent 的 return 字典的 key 是不是 "route_to_delete"。
```

Claude Code 擅长这种**对着状态快照做差异分析**——它能把 `values` 里的字段值和你的预期一一对照，找出哪个字段异常、哪个字段缺失，比人眼扫快得多。

### 8.3 配合 LangSmith trace 看全链路

`get_state` 只能看"当前这一刻"的状态，想看"从头到尾每一步状态怎么变的"，要上 LangSmith trace：

| 工具 | 看什么 | 适合 |
|------|--------|------|
| `get_state` | 当前状态快照、next 节点 | 卡住时定位现场 |
| `get_state_history` | 同一 thread 的历史快照序列 | 看状态怎么一步步演变的 |
| LangSmith trace | 每个节点的输入/输出/耗时/报错 | 全链路性能与异常排查 |

开启 LangSmith 只需设环境变量：

```bash
set LANGSMITH_TRACING=true
set LANGSMITH_API_KEY=your_key
# 之后所有 agent.invoke 自动上报 trace，去 LangSmith 网页看
```

### 8.4 一套调试断点恢复的标准流程

```
Agent 卡住 / 行为异常
        │
        ▼
① agent.get_state(config).next   ← 定位卡在哪个节点
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

- [ ] 能说清楚 LangGraph 持久化的两个层次（Checkpointer 短时/会话级 vs Store 长期/跨会话级），默写对比表（作用域/生命周期/访问方式/使用场景）
- [ ] 用 `create_agent(..., checkpointer=InMemorySaver())` + `config={"configurable": {"thread_id": "xxx"}}` 跑通多轮对话记忆，对比 Week 03 手动维护 messages 列表，理解"状态存档 = 记忆"
- [ ] 用 `InMemoryStore` 创建 Store，在 tool 内通过 `runtime.store.get/put` 读写跨会话持久数据，验证同一 store 下不同 thread 共享用户偏好
- [ ] 用 `agent.get_state(config)` 查看 `values` / `next`，用 `agent.update_state(config, values)` 手动改状态后 `agent.invoke(None)` 续跑，跑通人工干预闭环
- [ ] `persistent_agent.py` 跑通完整示例：Store 存用户路线 → interrupt 确认删除 → Command(resume=...) 恢复 → 跨 thread 验证持久化
- [ ] 能用 `agent.get_state().next` + Claude Code 状态分析 + LangSmith trace 三件套定位"Agent 卡在哪"，复述断点恢复标准流程

---

> **下一课预告：Day 06 — 高级模式：stream_events / 子图 / 中间件**。今天我们把图装上了持久化和人机交互，但图的拓扑还是一条线。明天上高级模式：**stream_events 流式输出**（边跑边吐 token 和中间结果）、**子图**（把复杂图封装成单个节点复用）、**中间件**（在节点前后插全局逻辑——日志、鉴权、限流）。同时把 Claude Code 调试进一步深化——让它帮你可视化图结构、分析状态机流转、自动生成调试脚本。
