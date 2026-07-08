# Day 01 — MCP 核心概念：Server / Client / Transport

## 学习目标

Week 07 我们把单 Agent 升级成了多 Agent，学会了 Subagents / Handoffs / Skills / Router 四大模式，主 Agent 协调子 Agent、上下文隔离、并行执行。但你有没有注意到一个共同点——所有这些 Agent、所有这些工具，都跑在**同一个 Python 进程**里。Week 06 的 `@tool` 是 Python 函数，Week 07 的子 Agent 也是 Python 对象，它们靠内存里的函数调用通信。换一个语言、换一个框架，工具就得重写一遍。今天我们从 Agent 框架层往下沉一层，进入**协议层**——MCP（Model Context Protocol）。它解决的问题是：把工具从"同进程函数"升级成"跨进程标准协议"，让一个工具能被 Claude Code、Cursor、任何 MCP 客户端调用，不用为每个宿主重写。

学完今天你能：
1. 理解 MCP 的核心定位：把工具从同进程函数升级为跨进程标准协议，让工具成为独立可复用的"服务"
2. 掌握 MCP 的三大角色：Server（暴露工具）、Client（调用工具）、Host（宿主应用如 Claude Code），说清它们各自的职责边界
3. 理解 MCP 的三种传输层：stdio（本地进程通信）、SSE（HTTP 流式）、Streamable HTTP（2026 新标准），知道各自适合什么场景
4. 能说清楚 MCP 和 Week 06 的 `@tool` 的本质区别：跨进程标准协议 vs 同进程函数调用，以及各自适合什么场景

---

## 一、为什么需要 MCP：从 @tool 到标准协议

### 1.1 回顾 Week 06 的 @tool

Week 06 你用 `@tool` 装饰器定义工具，`create_agent` 一行创建 Agent，底层自动管理工具循环。代码大概长这样：

```python
"""Week 06 回顾：@tool 是同进程 Python 函数"""
from langchain.agents import create_agent
from langchain.tools import tool


@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。city 为城市名。"""
    # mock 数据，生产环境此处调真实天气 API
    return f"{city}：晴 25°C"


# Agent 和工具在同一个进程里，函数调用即可
agent = create_agent(
    model="ollama:qwen2.5:7b",
    tools=[get_weather],
    system_prompt="你是天气助手。",
)
```

这段代码能跑，工具数不多时表现也不错。但当你想把 `get_weather` 这个工具给 **Claude Code** 用、给 **Cursor** 用、给一个 **TypeScript 写的 Agent** 用时，问题来了——它是个 Python 函数，Claude Code 没法直接 import 它。

### 1.2 @tool 的三大痛点

| 痛点 | 表现 | 后果 |
|------|------|------|
| **语言绑定** | `@tool` 是 Python 函数，TypeScript/Go 的 Agent 用不了 | 换语言就得重写工具 |
| **进程绑定** | 工具和 Agent 跑在同一进程，Agent 崩了工具也跟着死 | 工具无法独立部署、独立升级 |
| **框架绑定** | `@tool` 是 LangChain 的装饰器，换 LangGraph 原生 / 换 CrewAI 又是一套 | 工具和框架耦合，复用性差 |

一句话总结：`@tool` 的工具是"内嵌函数"，它和 Agent **绑死**在同进程、同语言、同框架里。

### 1.3 MCP 的解决方案：工具变成独立服务

MCP（Model Context Protocol）是 Anthropic 在 2024 年底提出、2025-2026 年快速普及的开放协议。它的核心思路很简单：**把工具变成一个独立的服务进程，用标准协议通信**。

- 工具不再是一个 Python 函数，而是一个**独立运行的进程**（MCP Server）
- Agent（Host）通过标准协议（MCP）和这个进程通信，不关心它用什么语言写的
- 一个 MCP Server 写一次，可以被 Claude Code、Cursor、任何 MCP 客户端调用

> **直觉类比：** `@tool` 像"内嵌函数"——工具是 Agent 身体里的一个器官，离了 Agent 就活不了；MCP 像"微服务 API"——工具是独立的服务进程，Agent 通过网络/管道调用它，工具可以独立部署、独立升级、跨语言复用。你做过 11 年前端，这个类比应该很熟悉：`@tool` 是组件内部的方法调用，MCP 是后端 REST API。

