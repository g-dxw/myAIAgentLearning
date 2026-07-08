# Day 06 — MCP 客户端 + 工具发现机制

## 学习目标

Day 01-02 我们站在 Server 的视角写了 MCP Server，暴露了 Tool / Resource / Prompt 三种能力，还接入了 Claude Code 验证。Day 03-04 我们学了 Skills——能力包文件，理解了 Skill 和 Tool/MCP/Prompt 的区别。Day 05 我们学了 A2A 协议——Agent 之间怎么通信。但有一个角色我们一直没亲手写过——**MCP Client**。前面我们写 Server、用 Claude Code 当 Host，但 Client 这个中间人一直是 SDK 自动管理的"黑盒"。今天我们要把这个黑盒打开，自己手写一个 MCP Client，连接 Day 02 的 hiking-route-server，亲眼看到"连接 → 发现 → 调用 → 返回"的完整链路。同时我们要搞清楚一个核心问题：Host（如 Claude Code）是怎么"知道"一个 Server 有哪些工具的？这就是工具发现机制。

学完今天你能：

1. 理解 MCP Client 的工作机制：连接 Server、发现工具、转发调用，说清 Client 在 Host 里的角色定位
2. 能用 MCP Python SDK 写一个 MCP Client，连接 Day 02 创建的 MCP Server，发现并调用它的工具
3. 理解工具发现的完整流程：list → 选择 → 调用 → 获取结果，以及动态发现相比静态注册的优势
4. 理解 Claude Code 作为 MCP Host 的集成原理：启动时如何连接多个 Server、汇总工具、处理冲突

---

## 一、MCP Client 的工作机制

### 1.1 回顾：Client 在 MCP 三角色里的位置

Day 01 我们讲过 MCP 的三大角色：Host、Client、Server。当时我们说 Client 是 Host 内部的组件，负责和单个 Server 通信，但它一直是个"黑盒"——你写 Server、你用 Claude Code 当 Host，中间的 Client 是 SDK 自动管理的。今天我们把这个黑盒拆开。

先用一张图回顾三者的关系，重点看 Client 的位置：

```
┌──────────────────────────────────────────────────┐
│              Host (Claude Code)                   │
│                                                   │
│   ┌─────────┐    ┌──────────┐   ┌──────────┐     │
│   │   LLM   │    │ Client A │   │ Client B │     │
│   │  (推理)  │    │          │   │          │     │
│   └─────────┘    └────┬─────┘   └────┬─────┘     │
│        │              │              │           │
│        └──────────────┴──────────────┘           │
│              工具描述汇总给 LLM                    │
└──────────────────────────┬───────────────┬────────┘
                           │               │
                     stdio  │        SSE   │
                           ▼               ▼
             ┌──────────────────┐  ┌──────────────────┐
             │  MCP Server A    │  │  MCP Server B    │
             │  (hiking-route)   │  │  (weather)       │
             └──────────────────┘  └──────────────────┘
```

Client 是夹在 LLM 和 Server 之间的"中间人"。它不做业务逻辑，它是个翻译官——把 Server 的工具描述翻译成 LLM 能理解的格式，把 LLM 的调用请求转发给 Server。

### 1.2 Client 的生命周期

一个 Client 从创建到销毁，要经历五个阶段。这是今天的核心知识点：

