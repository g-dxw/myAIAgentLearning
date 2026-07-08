# Day 02 — MCP Server 开发：Tool / Resource / Prompt

## 学习目标

Day 01 我们搞清楚了 MCP 是什么：它把 Week 06 的 `@tool`——一个只能在本进程里跑的 Python 函数——升级成了跨进程、跨语言的标准协议。MCP Server 就是一个"工具服务"，任何 MCP Client（Claude Code、Cursor、你自己写的客户端）都能连上来调用它的能力。但 Day 01 只是跑了个最小骨架，今天我们要往里塞东西——MCP Server 不只能暴露工具，它有三种能力：Tool（工具调用）、Resource（资源读取）、Prompt（提示词模板）。这三种能力对应了 Agent 与外部世界交互的三种方式：执行动作、读取数据、提供指令。今天我们手写一个完整的徒步路线查询 MCP Server，把三种能力都暴露出来，再接入 Claude Code 实际验证。

学完今天你能：
1. 掌握 MCP Server 的三种能力：Tool（工具调用）、Resource（资源读取）、Prompt（提示词模板），能说清它们各自解决什么问题
2. 能用 Python MCP SDK 写一个完整的 MCP Server，暴露三种能力，并解释每个装饰器背后的机制
3. 理解 MCP Server 的工具发现机制：Client 连接后如何"发现"Server 有哪些 Tool / Resource / Prompt，LLM 又如何决定调用哪个
4. 能把 MCP Server 接入 Claude Code 验证，在 Claude Code 里实际调用自己写的工具

---

## 一、MCP Server 的三种能力

### 1.1 不只是工具：三种能力概览

很多人第一次接触 MCP 会以为"MCP Server = 工具服务"，觉得它就是 Week 06 `@tool` 的跨进程版本。这只说对了一部分。MCP Server 实际上能暴露**三种能力**，工具只是其中之一：

| 能力 | 说明 | 类比 | 例子 |
|------|------|------|------|
| **Tool** | 可调用的函数，执行动作后有副作用 | Week 06 的 `@tool` | `get_weather(city)`、`search_routes(difficulty, days)` |
| **Resource** | 可读取的数据源，只读不写 | 文件系统 / API 接口 | 读取配置文件、查询数据库、拉取日志 |
| **Prompt** | 预定义的提示词模板，可复用 | 系统提示词 | "你是一个天气分析助手，请从以下维度分析..." |

对应到 Agent 的交互方式：

```
MCP Server 暴露的三种能力
┌──────────────────────────────────────────────────────┐
│                    MCP Server                        │
│                                                      │
│   Tool      → "执行动作"（有副作用，如发邮件/写DB）    │
│   Resource  → "读取数据"（只读，如读配置/查状态）      │
│   Prompt    → "提供指令"（给 LLM 一段预设模板）        │
│                                                      │
└──────────────────────────────────────────────────────┘
        ▲            ▲            ▲
        │            │            │
   tools/call   resources/read  prompts/get
        │            │            │
   ┌────┴────────────┴────────────┴────┐
   │           MCP Client              │
   │  （Claude Code / Cursor / ...）   │
   └───────────────────────────────────┘
```

### 1.2 Tool 和 Resource 的区别

这是最容易混淆的一对。记住一个判断标准：**有没有副作用**。

| 维度 | Tool（工具） | Resource（资源） |
|------|--------------|-----------------|
| 本质 | 执行一个动作 | 读取一份数据 |
| 副作用 | 有（可能改状态、发邮件、写 DB） | 无（纯读取，不改任何东西） |
| 调用方式 | `tools/call`，LLM 决定何时调 | `resources/read`，按 URI 读取 |
| 幂等性 | 不一定幂等 | 幂等（读多少次结果一样，数据没变的话） |
| 类比 | POST 请求 | GET 请求 |
| 典型例子 | `send_email(to, subject)` | `config://app-settings` |

> **一句话记忆：** Tool 是"动词"（去干活），Resource 是"名词"（拿来看）。`search_routes` 是 Tool（去搜索这个动作），`route://config` 是 Resource（路线配置这份静态数据）。

举个例子区分：