### 1.4 ASCII 图对比

```
Week 06 @tool（同进程）：
┌─────────────────────────────────┐
│         同一个 Python 进程       │
│  ┌─────────┐    ┌────────────┐  │
│  │  Agent   │───►│ @tool 函数 │  │  ← 函数调用，内存里直接跑
│  │ (LLM)    │    │get_weather │  │
│  └─────────┘    └────────────┘  │
│         工具是 Python 函数        │
└─────────────────────────────────┘

MCP（跨进程）：
┌──────────────────┐               ┌──────────────────┐
│  Host(Claude Code)│              │  MCP Server      │
│  ┌──────┐ ┌─────┐ │   标准协议    │  (独立进程)       │
│  │ LLM  │ │Client│◄┼────────────►│  get_weather()   │
│  └──────┘ └─────┘ │  stdio/SSE   │  search_db()     │
│     Agent 在这    │               │  工具在这(可任意语言)│
└──────────────────┘               └──────────────────┘
   工具是独立进程，跨语言
```

关键区别：左边工具和 Agent 在同一个进程里，是函数调用；右边工具是独立进程，通过标准协议通信。这一步升级，让工具从"Agent 的附属品"变成了"独立可复用的服务"。

### 1.5 MCP 生态数据（2026）

MCP 在 2025 年下半年迎来了爆发式增长，到 2026 年已经成为 Agent 生态的事实标准：

| 指标 | 数据 | 说明 |
|------|------|------|
| SDK 月下载量 | ~9700 万 | Python / TypeScript / Go / Java 多语言 SDK |
| 已发布 MCP Server | 1 万+ | 官方和社区贡献，覆盖数据库/搜索/文件/API 等 |
| IDE 原生支持 | 主流全覆盖 | Claude Code / Cursor / Windsurf / Zed / VS Code(Copilot) |
| 协议版本 | 2026-03 spec | 引入 Streamable HTTP 传输层 |

> **为什么这么火：** 因为它解决了"每个 Agent 框架都要自己造一套工具轮子"的重复劳动。工具开发者写一次 MCP Server，所有支持 MCP 的客户端都能用——这和你做前端时"写一个组件库，所有项目都能用"是一个逻辑。

---

## 二、MCP 三大角色

MCP 协议里有三个核心角色：Host、Client、Server。理解这三个角色的职责边界，是搞懂 MCP 架构的关键。

### 2.1 Host（宿主应用）

Host 是**运行 LLM 的应用**，也就是用户直接交互的那个程序。

- 典型 Host：Claude Code、Cursor、Windsurf、Zed
- Host 内部运行 LLM，负责把用户请求交给 LLM 推理
- Host 内部可以运行**多个 Client**，每个 Client 连接一个 MCP Server
- Host 决定"把哪些 MCP Server 的工具描述喂给 LLM"

你可以把 Host 理解成一个"总调度"——它管理 LLM、管理多个 Client、管理用户交互。用户只跟 Host 打交道，看不到底下的 Client 和 Server。

### 2.2 Client（客户端）

Client 是 **Host 内部的 MCP 客户端**，负责和单个 Server 通信。

- **每个 Client 连接一个 Server**（1 对 1 关系）
- Client 的职责：连接 Server → 发现 Server 暴露的工具/资源/提示词 → 把工具描述转发给 LLM
- Client 不做业务逻辑，它是个"翻译官"——把 Server 的工具描述翻译成 LLM 能理解的格式
- 当 LLM 决定调用某个工具时，Host 通过对应的 Client 把调用请求发给 Server

> **关键点：** Client 是 Host 内部的组件，不是独立进程。你写 MCP 应用时，通常是写 Server（暴露工具）或写 Host（集成 LLM + Client）。Client 一般由 SDK 自动管理，你很少直接手写。

### 2.3 Server（服务端）

Server 是**暴露工具/资源/提示词的独立进程**。

- 可以用 Python、TypeScript、Go、Java 等任何语言写
- Server 暴露三类能力：
  - **Tool（工具）**：可调用的函数，如 `get_weather(city)`
  - **Resource（资源）**：可读取的数据，如一个文件、一个数据库表
  - **Prompt（提示词）**：可复用的提示词模板
