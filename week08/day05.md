# Day 05 — A2A / ACP 协议：Agent 间通信

## 学习目标

Day 01-04 我们花了四天在 MCP 和 Skills 上：Day 01-02 把 MCP Server 从 `@tool` 升级成跨进程标准协议，Day 03-04 搞清楚了 Skills 是可发现、可版本化的能力包。到现在你应该有一个清晰的认知——**MCP 解决的是"Agent 怎么连接外部世界"**，标准化了工具调用。

但今天我们要聊一个更"宏大"的问题：**Agent 和 Agent 之间怎么通信？**

回想 Week 07，我们学过多 Agent 协作的四大模式——Subagents、Handoffs、Skills、Router。但你有没有注意到一个隐含的前提？所有那些 Agent 都在**同一个框架内**。Subagents 是 LangGraph 主 Agent 调 LangGraph 子 Agent，Handoffs 是 LangGraph Agent A 把控制权交给 LangGraph Agent B。它们共享同一份 State，跑在同一个 Python 进程里，用同一种框架的 API。

那如果 Agent A 是用 LangGraph 写的，Agent B 是用 CrewAI 写的，它俩能直接对话吗？不能。如果 Agent A 跑在你的服务器上，Agent B 跑在另一家公司的服务器上，它俩能交接任务吗？也不能。这就是今天 **A2A（Agent2Agent）协议**要解决的问题——给不同框架、不同语言、不同机器上的 Agent 定一套"普通话"。

学完今天你能：

1. 理解 A2A（Agent2Agent）协议的核心概念：基于 JSON-RPC 2.0 的 Agent 间通信标准
2. 掌握 A2A 的四大核心抽象：AgentCard（能力声明）、Task（任务）、Message（消息）、Artifact（产物）
3. 能区分 A2A 和 Week 07 Handoffs 的本质：标准协议 vs 框架内交接
4. 了解 ACP（Agent Client Protocol）：Agent 与宿主应用的通信协议

---

## 一、为什么需要 A2A：从框架内到跨框架

### 1.1 回顾 Week 07 的多 Agent

Week 07 我们学了多 Agent 协作的四大模式，回顾一下其中两个和"Agent 间通信"最相关的：

- **Subagents**：主 Agent 把子 Agent 当 tool 调用，主 Agent 始终在场，集中控制。Day 02 写过"主 Agent + 路线专家 + 天气专家"。
- **Handoffs**：Agent 间通过修改共享 State 的 `current_agent` 字段交接控制权，用户直接和当前接管的 Agent 对话。Day 03 写过"售前 → 技术 → 售后"的接力流程。

这两种模式都有一个共同的前提：**所有 Agent 都在同一个框架内**。

```
Week 07 的世界：所有 Agent 都在 LangGraph 框架内

┌─────────────────── LangGraph 框架 ───────────────────┐
│                                                       │
│   主Agent ←─State共享─→ 子AgentA（路线）              │
│      │                                                   │
│      └──State共享──→ 子AgentB（天气）                  │
│                                                       │
│   Handoffs：AgentA ──改current_agent──→ AgentB        │
│   都读写同一份 State，都在同一个 Python 进程           │
└───────────────────────────────────────────────────────┘
```

这种"框架内通信"的好处是简单——共享 State、函数调用、零网络开销。但代价是**锁死在同一个框架里**。

### 1.2 痛点：不同框架的 Agent 无法通信

现在想象一个真实的企业场景：

- 你的公司用 **LangGraph** 写了一个"路线规划 Agent"
- 合作伙伴用 **CrewAI** 写了一个"天气预报 Agent"
- 另一个部门用 **AutoGen** 写了一个"装备清单 Agent"

你想让路线 Agent 调用天气 Agent 查天气，能做到吗？做不到。因为：

1. **数据格式不同**：LangGraph 用 State 字典传数据，CrewAI 用自己的数据结构，AutoGen 又是另一套。它们没有共同的数据格式。
2. **调用方式不同**：LangGraph 是函数调用，CrewAI 是任务编排，AutoGen 是消息传递。它们没有共同的调用协议。
3. **发现机制缺失**：LangGraph 的 Agent 不知道 CrewAI 的 Agent 存在，也没有地方去"查"对方能干什么。