```
Client 生命周期
┌────────────────────────────────────────────────────────────┐
│                                                            │
│  1. 启动 → 连接 MCP Server                                  │
│     │   通过 stdio 启动 Server 子进程，或通过 SSE 连远程   │
│     │                                                      │
│  2. 发现 → 查询 Server 有哪些工具/资源/提示词              │
│     │   发 tools/list、resources/list、prompts/list        │
│     │                                                      │
│  3. 转发 → 把工具描述告诉 LLM                               │
│     │   Client 把工具的 JSON Schema 描述塞进 LLM 上下文    │
│     │                                                      │
│  4. 调用 → LLM 决定调用工具时，Client 转发请求给 Server     │
│     │   LLM 说"我要调 search_routes"，Client 发 tools/call │
│     │                                                      │
│  5. 返回 → Server 执行工具，结果通过 Client 返回给 LLM      │
│         Server 跑完函数，结果经 Client 传回 LLM            │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

这五个阶段是固定的顺序，缺一不可。你今天写 Client 代码时，会看到每一步对应一行代码。

### 1.3 Client 和 Server 的关系：一对一

这是一个容易忽略但很重要的点：**一个 Client 只连一个 Server**。

| 概念 | 数量关系 | 说明 |
|------|---------|------|
| Host : Client | 一对多 | 一个 Host（如 Claude Code）可以有多个 Client |
| Client : Server | 一对一 | 一个 Client 只连接一个 Server |
| Server : Client | 一对多 | 一个 Server 可以被多个 Client 同时连接 |

用前端工程师熟悉的话说：Client 就像一个 HTTP 连接实例——一个 `fetch` 请求对应一个连接。Host 要连三个 Server，就得创建三个 Client，每个 Client 独立和自己的 Server 通信。

```
Host
├── Client A ────► Server A (hiking-route)
├── Client B ────► Server B (weather)
└── Client C ────► Server C (github)

每个 Client 独立连接，互不干扰
```

> **关键理解：** Client 不是"一个全局管理器"，而是"一个专用连接器"。Day 02 你接入 Claude Code 时，Claude Code 内部就为你那个 hiking-route-server 创建了一个专属 Client。这个 Client 只负责和你的 Server 通信，不会去碰别的 Server。

---

## 二、手写 MCP Client

### 2.1 用 MCP Python SDK 写 Client

理论说完了，开始写代码。我们用 MCP Python SDK 的 Client API，连接 Day 02 创建的 `hiking-route-server`，完整走一遍"发现 → 调用 → 读取资源"的流程。

```python
"""mcp_client_demo.py — MCP Client 示例

连接 Day 02 的 hiking-route-server，发现并调用工具

运行方式：python mcp_client_demo.py
前提：Day 02 的 my_mcp_server.py 在同目录下
"""
import asyncio
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def main():
    # 1. 配置要连接的 MCP Server
    #    StdioServerParameters 告诉 Client：用 stdio 传输，启动命令是什么
    server_params = StdioServerParameters(
        command="python",
        args=["my_mcp_server.py"],
    )

    # 2. 连接 Server
    #    stdio_client 会启动 my_mcp_server.py 作为子进程
    #    返回 (read, write) 两个流，用于和 Server 通信
    async with stdio_client(server_params) as (read, write):
        # ClientSession 是 MCP 协议层，封装了 JSON-RPC 消息的编解码
        async with ClientSession(read, write) as session:
            # 3. 初始化连接（握手）
            #    这一步交换协议版本、能力声明等
            await session.initialize()

            # 4. 发现工具（对应生命周期第 2 步）
            print("=" * 50)
            print("发现工具 (tools/list)")
            print("=" * 50)
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description}")

            # 5. 调用工具（对应生命周期第 4-5 步）
            print("\n" + "=" * 50)
            print("调用工具: search_routes")
            print("=" * 50)
            result = await session.call_tool(
                "search_routes",
                arguments={"difficulty": "进阶", "days": 3},
            )
            print(f"  结果: {result.content[0].text}")

            # 6. 读取资源（Resource 也能通过 Client 发现和读取）
            print("\n" + "=" * 50)
            print("发现并读取资源")
            print("=" * 50)
            resources = await session.list_resources()
            for res in resources.resources:
                print(f"  资源 URI: {res.uri}")
                content = await session.read_resource(res.uri)
                print(f"  内容: {content}")