- Server 是独立进程，可以独立部署、独立升级、独立重启
- 一个 Server 可以被多个 Host 同时连接（多客户端共享）

### 2.4 ASCII 架构图

```
┌─────────────────────────────────────────────┐
│              Host (Claude Code)             │
│                                             │
│   ┌─────────┐    ┌─────────┐  ┌─────────┐  │
│   │   LLM   │    │ Client1 │  │ Client2 │  │
│   │  (推理)  │    │         │  │         │  │
│   └─────────┘    └────┬────┘  └────┬────┘  │
│        │              │            │       │
│        └──────────────┴────────────┘       │
│              工具描述汇总给 LLM              │
└───────────────────────┬─────────────┬───────┘
                        │             │
                  stdio  │      SSE   │  (传输层)
                        ▼             ▼
          ┌──────────────────┐  ┌──────────────────┐
          │  MCP Server A    │  │  MCP Server B    │
          │  (Python 进程)   │  │  (TypeScript 进程)│
          │                  │  │                  │
          │  - get_weather   │  │  - search_db     │
          │  - get_altitude  │  │  - query_log     │
          └──────────────────┘  └──────────────────┘
```

看这张图重点理解三件事：
1. Host 内部有 LLM 和多个 Client，Client 是 1 对 1 连 Server 的
2. 传输层（stdio / SSE）是 Client 和 Server 之间的通信管道，后面会细讲
3. 每个 Server 可以用不同语言写，Host 不关心 Server 的实现语言

### 2.5 @tool vs MCP 六维度对比

| 维度 | Week 06 @tool | MCP Server |
|------|---------------|------------|
| **语言绑定** | 只能用 Python（或对应框架语言） | Python / TypeScript / Go / Java 任意语言 |
| **进程模型** | 同进程，函数调用 | 独立进程，协议通信 |
| **调用方式** | 内存函数调用 `get_weather(city)` | 跨进程消息 `Client → Server → 返回` |
| **工具发现** | 手动把 tools 列表传给 `create_agent` | Client 自动发现 Server 暴露的工具 |
| **跨框架** | LangChain 的 @tool 只能 LangChain 用 | 一个 MCP Server 所有 MCP 客户端通用 |
| **生态** | 自己写自己用 | 1 万+ 现成 Server 可直接接入 |

> **一句话记忆：** `@tool` 是"自家用的小工具"，MCP 是"公开的标准插座"——你写的工具插上去，所有支持 MCP 的电器（Host）都能用。

---

## 三、MCP 三种传输层

Client 和 Server 之间需要一条通信管道，这就是传输层（Transport）。MCP 定义了三种传输层，分别适合不同场景。

### 3.1 stdio：标准输入输出

stdio 是最简单的传输层，用操作系统的标准输入/标准输出（stdin/stdout）通信。

- **工作方式**：Host 启动 Server 作为**子进程**，通过 stdin/stdout 通信
- Host 往 Server 的 stdin 写请求，Server 往 stdout 写响应
- **适合场景**：本地开发工具、本地命令行工具
- **优点**：零配置、零网络开销、最简单
- **缺点**：只能本地用，不能远程访问

```
Host 进程                Server 子进程
   │                         │
   │── stdin ──写请求────────►│
   │                         │
   │◄── stdout ─读响应───────│
   │                         │
   (stderr 可用于日志调试)
```

> **重要提醒：** 用 stdio 传输时，Server 里**绝对不能 `print()` 调试**！因为 stdout 是通信管道，你 print 的内容会被 Host 当成协议消息解析，直接报错。调试要写到 stderr 或日志文件里。

### 3.2 SSE：Server-Sent Events

SSE 是基于 HTTP 的流式传输，Server 是一个 HTTP 服务。

- **工作方式**：Server 是一个 HTTP 服务，Host 通过 HTTP 请求 + SSE 推送通信
- Client 发 HTTP POST 请求，Server 通过 SSE（Server-Sent Events）流式推送结果
- **适合场景**：远程服务、需要多客户端共享的 Server
- **优点**：可远程访问、可多客户端共享
- **缺点**：需要部署 HTTP 服务、比 stdio 复杂