```
现实世界的痛点：Agent 孤岛

  LangGraph Agent          CrewAI Agent          AutoGen Agent
  ┌──────────┐            ┌──────────┐          ┌──────────┐
  │ 路线规划  │  ✗ 无法    │ 天气预报  │  ✗ 无法  │ 装备清单  │
  │ Agent    │  通信      │ Agent    │  通信    │ Agent    │
  └──────────┘            └──────────┘          └──────────┘
       ↑                       ↑                     ↑
   各说各的方言              各说各的方言           各说各的方言
```

每个框架都是一种"方言"，Agent 之间没法对话。这就像 Week 06 的 `@tool` 只能在同进程用一样——Week 08 Day 01 用 MCP 解决了"工具的跨进程标准化"问题，现在我们需要一个类似的方案解决"Agent 的跨框架标准化"问题。

### 1.3 A2A 的解决方案：标准化 Agent 间通信协议

A2A（Agent2Agent Protocol）就是干这个的。Google 在 2025 年 4 月联合 50 多家企业推出了这套开放协议，目标是让不同框架、不同语言、不同机器上的 Agent 能互相发现、互相通信、互相协作。

A2A 的核心选择是**基于 JSON-RPC 2.0**。JSON-RPC 2.0 是一个成熟的、语言无关的远程调用协议——你发一个 JSON 请求，收一个 JSON 响应，任何语言都能实现。A2A 在 JSON-RPC 之上定义了 Agent 间通信的语义：怎么发现对方、怎么提交任务、怎么传消息、怎么拿结果。

> **前端工程师的类比：** 你可以把 A2A 想成 Agent 世界的 HTTP API。就像前端不关心后端用 Java 还是 Python，只要遵守 HTTP 协议就能调接口；A2A 让 Agent 不关心对方用 LangGraph 还是 CrewAI，只要遵守 A2A 协议就能协作。

### 1.4 类比：MCP 是工具的标准协议，A2A 是 Agent 的标准协议

Day 01 我们学过一个类比：MCP 把 `@tool` 从"同进程函数调用"升级成"跨进程标准协议"。A2A 做的是同样的事，只不过对象从"工具"变成了"Agent"：

| 对比 | Week 06 @tool | Week 08 Day 01 MCP | Week 07 Handoffs | Week 08 Day 05 A2A |
|------|-------------|-------------------|-----------------|-------------------|
| 连接对象 | 工具（函数） | 工具（跨进程） | Agent（同框架） | Agent（跨框架） |
| 通信范围 | 同进程 | 跨进程 | 同框架内 | 跨框架、跨语言、跨机器 |
| 协议 | Python 函数调用 | JSON-RPC 2.0 | LangGraph State | JSON-RPC 2.0 |

一句话：**MCP 是工具的标准协议，A2A 是 Agent 的标准协议**。两者都用 JSON-RPC 2.0，但标准化的对象不同。

### 1.5 ASCII 图对比：Handoffs vs A2A

把 Week 07 的 Handoffs 和今天的 A2A 放一起对比，差异一目了然：

```
Week 07 Handoffs:                  A2A:

AgentA → [状态交接] → AgentB        AgentA → [JSON-RPC] → AgentB
                                      → [JSON-RPC] → AgentC
同一个 LangGraph 框架内              不同框架、不同语言、不同机器
共享同一份 State                     通过 HTTP 传 JSON 消息
改 current_agent 字段               提交 Task，等待状态轮询
```

关键差异：Handoffs 是"改一个共享字段"就完成交接，因为它在同一个进程里；A2A 是"通过网络发 JSON-RPC 请求"来完成通信，因为 Agent 可能在地球两端。

---

## 二、A2A 核心概念详解

A2A 协议定义了几个核心概念（Entity），理解了它们就理解了 A2A 的通信模型。最重要的是四个：**AgentCard、Task、Message、Artifact**。

### 2.1 AgentCard（能力声明）

A2A 的第一个核心概念是 AgentCard。每个 A2A Agent 对外暴露一张"名片"，声明自己是谁、能干什么、在哪找到我。

这跟 MCP 有没有似曾相识的感觉？Day 01 学过 MCP Server 启动时会通过 `tools/list` 暴露自己有哪些工具。A2A 的 AgentCard 也干类似的事，但它更丰富——不光声明"能干什么"（skills），还声明"在哪"（url）、"支持什么能力"（capabilities，比如支不支持流式输出、支不支持推送）。