```python
# 这是 Tool —— 执行"搜索"动作，有逻辑处理
@server.tool()
async def search_routes(difficulty: str) -> str:
    """搜索徒步路线。"""
    # 内部有匹配逻辑，可能还要查数据库
    return f"匹配到 {difficulty} 难度的路线 3 条"

# 这是 Resource —— 读取"配置"数据，纯静态
@server.resource("route://config")
async def get_route_config() -> str:
    """读取路线配置信息。"""
    return "数据源：本地数据库 / 更新时间：2026-07 / 支持区域：川西"
```

### 1.3 Prompt 和 Week 06 的 system_prompt 的区别

Week 06 你给 Agent 写过 `system_prompt="你是徒步规划助手..."`。MCP 的 Prompt 和它长得像，但本质不同：

| 维度 | Week 06 system_prompt | MCP Prompt |
|------|----------------------|------------|
| 定义位置 | Agent 代码里，写死在 `create_agent` 参数 | MCP Server 提供，Client 动态获取 |
| 可复用性 | 只能给这一个 Agent 用 | 任何连上来的 Client 都能用 |
| 参数化 | 不支持（就是一段固定文本） | 支持参数（如 `route_analysis(route_name="贡嘎")`） |
| 发现方式 | Client 不知道有哪些 prompt | `prompts/list` 能列出所有可用模板 |
| 本质 | Agent 的"出厂设置" | Server 提供的"可复用模板库" |

关键区别在于：MCP Prompt 是 Server 提供的、可参数化的、可被发现的提示词模板。它不是写死在某个 Agent 里，而是"挂"在 Server 上，谁连上来都能用。

```python
# Week 06：prompt 写死在 Agent 里，换不了
agent = create_agent(
    system_prompt="你是徒步规划助手...",  # ← 这个 Agent 专用
)

# MCP：prompt 挂在 Server 上，任何 Client 都能调
@server.prompt()
async def route_analysis(route_name: str) -> str:  # ← 可参数化
    """路线分析提示词模板"""
    return f"你是徒步路线分析专家。请分析路线：{route_name}..."
```

> **前端类比：** Week 06 的 system_prompt 就像组件里写死的 props，MCP 的 Prompt 就像从 API 动态获取的配置——组件不变，但配置可以按需加载、参数化传入。

---

## 二、手写完整 MCP Server

### 2.1 场景设定：徒步路线查询服务

我们写一个"徒步路线查询 MCP Server"，叫 `hiking-route-server`。它对外暴露三种能力：

```
hiking-route-server
├── Tool:     search_routes(difficulty, days)   → 搜索徒步路线
├── Resource: route://config                    → 读取路线配置
└── Prompt:   route_analysis(route_name)        → 路线分析提示词模板
```

### 2.2 完整代码

下面是完整代码，每个部分都有注释，对应三种能力：