asyncio.run(main())
```

### 2.2 代码逐行解读

这段代码的每一部分都对应 Client 生命周期的一个阶段，我们逐段对照：

| 代码 | 生命周期阶段 | 做了什么 |
|------|-------------|---------|
| `StdioServerParameters(...)` | 准备 | 告诉 Client 怎么启动 Server |
| `stdio_client(server_params)` | 第 1 步：启动 | 拉起 Server 子进程，建立 stdio 通信 |
| `ClientSession(read, write)` | 第 1 步：连接 | 创建协议层会话，封装 JSON-RPC |
| `session.initialize()` | 第 1 步：握手 | 交换协议版本、能力声明 |
| `session.list_tools()` | 第 2 步：发现 | 发 tools/list，拿到工具列表 |
| （隐式）工具描述给 LLM | 第 3 步：转发 | 真实 Host 会把描述塞进 LLM 上下文 |
| `session.call_tool(...)` | 第 4-5 步：调用 | 发 tools/call，等结果返回 |
| `session.list_resources()` | 第 2 步：发现 | 发 resources/list，发现资源 |
| `session.read_resource(uri)` | 第 5 步：返回 | 发 resources/read，读资源内容 |

> **注意第 3 步的"隐式"：** 我们写的这个 Client 是"纯 Client"，没有接 LLM。所以第 3 步"把工具描述转发给 LLM"在我们的代码里是看不到的——因为没有 LLM。在真实的 Claude Code 里，Client 发现工具后会把 JSON Schema 描述塞进发给 Claude 的消息里，这一步是 Host 框架自动做的。我们今天的实验聚焦在"Client 怎么和 Server 通信"，LLM 那一端先不管。

### 2.3 运行结果预期

如果 Day 02 的 `my_mcp_server.py` 没问题，运行 `python mcp_client_demo.py` 后你会看到类似这样的输出：

```
==================================================
发现工具 (tools/list)
==================================================
  - search_routes: 搜索徒步路线。

==================================================
调用工具: search_routes
==================================================
  结果: 推荐进阶路线（3天）：['长穿毕3日', '四姑娘山二峰3日', '九顶山2日']

==================================================
发现并读取资源
==================================================
  资源 URI: route://config
  内容: 路线配置：
- 数据源：本地路线数据库
...
```

> **成就感时刻：** 到这一步，你已经从两边都写过了——Day 02 写了 Server，今天写了 Client。你完整掌握了 MCP 的通信两端。这就像你既会写后端 API，又会写前端 fetch 调用，两端都通透了。

### 2.4 和 Day 02 伪代码的对比

Day 02 的第三节我们其实写过一段"模拟 Client 发现工具"的伪代码（`client_discover_demo.py`）。今天的 `mcp_client_demo.py` 和它几乎一样，但有两个关键区别：

| 对比项 | Day 02 伪代码 | Day 06 完整版 |
|--------|--------------|--------------|
| 定位 | 概念演示，展示发现机制 | 真实可运行的 Client |
| 调用 LLM | 没有 | 没有（但白银实验会接上） |
| 错误处理 | 没有 | 后面踩坑记录会补 |
| 资源读取 | 只列了 URI | 真正调 read_resource 读内容 |

Day 02 那段是"告诉你原理"，今天这段是"你能跑起来的代码"。本质相同，但今天的是产出物。

---

## 三、工具发现机制深度解析

### 3.1 发现的完整流程

工具发现不是一个孤立的动作，而是一条完整的链路。从 Client 连上 Server 到 LLM 拿到工具结果，中间要经过五步：

```
Client                    Server                    Host(LLM)
  │                         │                         │
  │ ① tools/list 请求       │                         │
  │ ──────────────────────► │                         │
  │                         │                         │
  │ ② 返回工具 JSON Schema  │                         │
  │ ◄────────────────────── │                         │
  │                         │                         │
  │ ③ 转发工具描述给 LLM     │                         │
  │ ──────────────────────────────────────────────────►│
  │                         │                         │
  │                         │  ④ LLM 决定调用某工具    │
  │                         │ ◄────────────────────── │
  │                         │                         │
  │ ⑤ tools/call 请求       │                         │
  │ ──────────────────────► │                         │
  │                         │                         │
  │ ⑥ Server 执行工具       │                         │
  │    返回结果             │                         │
  │ ◄────────────────────── │                         │
  │                         │                         │
  │ ⑦ 结果转发给 LLM         │                         │
  │ ──────────────────────────────────────────────────►│
  │                         │                         │
  │                         │  ⑧ LLM 组织最终回答     │