```python
# A2A 的 AgentCard 结构（Pydantic Model）
class AgentCard(BaseModel):
    name: str                           # Agent 名称
    description: str                    # Agent 描述
    version: str                        # 版本号
    url: str                            # Agent 的访问 URL（HTTP 端点）
    protocolVersion: str = "0.2.5"     # A2A 协议版本
    skills: list[AgentSkill]           # 技能列表（Agent 擅长什么）
    capabilities: AgentCapabilities     # 能力声明（流式输出？推送？）

class AgentSkill(BaseModel):
    id: str; name: str; description: str
    tags: list[str] = []; examples: list[str] = []

class AgentCapabilities(BaseModel):
    streaming: bool = False             # 是否支持流式输出（SSE）
    pushNotifications: bool = False    # 是否支持推送通知
```

AgentCard 通常挂在一个约定好的路径上：`/.well-known/agent.json`。任何想找这个 Agent 的人，只要访问这个 URL 就能拿到名片，知道对方能干什么。这就像 MCP 的 `tools/list`，但它是"Agent 级别"的发现机制。

```
发现流程：Client GET /.well-known/agent.json → 拿到 AgentCard（url + skills）
         → 知道这个 Agent 会查天气，下一步发 Task
```

> **前端类比：** AgentCard 就像一个 npm 包的 `package.json`——你不用安装它、不用看源码，只要读 `package.json` 就知道这个包叫什么、版本多少、能干什么、依赖什么。AgentCard 是 Agent 的"对外 README"。

### 2.2 Task（任务）生命周期

A2A 的核心交互单位是 **Task**，不是直接的消息交换。这和 Week 07 的 Handoffs 有本质区别——Handoffs 是直接交接控制权（改一个字段就完事），A2A 是"提交一个任务，等对方处理完，拿回结果"。

Task 有一个明确的状态机：

```
Task 状态机：

         submitted（已提交）
              │
              ▼
         working（处理中）──────────► canceled（已取消）
              │
       ┌──────┼──────┐
       ▼      ▼      ▼
  completed  input  failed
  （完成）   _required（失败）
            （需要更多输入）
```

逐个状态解释：

- **submitted**：Client 提交了 Task，Server Agent 收到了。
- **working**：Server Agent 正在处理这个 Task。
- **input_required**：Server Agent 处理到一半，发现需要 Client 提供更多信息才能继续。比如路线 Agent 问天气 Agent "查哪天的天气？"，天气 Agent 回"你没说日期，告诉我日期"。这时状态是 `input_required`，Client 补充信息后 Task 继续。
- **completed**：Task 完成，可以拿结果了。
- **failed**：Task 失败了，处理出错。
- **canceled**：Task 被取消。

这个状态机最重要的设计是 **input_required**——它让 A2A 支持多轮交互。不是所有任务都能一次搞定，Agent 可能需要追问。这比 MCP 的"调一次工具拿一个结果"灵活得多。

对比 Week 07 的 Handoffs：Handoffs 是直接交接控制权，AgentA 改了 `current_agent = "B"` 就退场了；A2A 是提交 Task 等完成，Client 提交 Task 后要轮询状态（或等推送），直到 Task 变成 `completed` 才拿结果。**Handoffs 是"接力赛交接棒"，A2A 是"发快递等签收"**。

### 2.3 Message 和 Part

Task 里传递的信息用 **Message** 表示。一条 Message 可以包含多个 **Part**，每个 Part 可以是文本、文件或结构化数据——这支持了多模态通信。

```python
class Message(BaseModel):
    messageId: str              # 消息唯一 ID
    role: str                   # "user"（来自 Client）或 "agent"（来自 Server Agent）
    parts: list[Part]           # 消息内容，可以是多个 Part
    taskId: str | None = None   # 所属 Task 的 ID

# Part 有三种类型
class TextPart(BaseModel):
    type: str = "text"          # 固定为 "text"
    text: str                   # 文本内容

class FilePart(BaseModel):
    type: str = "file"          # 固定为 "file"
    file: FileWithBytes | FileWithUri  # 文件内容（字节或 URL）

class DataPart(BaseModel):
    type: str = "data"          # 固定为 "data"
    data: dict                  # 结构化 JSON 数据
```

一个 Message 可以混合多种 Part。比如你提交一个"分析卫星云图判断天气"的 Task，Message 里可以同时有 TextPart（"帮我分析天气"）+ FilePart（卫星云图）+ DataPart（`{"location":"北京"}`）。