```python
"""my_mcp_server.py — 完整的 MCP Server

暴露三种能力：
1. Tool:     search_routes（搜索徒步路线）
2. Resource: route://config（读取路线配置）
3. Prompt:   route_analysis（路线分析提示词模板）

运行方式：python my_mcp_server.py
它会通过 stdio 等待 Client 连接。
"""
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Resource, Prompt

# 创建一个名为 "hiking-route-server" 的 MCP Server 实例
server = Server("hiking-route-server")


# ─── 1. Tool: 可调用的函数 ──────────────────────────────
# @server.tool() 装饰器把一个普通函数注册为 MCP 工具
# 和 Week 06 的 @tool 一样：函数名→工具名，docstring→描述，类型注解→参数schema
@server.tool()
async def search_routes(difficulty: str, days: int) -> str:
    """搜索徒步路线。

    Args:
        difficulty: 难度等级（休闲/进阶/硬核）
        days: 徒步天数
    """
    # 模拟一个路线数据库
    routes = {
        "休闲": ["青城山后山1日", "白水河2日", "赵公山1日"],
        "进阶": ["长穿毕3日", "四姑娘山二峰3日", "九顶山2日"],
        "硬核": ["贡嘎大环线7日", "狼塔C线8日", "鳌太线5日"],
    }
    matched = routes.get(difficulty, [])
    return f"推荐{difficulty}路线（{days}天）：{matched}"


# ─── 2. Resource: 可读取的数据源 ────────────────────────
# @server.resource(uri) 装饰器把一个函数注册为资源
# 参数是 URI，Client 通过这个 URI 来读取资源
# Resource 是"只读"的——它不执行动作，只是返回一份数据
@server.resource("route://config")
async def get_route_config() -> str:
    """读取路线配置信息"""
    return """路线配置：
- 数据源：本地路线数据库
- 更新时间：2026-07
- 支持区域：川西、川藏、云南
- 难度分级：休闲/进阶/硬核
- 路线总数：9 条
"""


# ─── 3. Prompt: 预定义提示词模板 ────────────────────────
# @server.prompt() 装饰器把一个函数注册为提示词模板
# 函数参数就是模板的参数，Client 调用时传入具体值
@server.prompt()
async def route_analysis(route_name: str) -> str:
    """路线分析提示词模板

    Args:
        route_name: 要分析的路线名称
    """
    return f"""你是一个徒步路线分析专家。请分析以下路线：
路线名：{route_name}

分析维度：
1. 难度评估（海拔、距离、地形）
2. 季节适宜性（几月去最好）
3. 风险点提示（高反、天气突变、迷路）
4. 装备建议（必备装备清单）
5. 体能要求（需要什么训练基础）

请给出专业、详细的分析报告。
"""


# ─── 启动 Server ────────────────────────────────────────
if __name__ == "__main__":
    # stdio_server 让 Server 通过标准输入/输出通信
    # MCP Client（如 Claude Code）会通过 stdin/stdout 和它交互
    stdio_server(server)
```

### 2.3 三个装饰器对比

三种能力分别用三个不同的装饰器注册，它们的机制对比如下：

| 装饰器 | 注册为 | Client 调用方式 | 参数来源 | 返回值 |
|--------|--------|----------------|---------|--------|
| `@server.tool()` | Tool | `tools/call`（LLM 自动调） | LLM 从 schema 推断参数 | 函数返回值（字符串） |
| `@server.resource(uri)` | Resource | `resources/read`（按 URI 读） | URI 本身 | 函数返回值（数据内容） |
| `@server.prompt()` | Prompt | `prompts/get`（Client 显式调） | Client 传入参数 | 函数返回值（提示词文本） |

> **关键理解：** Tool 的调用方是 LLM（模型自己决定何时调），Resource 和 Prompt 的调用方通常是 Client 应用（如 Claude Code 的用户界面）。Tool 是"给模型用的"，Resource 和 Prompt 更偏"给应用/用户用的"。

### 2.4 和 Week 06 @tool 的代码对比

把同一个 `search_routes` 分别用 Week 06 的 `@tool` 和 MCP 的 `@server.tool()` 写一遍，感受差异：

```python
# ── Week 06：@tool，同进程，只能给本进程的 Agent 用 ──
from langchain.tools import tool

@tool
def search_routes(region: str, days: int) -> str:
    """检索徒步路线。region 为区域，days 为天数。"""
    return f"{region} {days}天路线：A/B/C"

# 只能在这个 Python 进程里用
agent = create_agent(tools=[search_routes], ...)


# ── Week 08：@server.tool()，跨进程，任何 Client 都能用 ──
from mcp.server import Server

server = Server("hiking-server")

@server.tool()
async def search_routes(difficulty: str, days: int) -> str:
    """搜索徒步路线。difficulty 为难度，days 为天数。"""
    return f"推荐{difficulty}路线（{days}天）"

# Claude Code、Cursor、任何 MCP Client 都能调用
```

核心差异：`@tool` 产出的工具只能在本进程用，`@server.tool()` 产出的工具挂在 Server 上，跨进程标准协议调用。写法几乎一样，但"服务范围"天差地别。

---

## 三、工具发现机制

### 3.1 Client 连接后的第一步：发现

MCP Client（比如 Claude Code）连接上你的 Server 之后，第一件事不是调用工具，而是**发现**——查询这个 Server 到底有哪些 Tool、Resource、Prompt 可用。