```
Host                              MCP Server (HTTP 服务)
  │                                   │
  │── HTTP POST /messages ───────────►│
  │                                   │
  │◄── SSE 推送 result chunk 1 ───────│
  │◄── SSE 推送 result chunk 2 ───────│
  │◄── SSE 推送 [完成] ────────────────│
```

### 3.3 Streamable HTTP：2026 新标准

Streamable HTTP 是 2026 年引入的新传输层，兼容 SSE 但更灵活。

- **工作方式**：单个 HTTP 端点，支持双向流式
- 兼容 SSE，但不需要维护长连接的 SSE 通道
- 支持双向流式（Server 和 Client 都可以流式发送）
- **适合场景**：生产环境、需要更好扩展性的远程服务
- **优点**：更灵活、兼容性好、更适合云原生部署
- **缺点**：协议稍复杂，需要较新的 SDK 版本

### 3.4 三种传输层对比

| 传输层 | 通信方式 | 适合场景 | 延迟 | 复杂度 | 多客户端 |
|--------|---------|---------|------|--------|---------|
| **stdio** | 进程 stdin/stdout | 本地开发、CLI 工具 | 最低（进程间） | 最低 | 否（1 Host 1 Server） |
| **SSE** | HTTP + SSE 流 | 远程服务、需共享 | 中（网络） | 中 | 是 |
| **Streamable HTTP** | HTTP 双向流 | 生产环境、云原生 | 中（网络） | 较高 | 是 |

> **选型建议：** 本地开发先用 stdio（最简单），需要远程访问时上 SSE，生产环境大规模部署用 Streamable HTTP。学习阶段建议从 stdio 入手，今天和明天的实验都用 stdio。

### 3.5 代码示例：最小 MCP Server

用 stdio 传输启动一个最小 MCP Server，结构如下。注意这是**概念演示伪代码**，展示 MCP Server 的骨架结构，真实 API 明天会完整实现：

```python
"""概念演示：最小 MCP Server 结构（伪代码，展示概念）

MCP 把工具从"同进程函数"升级为"跨进程标准协议"。
这个 Server 暴露一个 get_weather 工具，用 stdio 传输。

安装：pip install mcp
"""
from mcp.server import Server
from mcp.server.stdio import stdio_server

# 创建一个 MCP Server 实例，名字是 "my-first-server"
server = Server("my-first-server")


# 用装饰器注册一个工具，和 Week 06 的 @tool 写法很像
@server.tool()
def get_weather(city: str) -> str:
    """查询指定城市的天气。city 为城市名。"""
    # 生产环境此处调真实天气 API
    return f"{city}: 晴 22°C"


if __name__ == "__main__":
    # 用 stdio 传输启动 Server
    # Host 会把这个文件作为子进程启动，通过 stdin/stdout 通信
    stdio_server(server)
```

对比 Week 06 的 `@tool` 写法，你会发现**工具定义部分几乎一样**——都是装饰器 + 函数 + docstring。区别在于：

| 对比项 | Week 06 @tool | MCP Server |
|--------|---------------|------------|
| 装饰器 | `@tool`（langchain） | `@server.tool()`（mcp） |
| 运行方式 | 被 Agent 直接函数调用 | 作为独立进程通过 stdio 通信 |
| 启动代码 | 不需要（Agent 自动调） | 需要 `stdio_server(server)` |
| 调用方 | 同进程的 Agent | 任意 MCP 客户端（Claude Code 等） |

> **洞察：** 从 `@tool` 迁移到 MCP Server，工具的"业务逻辑"几乎不用改，改的是"工具怎么被调用"——从函数调用变成协议通信。这就是 MCP 的价值：它让你用熟悉的写法定义工具，但工具变成了跨进程、跨语言、跨框架的标准服务。

---

## 动手实验

### 🟢 青铜：安装 mcp Python SDK，运行官方示例

```bash
# 安装 MCP Python SDK
pip install mcp

# 验证安装
python -c "import mcp; print(mcp.__version__)"
```

然后找到 MCP 官方仓库的 `hello-world` 示例（或官方文档里的 quickstart），跑起来。验证三件事：
1. SDK 安装成功，能 `import mcp`
2. 官方示例能启动（可能需要配合一个 MCP 客户端或 Inspector 工具）
3. 观察启动后的进程——它是一个独立进程，等待 stdin 输入