> **前端类比：** Message + Part 的设计很像 HTTP 的 multipart/form-data——一个请求体里可以塞文本字段、文件、JSON 数据。A2A 的 Message 是"Agent 间的 multipart 请求"。

### 2.4 Artifact（产物）

Task 完成后产出的结果用 **Artifact** 表示。Artifact 可以是文本、文件或结构化数据——和 Part 的类型一一对应。

```python
class Artifact(BaseModel):
    artifactId: str             # 产物唯一 ID
    name: str                   # 产物名称
    description: str | None      # 产物描述
    parts: list[Part]           # 产物内容（和 Message 一样用 Part）
```

比如天气 Agent 完成了一个"查北京明天天气"的 Task，产出的 Artifact 可能是一个 DataPart：`{"city": "北京", "temp": "32℃", "weather": "晴"}`。如果是路线 Agent，产出的可能是一个 TextPart（一段路线规划文字）加一个 FilePart（一张路线地图图片）。

把四个概念串起来看一次完整的 A2A 交互流程：

```
Client Agent                              Server Agent（天气Agent）
    │  1. GET /.well-known/agent.json          │
    │ ────────────────────────────────────────►│
    │ ◄── AgentCard（url + skills） ──────────│
    │                                          │
    │  2. tasks/send — Message: [TextPart]    │
    │ ────────────────────────────────────────►│  ← submitted → working
    │                                          │
    │  3. tasks/get（轮询）                    │
    │ ────────────────────────────────────────►│
    │ ◄── Task: completed + Artifact ─────────│  ← 返回 DataPart 结果
    │  4. 拿到结果，结束                       │
```

四个概念的分工：**AgentCard** 声明能力，**Task** 管理生命周期，**Message** 传递输入，**Artifact** 返回输出。这就是 A2A 通信的全部骨架。

---

## 三、A2A vs Week 07 Handoffs 对比

这是今天最重要的对比。很多初学者会觉得"A2A 不就是 Handoffs 吗？都是 Agent 间通信"。名字像，本质完全不同。搞清楚这个差异，是今天最核心的认知。

### 3.1 本质差异：标准协议 vs 框架内交接

Week 07 Day 03 学过 Handoffs 的核心：所有 Agent 共享同一份 LangGraph State，交接就是改 `current_agent` 字段。这整个机制**依赖 LangGraph 框架**——没有 StateGraph，没有共享 State，Handoffs 就不存在。

A2A 完全不同。A2A 不依赖任何框架，它是一套**开放标准协议**。Agent A 是 LangGraph 写的还是 CrewAI 写的，A2A 不关心——只要遵守 JSON-RPC 2.0 协议，就能通信。

### 3.2 详细对比表

| 维度 | Week 07 Handoffs | A2A |
|------|-----------------|-----|
| 通信范围 | 同框架内（LangGraph） | 跨框架、跨语言、跨机器 |
| 协议基础 | LangGraph State（Python 字典） | JSON-RPC 2.0（HTTP + JSON） |
| 交接内容 | 共享整个 State（messages + current_agent） | Task + Message（只传需要的） |
| 交互模型 | 控制权交接（接力赛） | 提交任务等完成（发快递） |
| 发现机制 | 无（代码里硬编码有哪些 Agent） | AgentCard（`/.well-known/agent.json`） |
| 适用场景 | 单框架多 Agent、同进程 | 跨组织多 Agent、跨框架 |
| 标准化 | 无（LangGraph 私有机制） | 开放标准（Google + 50+ 企业） |
| 状态管理 | 共享 State | Task 状态机（独立于框架） |
| 多轮交互 | 天然支持（共享 messages） | 通过 input_required 状态 |
| 性能 | 高（同进程函数调用） | 低（网络 HTTP 调用） |

### 3.3 用一个例子说清差异

同一个任务："路线 Agent 需要天气数据"。看看 Handoffs 和 A2A 分别怎么做。

**Week 07 Handoffs 的做法：**

```python
# Week 07 Handoffs：同一个 LangGraph 框架内，路线Agent 和 天气Agent 共享同一份 State
def route_agent(state):
    state["current_agent"] = "weather"  # 改字段，交接控制权，路线Agent退场
    return state

def weather_agent(state):
    city = state["messages"][-1]["content"]
    weather = get_weather(city)
    state["messages"].append({"role": "agent", "content": weather})
    state["current_agent"] = "route"  # 干完活，交回控制权
    return state
```