```
MCP Client                          MCP Server
   │                                    │
   │  ① 建立连接（stdio / SSE）         │
   │ ─────────────────────────────────► │
   │                                    │
   │  ② tools/list（发现所有工具）       │
   │ ─────────────────────────────────► │
   │  ◄── [search_routes, ...]         │  返回工具描述列表
   │                                    │
   │  ③ resources/list（发现所有资源）   │
   │ ─────────────────────────────────► │
   │  ◄── [route://config, ...]        │  返回资源 URI 列表
   │                                    │
   │  ④ prompts/list（发现所有提示词）   │
   │ ─────────────────────────────────► │
   │  ◄── [route_analysis, ...]        │  返回提示词列表
   │                                    │
   │  ⑤ LLM 根据工具描述决定何时调用     │
   │     tools/call search_routes       │
   │ ─────────────────────────────────► │
   │  ◄── "推荐进阶路线：长穿毕3日..."  │  执行工具，返回结果
   │                                    │
```

### 3.2 三种发现请求

发现机制靠三个标准的 JSON-RPC 请求：

| 请求 | 作用 | 返回内容 |
|------|------|---------|
| `tools/list` | 列出所有工具 | 每个工具的 name、description、inputSchema |
| `resources/list` | 列出所有资源 | 每个资源的 URI、name、description |
| `prompts/list` | 列出所有提示词 | 每个提示词的 name、description、arguments |

Client 拿到这些描述后，把它们"喂"给 LLM。LLM 看了工具的 name 和 description，就知道"哦，这个 Server 有个 `search_routes` 工具，能搜徒步路线"——然后用户问相关问题时，LLM 就会决定调用它。这和 Week 06 的 `@tool` 机制一模一样，只不过 Week 06 是本进程的函数列表，MCP 是跨进程发现来的。

### 3.3 模拟 Client 发现工具的过程

下面用伪代码模拟 Client 发现工具的完整过程：

```python
# client_discover_demo.py — 模拟 Client 发现工具的过程
"""模拟 MCP Client 如何发现 Server 的工具

这是伪代码，展示发现机制的逻辑流程。
实际使用时，Client（如 Claude Code）会自动完成这些步骤。
"""
import asyncio
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def discover_tools():
    """连接 Server 并发现它的三种能力"""

    # 配置 Server 的启动方式
    server_params = StdioServerParameters(
        command="python",
        args=["my_mcp_server.py"],
    )

    # 连接 Server
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 初始化连接
            await session.initialize()

            # ── 1. 发现工具 ──
            print("=" * 50)
            print("发现工具 (tools/list)")
            print("=" * 50)
            tools_result = await session.list_tools()
            for tool in tools_result.tools:
                print(f"  工具名: {tool.name}")
                print(f"  描述:   {tool.description}")
                print(f"  参数:   {tool.inputSchema}")
                print()

            # ── 2. 发现资源 ──
            print("=" * 50)
            print("发现资源 (resources/list)")
            print("=" * 50)
            resources_result = await session.list_resources()
            for resource in resources_result.resources:
                print(f"  URI:  {resource.uri}")
                print(f"  名称: {resource.name}")
                print()

            # ── 3. 发现提示词 ──
            print("=" * 50)
            print("发现提示词 (prompts/list)")
            print("=" * 50)
            prompts_result = await session.list_prompts()
            for prompt in prompts_result.prompts:
                print(f"  名称: {prompt.name}")
                print(f"  描述: {prompt.description}")
                print()

            # ── 4. 实际调用一个工具 ──
            print("=" * 50)
            print("调用工具: search_routes(difficulty='进阶', days=3)")
            print("=" * 50)
            result = await session.call_tool(
                "search_routes",
                arguments={"difficulty": "进阶", "days": 3},
            )
            print(f"  结果: {result.content[0].text}")


if __name__ == "__main__":
    asyncio.run(discover_tools())
```

运行后你会看到类似这样的输出：

```
==================================================
发现工具 (tools/list)
==================================================
  工具名: search_routes
  描述:   搜索徒步路线。
  参数:   {'type': 'object', 'properties': {'difficulty': ...}}

==================================================
发现资源 (resources/list)
==================================================
  URI:  route://config
  名称: get_route_config

==================================================
发现提示词 (prompts/list)
==================================================
  名称: route_analysis
  描述: 路线分析提示词模板

==================================================
调用工具: search_routes(difficulty='进阶', days=3)
==================================================
  结果: 推荐进阶路线（3天）：['长穿毕3日', '四姑娘山二峰3日', '九顶山2日']
```