> **提示：** MCP 官方提供了 `mcp dev` 命令（Inspector 调试工具），可以在浏览器里可视化测试你的 Server。青铜阶段先用它观察一个 Server 长什么样。

### 🟡 白银：完成 mcp_concept_demo.py

写一个最小 MCP Server，暴露一个 `echo` 工具，用 stdio 传输。要求：

```python
"""mcp_concept_demo.py — 最小 MCP Server 概念演示

暴露一个 echo 工具：接收文本，原样返回。
用 stdio 传输，验证 MCP Server 的基本结构。
"""
from mcp.server import Server
from mcp.server.stdio import stdio_server

server = Server("concept-demo")


@server.tool()
def echo(text: str) -> str:
    """原样返回输入的文本。text 为要回显的文本。"""
    return f"echo: {text}"


if __name__ == "__main__":
    # 用 stdio 启动，注意不要用 print 调试（会污染 stdout）
    stdio_server(server)
```

验证方法：
1. 用 `mcp dev` 或 MCP Inspector 连接这个 Server，看到 `echo` 工具
2. 调用 `echo(text="hello")`，确认返回 `echo: hello`
3. 思考：这个 Server 是独立进程，Host 怎么发现它的 `echo` 工具的？（答案：Client 连接后自动发现）

### 🔴 王者：把 Week 06 的 @tool get_weather 改写成 MCP Server

把 Week 06 的 `get_weather` 工具改写成 MCP Server，对比两种调用方式的差异。要求：

1. 创建一个 MCP Server，暴露 `get_weather(city)` 工具（和 Week 06 同样的 mock 逻辑）
2. 用 stdio 传输启动
3. 写一段对比说明：
   - Week 06：Agent 怎么调用 `get_weather`？（同进程函数调用）
   - MCP：Host 怎么调用 `get_weather`？（跨进程协议通信）
   - 同一个工具，两种方式各需要几步？
4. 思考题：如果想让 Claude Code 也能用这个 `get_weather`，Week 06 的 @tool 版本能做到吗？MCP 版本能做到吗？为什么？

> **对比要点：** Week 06 的 `@tool get_weather` 只能被同一个 Python 进程里的 LangChain Agent 调用；MCP 版本可以被 Claude Code、Cursor、任何 MCP 客户端调用。这就是"跨进程标准协议"的价值。

---

## 踩坑记录 🕳️

### 坑 1：mcp SDK 版本更新快，API 可能变化

```
ImportError: cannot import name 'Server' from 'mcp.server'
```

**解决：** MCP SDK 在 2025-2026 年迭代很快，从早期的 `FastMCP` 到后来的 `Server` 类，API 有过几次调整。安装时注意版本：
- 看 `pip show mcp` 的版本号
- 查官方文档对应版本的 API
- 如果 `from mcp.server import Server` 报错，可能需要用 `from mcp.server.fastmcp import FastMCP`（更简化的高层 API）

明天 Day 02 会用确定可用的 API 写完整 Server，今天先理解概念。

### 坑 2：stdio 传输不能用 print() 调试

```python
# ❌ 错误：stdio 传输时 print 会污染 stdout
@server.tool()
def echo(text: str) -> str:
    print(f"收到请求: {text}")  # 这行会导致 Host 协议解析报错！
    return f"echo: {text}"
```

**解决：** stdio 传输下，stdout 是协议通信管道，**任何 print 都会被 Host 当成协议消息解析**，导致报错或通信混乱。调试时：
- 写到 stderr：`import sys; print("debug", file=sys.stderr)`（stderr 不走协议）
- 写到日志文件：`logging.basicConfig(filename="server.log")`
- 用 MCP Inspector 工具可视化调试

### 坑 3：MCP Server 和 Agent 的进程隔离导致调试困难

MCP Server 是独立进程，你没法像调试 `@tool` 那样在 Agent 代码里打断点单步跟踪。Server 跑在另一个进程里，工具调用是跨进程消息。

**解决：**
- 用 MCP Inspector（`mcp dev` 命令）独立测试 Server，不依赖 Host
- Server 内部多写日志，把每次调用的入参/返回记下来
- 先用 Inspector 验证 Server 工具正常，再接入 Claude Code 等 Host
- 记住：进程隔离是 MCP 的特性不是 bug，它带来的是工具可独立部署、独立升级的好处