注意：这里路线 Agent 和天气 Agent **共享同一个 `state` 字典**，在同一个 Python 进程里，通过改字段完成交接。零网络开销，但**锁死在 LangGraph 里**。

**A2A 的做法：**

```python
# A2A：路线Agent 通过网络调用 天气Agent（两者可以在不同框架、不同机器上）
# 1. 发现能力
card = await client.get_agent_card("http://weather-agent:8000")  # 拿 AgentCard
# 2. 提交 Task
task = await client.send_task(url=card.url,
    message=Message(role="user", parts=[TextPart(text="查北京明天天气")]))
# 3. 轮询状态（submitted → working → completed）
while task.state in ("submitted", "working"):
    await asyncio.sleep(1)
    task = await client.get_task(task_id=task.id, url=card.url)
# 4. 拿 Artifact
weather_data = task.artifacts[0].parts[0].data  # {"city":"北京","temp":"32℃"}
```

注意：这里路线 Agent 和天气 Agent **不共享任何 State**，通过 HTTP + JSON-RPC 通信。有网络开销，但**完全解耦**——天气 Agent 可以是 CrewAI 写的、跑在另一台服务器上。

> **面试金句：** Handoffs 是"同一个框架内的控制权交接"，A2A 是"跨框架的标准化任务通信"。Handoffs 像接力赛交接棒（同一个赛道），A2A 像发快递（可以跨城市）。

### 3.4 什么时候用哪个

不是 A2A 一定比 Handoffs 好——它们解决不同层面的问题：

```
选型决策：

你的多 Agent 系统是？
│
├─ 同一个框架、同一个进程
│   └─► 用 Week 07 的 Handoffs / Subagents
│       理由：零网络开销，共享 State，简单高效
│
├─ 跨框架、跨语言、跨组织
│   └─► 用 A2A
│       理由：标准化协议，Agent 可以来自不同团队
│
└─ 混合：框架内用 Handoffs，对外用 A2A
    └─► 最常见的真实架构
        理由：内部协作要快（Handoffs），对外通信要标准（A2A）
```

真实的系统往往是混合的：你内部用 LangGraph 的 Subagents/Handoffs 做快速协作，同时把某些 Agent 通过 A2A 暴露出去，让外部系统的 Agent 能调用。

---

## 四、ACP（Agent Client Protocol）

前面三节都在讲 A2A——Agent 和 Agent 之间的通信。但 Agent 生态里还有一个协议需要知道：**ACP（Agent Client Protocol）**，它解决的是 Agent 和宿主应用之间的通信。

### 4.1 ACP 是什么

ACP（Agent Client Protocol）是 Zed 编辑器推出的一套通用智能体协议。它解决的核心问题是：**把 Agent 的核心功能（服务端）和用户界面（客户端）解耦**。

什么意思？想象你在用 Zed 编辑器写代码，你想用一个 AI Agent 帮你编程。传统做法是编辑器自己内置一个 Agent（比如 Cursor 内置自己的 AI）。但这样的话，你就被锁死在 Cursor 的 Agent 上了——想换 Claude Code？换不了，因为接口不兼容。

ACP 的做法是定义一套标准协议，让"编辑器（客户端）"和"Agent（服务端）"通过协议通信。这样你可以在 Zed 编辑器里自由切换不同的 Agent 后端——今天用 Claude Code，明天用 Codex，后天用别的，编辑器界面不用变，因为它们都说 ACP 这门"语言"。

```
ACP 的定位：解耦 Agent 服务端和客户端

传统方式（锁定）：               ACP 方式（解耦）：

┌─────────────────┐            ┌──────────┐  ACP   ┌──────────────┐
│  Cursor 编辑器   │            │  Zed     │◄──────►│ Claude Code  │
│  + 内置 Agent    │            │  编辑器   │  协议   │  Agent       │
│  （锁死，不能换） │            │ (客户端)  │        │ (服务端)     │
└─────────────────┘            └──────────┘        └──────────────┘
                                    │ ACP                 │
                                    ▼                     ▼
                               ┌──────────┐  ACP   ┌──────────────┐
                               │  可换成  │◄──────►│  Codex       │
                               │  Codex   │  协议   │  Agent       │
                               └──────────┘        └──────────────┘
```

### 4.2 三个协议的定位：MCP / A2A / ACP