```

这八步对应的是"一次完整工具调用"的全生命周期。其中 ①② 是发现，③ 是转发，④⑤⑥⑦ 是调用链路。

### 3.2 工具描述的格式：JSON Schema

第 ② 步 Server 返回的工具描述，不是一段自然语言，而是一个标准的 JSON Schema。这是 MCP 工具发现的核心数据结构。

```json
{
  "name": "search_routes",
  "description": "搜索徒步路线。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "difficulty": {
        "type": "string",
        "enum": ["休闲", "进阶", "硬核"]
      },
      "days": {
        "type": "integer"
      }
    },
    "required": ["difficulty"]
  }
}
```

三个字段的作用：

| 字段 | 作用 | 谁用 |
|------|------|------|
| `name` | 工具的唯一标识 | LLM 决定调用时引用这个名字 |
| `description` | 工具干什么用的 | LLM 看这段决定"要不要调这个工具" |
| `inputSchema` | 参数的 JSON Schema | LLM 决定调用时填什么参数 |

### 3.3 和 Week 06 @tool 的对比

Week 06 我们用 `@tool` 装饰器定义工具，它的"描述"是 Python 的 docstring，参数类型是 Python 的类型注解。MCP 的描述是 JSON Schema。两者对比：

| 维度 | Week 06 @tool | MCP |
|------|---------------|-----|
| 描述格式 | Python docstring | JSON Schema |
| 参数类型 | Python 类型注解 (`str`, `int`) | JSON Schema (`type: string`, `type: integer`) |
| 可校验性 | 弱（运行时才报错） | 强（schema 可静态校验） |
| 跨语言 | 否（只认 Python 类型） | 是（JSON Schema 是通用格式） |

```python
# Week 06 @tool：描述是 docstring，参数是 Python 类型注解
@tool
def search_routes(difficulty: str, days: int) -> str:
    """搜索徒步路线。difficulty 为难度，days 为天数。"""
    return f"推荐{difficulty}路线（{days}天）"

# MCP：描述和参数都被转成 JSON Schema（SDK 自动转换）
@server.tool()
async def search_routes(difficulty: str, days: int) -> str:
    """搜索徒步路线。difficulty 为难度，days 为天数。"""
    return f"推荐{difficulty}路线（{days}天）"
# 底层 SDK 会自动把 difficulty:str → {"type":"string"}
#                  days:int → {"type":"integer"}
```

> **JSON Schema 的优势：** 跨语言、可校验。一个 TypeScript 写的 Host 拿到 Python Server 返回的 JSON Schema，照样能解析参数格式。这就是"标准协议"的价值——描述格式是通用的，不绑定任何编程语言。

### 3.4 动态工具发现 vs 静态注册

这是今天最核心的认知升级。Week 06 的 `@tool` 是**静态注册**，MCP 是**动态发现**。

**静态注册（Week 06）：**

```python
# 工具列表在代码里写死，运行时不会变
agent = create_agent(
    model="ollama:qwen2.5:7b",
    tools=[get_weather, search_routes, send_email],  # ← 写死
    system_prompt="你是助手。",
)
```

**动态发现（MCP）：**

```python
# 运行时才查 Server 有哪些工具，不写死
async with ClientSession(read, write) as session:
    await session.initialize()
    tools = await session.list_tools()  # ← 运行时动态查询
    # tools 是什么，完全取决于 Server 当下暴露了什么