### 坑 4：以为 MCP Server 就是普通 HTTP 服务

新手容易以为 MCP Server 就是个普通 REST API，直接用 FastAPI 写几个路由。其实不是——MCP 有自己的 JSON-RPC 协议格式，Client 发的请求、Server 回的响应都有固定结构。你不能用 `requests.get("/weather")` 调 MCP Server。

**解决：** MCP Server 用 SDK 提供的 `Server` 类和 `stdio_server` / SSE 启动函数，SDK 自动处理协议编解码。你只管写工具函数，协议层 SDK 包办。明天 Day 02 会详细讲 Server 的完整开发流程。

---

## 副线笔记

### Claude Code 的 MCP 集成：它本身就是一个 MCP Host

Claude Code 本身就是一个 MCP Host——它内部运行 LLM（Claude），并且可以连接任意 MCP Server。你在 Claude Code 的配置里加一个 MCP Server，它就能用那个 Server 暴露的所有工具。

配置方式（在 Claude Code 的 settings 或 `.mcp.json` 里）：

```json
{
  "mcpServers": {
    "my-weather-server": {
      "command": "python",
      "args": ["e:/workspace/project/myAIAgentLearning/week08/my_mcp_server.py"],
      "transport": "stdio"
    }
  }
}
```

加了这段配置后，Claude Code 会：
1. 启动时用 `python my_mcp_server.py` 拉起一个子进程（你的 MCP Server）
2. 内部创建一个 Client 连接到这个 Server（stdio 传输）
3. 自动发现 Server 暴露的 `get_weather` 等工具
4. 把工具描述喂给 Claude（LLM）
5. Claude 决定调工具时，Client 把请求通过 stdin 发给 Server

### 对比你做过的两种方式

| 对比项 | Week 06 @tool（Agent 内嵌） | Claude Code + MCP Server |
|--------|----------------------------|--------------------------|
| 工具在哪 | Agent 同进程的 Python 函数 | 独立进程，Claude Code 外部 |
| 怎么接 | 写在 Agent 代码里 `tools=[get_weather]` | 在配置文件里加一段 mcpServers |
| 谁能用 | 只有那个 Python Agent | Claude Code（以及任何 MCP 客户端） |
| 升级工具 | 改 Agent 代码，重启 Agent | 改 Server 代码，重启 Server（Agent 不用动） |

### 今日观察任务

- 如果你装了 Claude Code，打开它的 MCP 配置，看看它已经接了哪些 MCP Server（有些是默认自带的）
- 思考：Claude Code 自带的工具（读文件、跑命令、搜代码），有多少是 MCP Server 实现的？有多少是内置的？
- 副线目标：本周 Day 02 写完自己的 MCP Server 后，把它接入 Claude Code，体验"自己写的工具被 Claude 用"的感觉

---

## 检查清单

- [ ] 理解 MCP 的三大角色：Host（运行 LLM 的应用）、Client（Host 内部连 Server 的客户端）、Server（暴露工具的独立进程）
- [ ] 能说清 @tool 和 MCP 的本质区别：同进程函数调用 vs 跨进程标准协议
- [ ] 知道三种传输层的适用场景：stdio（本地）、SSE（远程流式）、Streamable HTTP（生产环境）
- [ ] 知道 stdio 传输不能用 print 调试，要用 stderr 或日志文件
- [ ] 安装了 mcp Python SDK，跑通了最小 MCP Server（echo 或 get_weather）
- [ ] 理解 Claude Code 是一个 MCP Host，能通过配置接入任意 MCP Server

---

## 下课预告

> **Day 02 — MCP Server 开发：Tool / Resource / Prompt。** 今天我们理解了 MCP 的三大角色和三种传输层，知道了 MCP 把工具从"同进程函数"升级成"跨进程标准协议"。明天我们动手写一个完整的 MCP Server，暴露 MCP 的三类能力：Tool（可调用工具）、Resource（可读取资源）、Prompt（可复用提示词模板）。你会学到：用 mcp SDK 定义工具、用 stdio 启动 Server、用 MCP Inspector 调试、以及把写好的 Server 接入 Claude Code 实际调用。这是从"理解概念"到"产出可用 Server"的关键一步。