现在你已经学了三个协议，把它们放在一张图里看定位：

```
Agent 生态的三层协议：

                    ┌─────────────────┐
                    │   宿主应用       │
                    │  (Zed/VSCode)   │
                    └────────┬────────┘
                             │ ACP
                             │ （Agent ↔ 宿主应用）
                    ┌────────▼────────┐
                    │     Agent       │
                    │  (Claude Code)  │
                    └───┬────────┬────┘
                        │        │
                   A2A  │        │ MCP
              （Agent↔Agent）  （Agent ↔ 工具）
                        │        │
               ┌────────▼──┐  ┌──▼──────────┐
               │ 其他Agent  │  │ MCP Server   │
               │(CrewAI等)  │  │ (数据库/API) │
               └───────────┘  └─────────────┘
```

三层协议各管一段：

- **ACP（Agent ↔ 宿主应用）**：让编辑器/IDE 能连接不同的 Agent 后端，解耦 UI 和 Agent 内核。Zed 通过 ACP 集成了 Claude Code，你在 Zed 里用 Claude Code 时，界面是 Zed 的，Agent 内核是 Claude Code 的。
- **A2A（Agent ↔ Agent）**：让不同框架的 Agent 互相通信、协作。今天的主角。
- **MCP（Agent ↔ 工具）**：让 Agent 连接外部工具/资源。Day 01-02 学的。

### 4.3 三个协议对比表

| 维度 | MCP | A2A | ACP |
|------|-----|-----|-----|
| 连接对象 | Agent ↔ 工具 | Agent ↔ Agent | Agent ↔ 宿主应用 |
| 解决什么 | 标准化工具调用 | 标准化 Agent 间通信 | 解耦 Agent 内核与 UI |
| 协议基础 | JSON-RPC 2.0 | JSON-RPC 2.0 | JSON-RPC 2.0 |
| 推动方 | Anthropic | Google | Zed |
| 典型场景 | Agent 连接数据库/API | LangGraph Agent 调 CrewAI Agent | Zed 编辑器连接 Claude Code |
| Week 几学的 | Week 08 Day 01-02 | Week 08 Day 05（今天） | Week 08 Day 05（今天） |

注意一个共同点：**三个协议都基于 JSON-RPC 2.0**。这不是巧合——JSON-RPC 2.0 是语言无关、传输无关的成熟标准，用它做底层传输是最稳妥的选择。这也意味着你学了 MCP 的 JSON-RPC 调用方式，理解 A2A 和 ACP 会非常快。

> **一句话记忆：** MCP 连接工具（手），A2A 连接 Agent（同事），ACP 连接宿主应用（工位）。三个协议不冲突，可以同时用——一个 Agent 通过 ACP 连到编辑器，通过 A2A 跟其他 Agent 协作，通过 MCP 调用外部工具。

---

## 动手实验

### 🟢 青铜：安装 a2a-python SDK，查看 AgentCard 数据结构

安装 Google 官方的 A2A Python SDK，打印出一个 AgentCard 的完整结构。

```bash
pip install a2a-python
```

```python
# bronze_explore.py — 探索 A2A SDK 的数据结构
from a2a.types import AgentCard, AgentSkill, AgentCapabilities

# 构造一个最小的 AgentCard
card = AgentCard(
    name="天气查询Agent",
    description="查询任意城市的天气预报",
    version="1.0.0",
    url="http://localhost:8000",
    protocolVersion="0.2.5",
    skills=[AgentSkill(id="weather_query", name="天气查询",
                       description="根据城市名查询天气", tags=["weather"])],
    capabilities=AgentCapabilities(streaming=False, pushNotifications=False),
)
print(f"名称: {card.name} | URL: {card.url} | 协议版本: {card.protocolVersion}")
for skill in card.skills:
    print(f"  技能: {skill.name} — {skill.description}")
```

做完后运行，观察 AgentCard 的完整字段结构。

### 🟡 白银：完成 a2a_demo.py — 创建两个 A2A Agent，互相发送 Task

写一个最小可运行的 A2A demo：一个"客户端 Agent"向一个"服务端 Agent"发送 Task，服务端处理完返回 Artifact。