```

两者的差异用一个表说清楚：

| 维度 | 静态注册（@tool） | 动态发现（MCP） |
|------|------------------|----------------|
| 何时知道有哪些工具 | 编码时写死 | 运行时查询 |
| 添加新工具 | 改 Agent 代码，重新部署 | Server 更新，Client 自动发现 |
| 多工具源 | 手动合并多个 tools 列表 | 连多个 Server，工具自动聚合 |
| 扩展性 | 低（改代码才能加工具） | 高（加个 Server 就行） |

动态发现的三个优势：

1. **可以随时添加新工具**——Server 端加了个工具，Client 下次连上自动发现，Agent 代码一行不用改
2. **可以连接多个 Server，工具自动聚合**——Host 连三个 Server，三套工具自动汇总给 LLM
3. **不需要改 Agent 代码就能扩展能力**——这是最关键的，能力扩展变成了"运维操作"（加个 Server 配置），不再是"开发操作"（改代码）

> **前端类比：** 静态注册像把所有路由写死在路由表里（`routes: [Home, About, Contact]`）；动态发现像微前端架构——主应用启动时去注册中心拉取"现在有哪些子应用可用"，子应用增减不用改主应用代码。MCP 的动态发现就是这个思路。

---

## 四、Claude Code 的 MCP 集成原理

### 4.1 Claude Code 本质上是一个 MCP Host

Day 01 和 Day 02 我们都提到过"Claude Code 是一个 MCP Host"，但当时没有深入。现在你理解了 Client 的工作机制，可以真正看懂 Claude Code 的 MCP 集成了。

Claude Code 不是一个普通的聊天客户端，它本质上是一个 MCP Host——它内部运行 LLM（Claude），并且可以通过配置连接任意多个 MCP Server。

```
┌──────────────────────────────────────────────────────┐
│                    Claude Code (Host)                 │
│                                                      │
│   ┌──────────┐    ┌──────────┐   ┌──────────┐       │
│   │   LLM    │    │ Client 1 │   │ Client 2 │       │
│   │ (Claude) │    │          │   │          │       │
│   └──────────┘    └────┬─────┘   └────┬─────┘       │
│        │                │              │             │
│        └────────────────┴──────────────┘             │
│              工具描述汇总给 LLM                       │
└──────────────────────────┬───────────────┬──────────┘
                           │               │
                    stdio  │        stdio  │
                           ▼               ▼
             ┌──────────────────┐  ┌──────────────────┐
             │  hiking-route     │  │  filesystem      │
             │  (你 Day02 写的)  │  │  (Claude 内置)   │
             └──────────────────┘  └──────────────────┘
```

### 4.2 启动流程

Claude Code 启动时连接 MCP Server 的完整流程：

```
1. 读取配置（.claude/settings.json 或 .mcp.json）
   │  发现配置了哪些 MCP Server
   │
2. 启动每个 MCP Server 作为子进程
   │  对 stdio 传输的 Server：执行 command + args 拉起进程
   │
3. 每个 Server 对应一个 Client
   │  Host 内部为每个 Server 创建专属 Client
   │
4. 汇总所有 Server 的工具
   │  每个 Client 发 tools/list，把结果汇总
   │
5. 把工具描述注入 LLM 的上下文
   │  所有工具的 JSON Schema 塞进发给 Claude 的消息
   │
6. LLM 决定调用时，Client 转发给对应 Server
   │  Claude 说"调 search_routes"，对应 Client 转发给 hiking-route Server
```

### 4.3 工具冲突处理

如果你连了两个 Server，它们恰好都有同名工具怎么办？比如 Server A 有 `search`，Server B 也有 `search`。Claude Code 的处理方式是**加前缀**：

```
Server: hiking-route    →  工具名：hiking-route__search_routes
Server: weather-server  →  工具名：weather-server__search
                           ^^^^^^^^^^^^^^^^ 前缀避免冲突