> **前端类比：** 工具发现就像浏览器的服务发现。你访问一个网站前不知道它有哪些 API，先发个 OPTIONS 请求看看支持哪些方法。MCP Client 也是先 `tools/list` 看看 Server 有什么，再决定调什么。

---

## 四、接入 Claude Code 验证

### 4.1 为什么接入 Claude Code

写了 MCP Server 不接入一个真实 Client 验证，等于没写。Claude Code 是目前最主流的 MCP Host 之一——它既是 Agent 又是 MCP Host，能连接外部 MCP Server 获取工具能力。把我们写的 `hiking-route-server` 接入 Claude Code，就能在对话中直接调用我们的工具。

### 4.2 配置方式

Claude Code 通过配置文件管理 MCP Server。配置文件位置：

- 项目级：`.claude/settings.json` 或项目根目录的 `claude_desktop_config.json`
- 全局级：用户主目录下的 Claude Code 配置

配置内容：

```json
{
  "mcpServers": {
    "hiking-routes": {
      "command": "python",
      "args": ["e:/workspace/project/myAIAgentLearning/week08/my_mcp_server.py"]
    }
  }
}
```

字段说明：

| 字段 | 说明 | 示例 |
|------|------|------|
| `mcpServers` | 所有 MCP Server 的配置根 | - |
| `hiking-routes` | 给这个 Server 起的名字（自定义） | Claude Code 用它标识这个 Server |
| `command` | 启动命令 | `python`、`node`、`uv` 等 |
| `args` | 启动参数 | 你的 Server 脚本路径 |

### 4.3 配置后的流程

配置好之后重启 Claude Code，它会在启动时：

```
Claude Code 启动
    │
    ▼
读取配置文件 → 发现 hiking-routes 这个 MCP Server
    │
    ▼
执行 python my_mcp_server.py → 启动你的 Server 进程
    │
    ▼
通过 stdio 建立连接 → 发 tools/list 发现工具
    │
    ▼
拿到 search_routes 的描述 → 塞进 LLM 上下文
    │
    ▼
用户问："帮我搜索进阶3天的徒步路线"
    │
    ▼
LLM 看到工具描述 → 决定调用 search_routes
    │
    ▼
Claude Code 发 tools/call → 你的 Server 执行 → 返回结果
    │
    ▼
LLM 拿到结果 → 组织回答给用户
```

### 4.4 实际验证

在 Claude Code 里输入以下内容测试：

```
帮我搜索进阶3天的徒步路线
```

如果一切正常，Claude Code 会调用你的 `search_routes` 工具，返回类似这样的回答：

```
我帮你搜索了进阶难度、3天的徒步路线，找到以下推荐：
- 长穿毕3日
- 四姑娘山二峰3日
- 九顶山2日
```

你也可以测试 Resource 和 Prompt：

```
读取路线配置      → Claude Code 会通过 resources/read 读取 route://config
分析贡嘎大环线    → Claude Code 会用 route_analysis 提示词模板
```

> **成就感时刻：** 这是你在 12 周学习里第一次让"自己写的工具"被一个真实的 AI 产品调用。Week 06 的 `@tool` 只能在你自己的 Python 脚本里跑，现在你写的工具被 Claude Code 这个真实产品发现了、调用了——这就是 MCP 的价值：工具变成跨产品、跨进程的标准服务。

---

## 动手实验

### 🟢 青铜：用 MCP Inspector 查看工具列表

运行 Day 01 的最小 MCP Server，然后用 MCP Inspector（官方调试工具）连接它，查看它的工具列表。

```bash
# 安装 MCP Inspector（如果没有的话）
npx @modelcontextprotocol/inspector python my_mcp_server.py
```

打开 Inspector 的 Web 界面后：
1. 点击 "List Tools" 查看所有工具
2. 点击 "List Resources" 查看所有资源
3. 点击 "List Prompts" 查看所有提示词
4. 尝试调用 `search_routes`，传入 `difficulty=进阶`、`days=3`

目标：理解"发现"这一步到底发生了什么，亲眼看到 Server 暴露的三种能力。