```python
# a2a_demo.py — 创建两个 A2A Agent，互相发送 Task（day01-07.md 列的 Day 05 产出物）
import asyncio

# === 服务端 Agent：天气查询 ===
# 1. 定义 AgentCard（声明能力）
# 2. 定义处理函数（收到 Task 后查天气）
# 3. 启动 HTTP 服务（暴露 /.well-known/agent.json + tasks/send + tasks/get）

# === 客户端 Agent ===
# 1. GET 服务端的 /.well-known/agent.json → 获取 AgentCard
# 2. 构造 Message（TextPart: "查北京天气"）
# 3. POST tasks/send → 提交 Task，拿 Task ID
# 4. 循环 GET tasks/get → 轮询状态（submitted → working → completed）
# 5. 状态变 completed 后，从 Artifact 取结果

async def main():
    print("A2A Demo - 两个 Agent 互相发送 Task")
    print("TODO: 参考 a2a-python 官方示例完成实现")
    # 官方仓库: https://github.com/a2aproject/A2A

if __name__ == "__main__":
    asyncio.run(main())
```

把文件放到 `e:\workspace\project\myAIAgentLearning\week08\day05\a2a_demo.py`。

> **提示：** A2A SDK 还在快速迭代，API 可能和上面伪代码有出入。以官方仓库的 examples 为准。重点理解"提交 Task → 轮询状态 → 拿 Artifact"这个流程。

### 🔴 王者：对比同一任务用 Week 07 Handoffs 和 A2A 实现的差异

选一个任务（比如"路线 Agent 调天气 Agent 查天气"），分别用 Week 07 Handoffs 和 A2A 实现，写一份对比文档 `handoffs_vs_a2a.md`。

要求：
1. 两种实现各写一个最小可运行示例
2. 从通信方式、状态管理、代码复杂度、性能四个维度对比
3. 画出两种方式的 ASCII 流程图
4. 给出"什么时候用 Handoffs，什么时候用 A2A"的选型建议

把文档放到 `e:\workspace\project\myAIAgentLearning\week08\day05\handoffs_vs_a2a.md`。

---

## 踩坑记录 🕳️

### 坑 1：A2A SDK 还在快速迭代，API 可能变化

A2A 是 2025 年才推出的协议，SDK 还在快速演进。你今天照着文档写的代码，下周可能就跑不了——因为 API 改了名字、改了参数、甚至改了整个调用方式。

**问题：** 照着博客教程写代码，结果 import 报错或方法名对不上。

**解决：** 以官方仓库（`github.com/a2aproject/A2A`）的最新 examples 为准，不要完全依赖第三方教程。写代码前先看官方示例的 import 路径和调用方式。

### 坑 2：A2A 的 Task 是异步的，需要轮询状态

很多人第一次用 A2A，以为提交 Task 后会同步等到结果——就像调一个普通函数。实际上 A2A 的 Task 是异步的：你提交后拿到一个 Task ID，然后要**轮询** `tasks/get` 接口直到状态变成 `completed`。

**问题：** 提交 Task 后直接读 `task.artifacts`，结果为空——因为 Task 还在 `working` 状态。

**解决：** 写一个轮询循环，每隔 1-2 秒查一次状态，直到 `completed` / `failed` / `input_required`。如果 Agent 支持推送（`pushNotifications: true`），也可以用推送代替轮询。

```python
# 正确做法：轮询 Task 状态
while task.state in ("submitted", "working"):
    await asyncio.sleep(1)
    task = await client.get_task(task_id=task.id, url=card.url)

if task.state == "completed":
    artifact = task.artifacts[0]  # 现在才有结果
```

### 坑 3：A2A 和 MCP 容易混淆

最常见的基础概念混淆。有人把 A2A 理解成"Agent 版的 MCP"，然后就觉得"那我直接用 MCP 不就行了"。不行——MCP 连接的是**工具**（函数级别的接口），A2A 连接的是**Agent**（有状态、有推理能力的智能体）。

**区别：** MCP 的 `tools/call` 是"调一个函数，拿一个返回值"，同步的、无状态的。A2A 的 `tasks/send` 是"提交一个任务，Agent 可能要推理好几步，可能要追问，最后返回产物"，异步的、有状态的。

**解决：** 记住一句话——**MCP 连接工具，A2A 连接 Agent**。工具是"扳手"（调一次拿一个结果），Agent 是"同事"（交代任务，他自己想办法完成）。

### 坑 4：A2A 的安全认证比较复杂