```

这样 LLM 在调用时能区分"我要调哪个 Server 的 search"。这个前缀机制是 Host 层面的处理，Client 和 Server 本身不感知。

### 4.4 对比 Day 02 的接入验证

Day 02 我们把 hiking-route-server 接入了 Claude Code，当时你只是"配置 + 重启 + 测试"。今天你理解了背后发生的事：

| Day 02 你做的 | 今天你理解的 |
|--------------|-------------|
| 在 settings.json 里加 mcpServers 配置 | Claude Code 读取配置，知道要连这个 Server |
| 重启 Claude Code | Host 执行启动流程第 1-3 步：拉起子进程、建 Client |
| 输入"搜索进阶3天路线" | Host 已把工具描述注入 LLM，LLM 决定调用 search_routes |
| Claude 返回结果 | Client 转发 tools/call，Server 执行，结果回传 LLM |

> **认知升级：** Day 02 你是"使用者视角"——配置一下就能用，觉得 MCP 很神奇。今天你是"开发者视角"——知道每一步背后发生了什么，Client 怎么连接、怎么发现、怎么转发。这个视角的转变，是从"会用工具"到"理解工具"的关键一步。

---

## 动手实验

### 🟢 青铜：运行 mcp_client_demo.py

把第二节的 `mcp_client_demo.py` 写出来，确保 Day 02 的 `my_mcp_server.py` 在同目录下。然后运行：

```bash
python mcp_client_demo.py
```

验证三件事：
1. Client 能成功连接 Server（不报连接错误）
2. 能看到 `search_routes` 工具被发现
3. 能看到工具调用的结果输出

> **提示：** 如果报 `ModuleNotFoundError: No module named 'mcp'`，说明没装 MCP SDK，先 `pip install mcp`。如果报连接超时，检查 `my_mcp_server.py` 路径是否正确。

### 🟡 白银：连接两个 Server，汇总工具

扩展 `mcp_client_demo.py`，同时连接两个不同的 MCP Server，把两边的工具汇总打印出来。

要求：
1. 写第二个 MCP Server（比如 `weather_server.py`，暴露一个 `get_weather(city)` 工具）
2. Client 代码里创建两个连接，分别连两个 Server
3. 汇总两个 Server 的所有工具，统一打印

```python
"""mcp_client_multi.py — 连接两个 MCP Server，汇总工具

同时连接 hiking-route-server 和 weather-server
"""
import asyncio
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def discover_tools(session, server_name):
    """连接一个 Server 并返回它的工具列表"""
    await session.initialize()
    tools = await session.list_tools()
    print(f"\n--- {server_name} 的工具 ---")
    for tool in tools.tools:
        print(f"  {tool.name}: {tool.description}")
    return tools


async def main():
    # 两个 Server 的配置
    params_list = [
        ("hiking-route", StdioServerParameters(
            command="python", args=["my_mcp_server.py"]
        )),
        ("weather", StdioServerParameters(
            command="python", args=["weather_server.py"]
        )),
    ]

    all_tools = []
    for name, params in params_list:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                tools = await discover_tools(session, name)
                all_tools.extend(tools.tools)

    print(f"\n汇总：共发现 {len(all_tools)} 个工具")


asyncio.run(main())
```

> **思考：** 这个实验模拟了 Claude Code 启动时汇总多个 Server 工具的过程。你在青铜实验里连一个 Server，白银连两个——你会发现，加一个 Server 不需要改 Agent 逻辑，只要多建一个 Client 连接。这就是动态发现的扩展性。

### 🔴 王者：写一个简单 MCP Host

写一个简单的 MCP Host：连接 MCP Server + 用 LangChain `create_agent` 调用工具。这把 Client 和 LLM 接起来了。

要求：
1. 用 MCP Client 连接 Day 02 的 hiking-route-server
2. 发现工具后，把工具描述转换成 LangChain 能用的 Tool 格式
3. 用 `create_agent` 创建 Agent，把转换后的工具传进去
4. 让 Agent 处理用户输入："帮我搜索进阶3天的徒步路线"

```python
"""mcp_host_demo.py — 简单 MCP Host

连接 MCP Server + 用 LangChain create_agent 调用工具
这是 Host 的最小实现：Client 发现工具 → 转成 LangChain Tool → Agent 调用
"""
import asyncio
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from langchain.agents import create_agent


# 把 MCP 工具转成 LangChain 可调用的 Tool
def mcp_tool_to_langchain(session, mcp_tool):
    """把一个 MCP 工具描述转成 LangChain Tool"""
    async def call_mcp_tool(**kwargs):
        result = await session.call_tool(mcp_tool.name, arguments=kwargs)
        return result.content[0].text

    call_mcp_tool.__name__ = mcp_tool.name
    call_mcp_tool.__doc__ = mcp_tool.description
    return call_mcp_tool