### 🟡 白银：完成 my_mcp_server.py

完成本文第二节的完整 `my_mcp_server.py`，暴露 Tool + Resource + Prompt 三种能力。然后：

1. 确保代码能正常运行（`python my_mcp_server.py` 不报错）
2. 用 MCP Inspector 连接，验证三种能力都被正确发现
3. 尝试添加第二个工具，比如 `get_route_detail(route_name)` 返回某条路线的详细信息

```python
# 额外挑战：添加第二个工具
@server.tool()
async def get_route_detail(route_name: str) -> str:
    """获取某条路线的详细信息。

    Args:
        route_name: 路线名称
    """
    details = {
        "长穿毕3日": "海拔3200-4600m，全程约40km，翻越垭口3个",
        "贡嘎大环线7日": "海拔2900-4920m，全程约120km，需高原适应",
    }
    return details.get(route_name, f"暂无 {route_name} 的详细信息")
```

### 🔴 王者：接入 Claude Code 实际调用

把你的 MCP Server 接入 Claude Code，实际用对话调用你的工具。步骤：

1. 在项目根目录创建或编辑 `.claude/settings.json`，配置 `hiking-routes` Server
2. 重启 Claude Code
3. 在对话中测试以下三个场景：
   - "帮我搜索硬核7天的徒步路线" → 验证 Tool
   - "读取路线配置" → 验证 Resource
   - "用路线分析模板分析贡嘎大环线" → 验证 Prompt
4. 观察 Claude Code 是否正确发现并调用了你的工具
5. 在日志中确认 `tools/call` 请求确实发到了你的 Server

如果调用成功，恭喜你——你已经写了一个能被真实 AI 产品使用的工具服务。

---

## 踩坑记录 🕳️

### 坑 1：stdio 传输中用了 print() 污染 stdout

这是新手最常踩的坑。MCP 的 stdio 传输方式用 stdout 传递协议消息，如果你在代码里写了 `print("调试信息")`，这条信息会被 Client 当成协议消息解析，直接报错或连接断开。

```python
# 错误写法：print 会污染 stdout
@server.tool()
async def search_routes(difficulty: str) -> str:
    print(f"收到查询：{difficulty}")  # ← 这会搞坏通信！
    return f"推荐{difficulty}路线"

# 正确写法：用 logging 输出到 stderr
import logging
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

@server.tool()
async def search_routes(difficulty: str) -> str:
    logging.debug(f"收到查询：{difficulty}")  # ← stderr 不影响通信
    return f"推荐{difficulty}路线"
```

**解决：** stdio 传输模式下，所有日志输出走 `logging` 到 `stderr`，绝对不要用 `print()`。stdout 是协议通道，只能给 MCP 消息用。这是 stdio 传输的铁律。

### 坑 2：async 函数和 sync 函数写法混淆

MCP SDK 的工具函数是 `async def`，如果你写成普通 `def`，或者忘了 `await`，会报错或行为异常。

```python
# 错误：忘了 async
@server.tool()
def search_routes(difficulty: str) -> str:  # ← 缺少 async
    return f"推荐{difficulty}路线"

# 正确：async def
@server.tool()
async def search_routes(difficulty: str) -> str:
    return f"推荐{difficulty}路线"
```

**解决：** MCP Server 的工具函数统一用 `async def`。如果你函数内部要调异步 IO（如查数据库、发请求），记得 `await`。如果你不确定，先写成 async，跑起来看报错信息再调。

### 坑 3：Claude Code 的配置文件格式因版本不同

Claude Code 的 MCP 配置经历过几次格式变化。有的版本用 `.claude/settings.json`，有的用 `claude_desktop_config.json`，有的用 `.mcp.json`。配置结构也略有差异。

**解决：** 以你当前安装的 Claude Code 版本文档为准。一般原则：
- 先查 `claude --version` 确认版本
- 去 Claude Code 官方文档搜 "MCP configuration" 看当前版本要求的格式
- 配置后重启 Claude Code，在对话中输入 `/mcp` 查看 Server 连接状态

### 坑 4：Resource 的 URI 格式不规范

Resource 的 URI 是 Client 读取资源的"地址"。如果格式不规范，Client 可能无法正确解析。