A2A 支持多种认证方式：OAuth2、API Key、HTTP Basic Auth。初学者第一次跑 demo 往往跳过认证（用 HTTP 不用 HTTPS），但在生产环境里这是大坑——你的 Agent 暴露在公网上，没有认证就是裸奔。

**问题：** 本地 demo 能跑，部署到服务器后报 401 Unauthorized。

**解决：** 开发阶段可以先用 API Key（最简单），生产环境建议用 OAuth2。A2A SDK 对认证有封装，但配置项较多，需要仔细看文档。

### 坑 5：混淆 ACP 和 A2A

有人看到 ACP 和 A2A 都带"A"和"Protocol"，以为是一个东西。不是——A2A 是 Agent 和 Agent 之间的协议，ACP 是 Agent 和宿主应用（编辑器/IDE）之间的协议。

**解决：** 记住三层定位：**ACP 连宿主，A2A 连同事，MCP 连工具**。三个不冲突，可以同时存在。

---

## 副线笔记

### 对比 A2A 和 OpenAI 的 Swarm 框架

Week 07 副线提到过 OpenAI 的 Swarm 框架（一个轻量级多 Agent 框架）。Swarm 也有"handoff"的概念——Agent A 可以把控制权交给 Agent B。但 Swarm 的 handoff 和 A2A 有本质区别：

| 维度 | Swarm handoff | A2A |
|------|--------------|-----|
| 范围 | 框架内（Swarm 内部） | 跨框架 |
| 机制 | Agent 返回一个 `handoff` 指令 | JSON-RPC 任务提交 |
| 标准化 | 无（Swarm 私有） | 开放标准 |

Swarm 的 handoff 本质上和 Week 07 的 LangGraph Handoffs 是一回事——都是"框架内的控制权交接"。A2A 才是真正解决"跨框架协作"的方案。

### 2026 年的趋势：A2A 标准化

2026 年 Agent 生态的趋势是 **A2A 标准化**，让不同框架的 Agent 能互操作。你可以观察到几个信号：

1. Google 联合 50+ 企业推 A2A，包括 Salesforce、SAP、Atlassian 等企业级厂商
2. LangChain、CrewAI 等框架开始内置 A2A 支持
3. A2A 和 MCP 被视为"互补"关系——MCP 管工具，A2A 管 Agent

> **思考题：** 如果未来所有 Agent 都支持 A2A，那 LangGraph 的 Handoffs 还有存在意义吗？提示：想想"同进程函数调用"和"HTTP API"的关系——HTTP 出现后，函数调用并没有消失，它们解决不同层面的问题。

> **补充：** 搜索 Agent 协议时你可能还会看到 ANP（Agent Network Protocol），它偏向"一群 Agent 组成去中心化网络"。和 A2A 的区别是：A2A 偏向"两个 Agent 之间通信"，ANP 偏向"Agent 网络"。今天先不深入，知道有这个概念就行。

---

## 检查清单

- [ ] 理解 A2A 的核心概念——基于 JSON-RPC 2.0 的 Agent 间通信标准协议
- [ ] 掌握 A2A 四大核心抽象——AgentCard（能力声明）、Task（任务+状态机）、Message（多 Part 消息）、Artifact（产物）
- [ ] 能区分 A2A 和 Week 07 Handoffs——标准协议 vs 框架内交接，跨框架 vs 同框架
- [ ] 理解 Task 的状态机——submitted → working → completed / input_required / failed / canceled
- [ ] 知道 MCP / A2A / ACP 三个协议的定位——MCP 连工具、A2A 连 Agent、ACP 连宿主应用
- [ ] 理解三个协议都基于 JSON-RPC 2.0，学了 MCP 的底层就理解了 A2A 和 ACP 的底层
- [ ] 完成了 a2a_demo.py——两个 A2A Agent 互相发送 Task 的最小示例

---

## 下课预告

> **Day 06 — MCP 客户端开发：工具发现与动态加载。** 今天我们从 Week 07 的"框架内 Agent 通信"扩展到了"跨框架 Agent 通信"（A2A）和"Agent ↔ 宿主应用通信"（ACP）。明天我们回到 MCP，但这次不是写 Server（Day 02 做过了），而是写 **Client**——一个能连接 MCP Server、自动发现工具列表、动态加载工具的客户端。你会理解 Claude Code 内部是怎么发现 MCP Server 暴露的工具、怎么把它们注入 Agent 的可用工具列表里的。这是 Day 07 综合项目的最后一块拼图。