async def main():
    server_params = StdioServerParameters(
        command="python", args=["my_mcp_server.py"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 发现工具并转换
            mcp_tools = await session.list_tools()
            lc_tools = [
                mcp_tool_to_langchain(session, t)
                for t in mcp_tools.tools
            ]

            # 创建 Agent（把 MCP 工具喂给它）
            agent = create_agent(
                model="ollama:qwen2.5:7b",
                tools=lc_tools,
                system_prompt="你是徒步路线规划助手。",
            )

            # 让 Agent 处理用户输入
            response = await agent.ainvoke(
                {"messages": [{"role": "user", "content": "帮我搜索进阶3天的徒步路线"}]}
            )
            print(response["messages"][-1].content)


asyncio.run(main())
```

> **这是今天的高光时刻：** 你写了一个最小的 MCP Host——它能连接 Server、发现工具、把工具喂给 LLM、让 LLM 决定调用。这就是 Claude Code 做的事的简化版。区别只是 Claude Code 的工程更完善（错误处理、多 Server、上下文管理），但核心链路和你写的这个 Host 一模一样。

---

## 踩坑记录 🕳️

### 坑 1：async API 和 sync 代码混淆

MCP Client 的 API 全是 `async` 的，但很多人写着写着就忘了 `await`，或者把 async 函数和 sync 函数混着用。

```python
# 错误：忘了 await
tools = session.list_tools()  # ← 返回的是 coroutine，不是结果！
print(tools)  # 打印出 <coroutine object>

# 正确：加 await
tools = await session.list_tools()  # ← await 拿到真实结果
```

**解决：** MCP Client 的所有 IO 操作都是 async 的，记住三个规则：
- 所有 `session.xxx()` 调用前都要加 `await`
- 整个入口函数用 `async def main()`，最后 `asyncio.run(main())`
- 如果要在同步代码里调 async，用 `asyncio.run()` 包一层，不要混用

### 坑 2：Server 进程崩溃时 Client 不会自动重连

MCP 的 stdio 传输是"Host 启动 Server 子进程"的模式。如果 Server 进程因为 bug 崩了，Client 这边的连接会直接断开，但 Client 不会自动重连。

```python
# Server 崩了之后，Client 再调工具会报连接错误
result = await session.call_tool("search_routes", ...)
# RuntimeError: Connection closed / Server process exited
```

**解决：** 生产环境需要自己加重连逻辑。学习阶段不用管，但要意识到这是 stdio 传输的局限——它依赖子进程活着。SSE 传输相对好一些（可以重连 HTTP），但也要处理断线。这也是为什么大型生产环境推荐 Streamable HTTP 传输。

### 坑 3：工具发现的 JSON Schema 和 Python 类型提示的转换

MCP Server 用 Python 类型注解定义参数（`difficulty: str`），底层 SDK 会自动转成 JSON Schema（`{"type": "string"}`）。但有些转换不直观：

| Python 类型 | JSON Schema | 注意 |
|------------|-------------|------|
| `str` | `{"type": "string"}` | 直觉一致 |
| `int` | `{"type": "integer"}` | 直觉一致 |
| `bool` | `{"type": "boolean"}` | 直觉一致 |
| `list` | `{"type": "array"}` | 注意是 array 不是 list |
| `Optional[str]` | `{"type": "string"}` + required 里不列 | None 不会出现在 enum 里 |
| `Literal["a","b"]` | `{"type":"string","enum":["a","b"]}` | 枚举要靠 Literal |

**解决：** 如果 LLM 调用工具时参数总填错，先用 `session.list_tools()` 打印出实际的 JSON Schema，看看 SDK 把你的类型注解转成了什么。发现对不上再调整 Python 端的类型写法。

### 坑 4：多个 Server 工具名冲突

如果你连了两个 Server，它们都有 `search` 工具，Client 层面不冲突（各连各的），但汇总给 LLM 时会冲突——LLM 不知道"search"指的是哪个 Server 的。

```python
# 两个 Server 都有 search 工具
all_tools = []
for session in [session_a, session_b]:
    tools = await session.list_tools()
    all_tools.extend(tools.tools)
# all_tools 里有两个 search，LLM 调用时不知道找谁
```

**解决：** Host 层面要做去重或加前缀。Claude Code 的做法是加 `server-name__tool-name` 前缀。你自己写 Host 时，汇总工具前先 rename：`tool.name = f"{server_name}__{tool.name}"`。这样 LLM 调用时能区分。

---

## 副线笔记

### Claude Code 的 MCP 集成：从使用者到理解者

分析 Claude Code 的 MCP 集成，你会发现它做的事情其实很简单——启动时连接所有配置的 MCP Server，汇总工具，把工具描述注入 LLM 上下文。当你在 Claude Code 里问"帮我搜索进阶徒步路线"，它实际上是通过 MCP Client 调用了你 Day 02 写的 hiking-route Server 的 search_routes 工具。

用一张表把"你在 Claude Code 里做的事"和"底层发生的事"对应起来：

| 你在 Claude Code 里 | 底层发生的事 |
|---------------------|------------|
| 配置 .mcp.json | Claude Code 读配置，知道要连哪些 Server |
| 重启 Claude Code | 启动 Server 子进程，建 Client，发现工具 |
| 输入"搜索进阶路线" | 工具描述已在 LLM 上下文，LLM 决定调用 search_routes |
| 看到 Claude 的回答 | Client 转发 tools/call，Server 执行，结果回传 LLM |
| 输入 `/mcp` 查看状态 | Host 展示每个 Client 的连接状态和工具列表 |

### 对比 Week 06 的静态调用

| 维度 | Week 06（@tool + create_agent） | 今天（MCP Client + Host） |
|------|--------------------------------|--------------------------|
| 工具在哪 | 同进程 Python 函数 | 独立进程的 MCP Server |
| 怎么发现 | 代码里写死 tools=[...] | 运行时 list_tools() 动态发现 |
| 加工具 | 改 Agent 代码重新部署 | 加个 Server 配置，重启 Host |
| 跨语言 | 不能 | 能 |

### 今日观察任务

- 打开 Claude Code 的 MCP 配置，数数它接了几个 Server
- 输入 `/mcp` 查看 Client 连接状态，看看有没有"断连"的 Server
- 思考：Claude Code 自带的工具（读文件、跑命令、搜代码），底层是不是也是 MCP Server？有多少是 MCP 实现的，有多少是内置的？
- 副线目标：Day 07 综合项目会把 MCP Server + Skill + Client 组装成一个完整的能力包，今天的 Client 知识是最后一块拼图

---

## 检查清单

- [ ] 理解 MCP Client 的工作机制（连接 → 发现 → 转发 → 调用 → 返回）
- [ ] 知道 Client 和 Server 是一对一关系，Host 可以有多个 Client
- [ ] 完成了 `mcp_client_demo.py`，能连接 Day 02 的 Server 并发现工具
- [ ] 理解工具发现的完整流程（list → 选择 → 调用 → 获取结果）
- [ ] 知道工具描述是 JSON Schema 格式，和 Week 06 @tool 的 docstring 对比
- [ ] 理解动态发现 vs 静态注册的区别和优势
- [ ] 知道 Claude Code 的 MCP 集成原理（读配置 → 启动子进程 → 建 Client → 汇总工具）

---

## 下课预告

> **Day 07 — 综合产出：MCP Server + Skill + Client 组装成完整能力包。** 今天你写完了 MCP Client，掌握了工具发现的完整链路。从 Day 01 到 Day 06，你学了 MCP Server（Day 01-02）、Skills（Day 03-04）、A2A（Day 05）、MCP Client（Day 06）。明天是 Week 08 的收官——把这些全部组装起来，产出一个完整的能力包：一个 MCP Server 暴露工具、一个 SKILL.md 定义使用流程、一个 Client 连接并调用。你会真正理解"工具接口 + 能力知识 + 连接协议"三者怎么协作，这是从零散学习到系统整合的关键一步。