```python
# 不规范：URI 没有协议前缀
@server.resource("config")  # ← 缺少协议前缀，Client 不好解析
async def get_config() -> str:
    return "配置内容"

# 规范：URI 带协议前缀
@server.resource("route://config")  # ← route:// 是自定义协议
async def get_config() -> str:
    return "配置内容"
```

**解决：** URI 格式遵循 `scheme://path` 的规范。可以用自定义 scheme（如 `route://`、`db://`、`file://`），但必须有 `://` 分隔符。常见的有 `file:///path`、`config://app`、`db://table/row`。

---

## 副线笔记

### Claude Code 的 MCP 集成：既是 Agent 又是 MCP Host

对比 Claude Code 的 MCP 集成架构，你会发现一个有趣的事实：Claude Code 既是 Agent 又是 MCP Host。

```
┌─────────────────────────────────────────────────────┐
│                    Claude Code                       │
│                                                     │
│   ┌──────────┐    ┌────────────────────────────┐   │
│   │  Agent    │    │       MCP Host             │   │
│   │  (LLM)    │    │  ┌────────┐ ┌──────────┐  │   │
│   │           │◄──►│  │ MCP    │ │ MCP      │  │   │
│   │  推理决策  │    │  │ Client │ │ Client   │  │   │
│   └──────────┘    │  └───┬────┘ └────┬─────┘  │   │
│                    └─────┼───────────┼─────────┘   │
└──────────────────────────┼───────────┼─────────────┘
                           │           │
                    ┌──────▼───┐ ┌─────▼──────┐
                    │ 你的 MCP │ │ 官方 MCP   │
                    │  Server  │ │  Server    │
                    │ (徒步路线)│ │ (文件系统) │
                    └──────────┘ └────────────┘
```

这意味着什么？你在 Claude Code 里用的每个工具，背后可能是一个 MCP Server。文件读写、代码搜索、终端执行……这些"Claude Code 自带"的能力，底层可能就是通过 MCP 连接的内置 Server。而你自己写的 MCP Server，和这些"官方"的 Server 在 Claude Code 眼里是平等的——都是通过 `tools/list` 发现、通过 `tools/call` 调用的标准工具。

> **洞察：** 这就是协议标准化的力量。在 MCP 之前，每个 AI 工具要接外部能力都得自己定义一套接口。有了 MCP，你的徒步路线 Server 和 Anthropic 官方的文件系统 Server 用的是同一套协议——Claude Code 不用关心你是谁写的、用什么语言写的，它只知道"连上、发现、调用"。就像 HTTP 让所有网站互联，MCP 让所有 AI 工具的能力互通。

---

## 检查清单

- [ ] 理解 MCP Server 的三种能力（Tool / Resource / Prompt），能说清各自解决什么问题
- [ ] 能区分 Tool（执行动作）和 Resource（读取数据）的关键差异
- [ ] 理解 MCP Prompt 和 Week 06 system_prompt 的区别（Server 提供 vs Agent 写死）
- [ ] 完成了 `my_mcp_server.py`，暴露三种能力
- [ ] 理解工具发现机制（`tools/list` / `resources/list` / `prompts/list`）
- [ ] 知道 stdio 传输中不能用 `print()`，要用 `logging` 到 `stderr`
- [ ] 成功接入 Claude Code（或至少知道怎么配置）
- [ ] 在 Claude Code 里实际调用过自己写的工具

---

## 下课预告

> **Day 03 — Skills 概念：Skill vs Tool vs MCP vs Prompt。** 今天你写了 MCP Server 暴露 Tool / Resource / Prompt 三种能力。明天我们换一个视角——Tool 是"接口"，Skill 是"能力包"。Claude Code 的 Skills 不是 Week 07 LangChain 的 Skills（同名不同物），它是一个 SKILL.md 文件，告诉 Agent "怎么完成一类任务"。你会学到：Skill 和 Tool/MCP/Prompt 的本质区别、SKILL.md 的标准结构、以及为什么 2026 年 Agent 生态开始从"工具接口"转向"能力包"。副线阅读 Claude Code 官方 Skills 文档，理解它的可发现、可版本化特性。
