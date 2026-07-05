# Day 02 — 工具调用深入：@tool / ToolRuntime / 状态注入

## 学习目标

Day 01 介绍了 LCEL 链式组装，但 Agent 的核心是"模型+工具"的交互循环。今天从 Week 03 手写 Function Calling 出发，切入 LangChain 2026 年的工具系统：`@tool` 装饰器用函数签名 + docstring 自动生成 tool schema；`ToolRuntime` 运行时注入让工具能读写 Agent 状态、长期记忆、流式输出——这些在 Week 03 手写时要么做不到、要么需要大量样板代码。配套产出 `tool_calling_demo.py`。

学完今天你能：
1. 用手写 JSON Schema + 注册表的痛点对比，说清 `@tool` 替我省了哪几大块体力活
2. 用 `@tool` 定义带类型注解和 Pydantic 参数约束的工具，并解释 schema 从哪来的
3. **用 `ToolRuntime` 在工具函数里访问 Agent 状态、长期记忆、流式写入——这是 2026 年新 API，也是今天最重要的一条**
4. 把工具列表传给 `create_agent`，让框架自动管理 tool 调用循环，说清对比手写省了多少代码

---

## 一、回顾 Week 03 手写 Function Calling：四个痛点

Week 03 Day 02 我们纯手写了一整套 Function Calling：`httpx` 调 OpenAI API、手写 JSON Schema、手动解析 `tool_calls`、手动 dispatch、手动构造 tool 角色消息。当时这么干是为了"看穿黑盒"，但也付出了四笔重复劳动。

### 痛点 1：手写 JSON Schema，改一处漏一处

每个工具要写 20 多行的 JSON Schema 字典，`name / description / parameters / properties / required` 一个字段不能少。改一个参数名，得同步改函数签名和 Schema 两处。

```python
# Week 03 手写：一个工具的 JSON Schema 就要 20+ 行
get_weather_schema = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "获取指定城市的当前天气信息",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"],
                         "description": "温度单位，默认 celsius"},
            },
            "required": ["city"],
        },
    },
}
```

### 痛点 2：手动解析 tool_calls + json.loads

OpenAI 返回的 `arguments` 是**字符串不是字典**，每次都要 `json.loads` 再解包，类型错误是高频 bug。

```python
# Week 03 手写：arguments 是字符串，必须 json.loads
tool_calls = response["choices"][0]["message"]["tool_calls"]
for tc in tool_calls:
    name = tc["function"]["name"]
    args = json.loads(tc["function"]["arguments"])  # ← 字符串！容易忘
```

### 痛点 3：手动维护注册表 + dispatch

每个工具要手动注册到 `TOOL_REGISTRY`，dispatch 时查表 + `**kwargs` 解包 + try/except，每加一个工具都要三处修改（Schema + impl + 注册表）。

### 痛点 4：手动构造 tool 角色消息 + 维护消息顺序

结果要包成 `{"role": "tool", "tool_call_id": "...", "content": "..."}` 字典，带 `tool_calls` 的 assistant 消息也必须回填，顺序错了（ToolMessage 在 AIMessage 前面）API 直接 422。

### 痛点总结表

| 维度 | Week 03 手写 | 代码量 | 根本问题 |
|------|-------------|--------|---------|
| **Schema 定义** | 手写 JSON Schema 字典 | 约 22 行/工具 | 函数定义与 Schema 分离，改一处漏一处 |
| **tool_calls 解析** | `json.loads(arguments)` 字符串拆包 | 约 5 行/次 | 字符串/字典类型混淆，运行时才能发现 |
| **注册与 dispatch** | 手动 `TOOL_REGISTRY` 注册表 + 查表执行 | 约 40 行 | 每加工具需改三处，耦合高 |
| **消息构造** | 手动构造 tool 角色字典 + 维护消息顺序 | 约 20 行 | 顺序错了 API 报 422，无编译期检查 |

LangChain 2026 的工具系统把上面 4 个痛点全部消灭：`@tool` 自动生成 Schema、自动注册；`create_agent` 自动管理 tool_choice 解析 + dispatch + 消息回填；`ToolRuntime` 更是手写时代完全无法实现的能力。

---

## 二、@tool 装饰器：函数签名 + 类型注解 → 自动 tool schema

### 2.1 一句话原理

`@tool` 的魔法在于：它从**函数名 → name**、**docstring → description**、**类型注解 → parameters 的 properties** 三处自动推断，你不用再手写一行 JSON Schema。

```python
"""tool_calling_demo.py — 第一部分：@tool 基础定义"""
from langchain.tools import tool


@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。city 为城市名，如 '北京'、'Tokyo'。"""
    weather_db = {"北京": "晴 25°C", "Tokyo": "小雨 18°C", "上海": "多云 28°C"}
    return weather_db.get(city, f"{city}：暂无天气数据")
```

装饰完后，`get_weather` 不再是普通函数，而是一个 `BaseTool` 对象：

```python
print(get_weather.name)         # 'get_weather'                    ← 取自函数名
print(get_weather.description)  # '查询指定城市的当前天气...'       ← 取自 docstring
print(get_weather.args)         # {'city': {'type': 'string'}}     ← 取自类型注解
```

### 2.2 Schema 推断规则

| Schema 字段 | 来源 | 说明 |
|------------|------|------|
| `name` | 函数名 | 可用 `@tool("自定义名")` 覆盖 |
| `description` | docstring 第一行 / 全文 | **没有 docstring 就没有 description**，LLM 会瞎猜或不调 |
| 参数名 | 函数形参 | 直接作为 JSON Schema 的 property 名 |
| 参数类型 | 类型注解 `: str / : int / : float` | `str/int/float/bool/list/dict` 都能推断 |
| `required` | 没有默认值的形参 | 没有默认值的参数自动标为 required |
| 参数描述 | docstring 的 `Args:` 段 | Google 风格 docstring 的 `Args:` 会被解析进每个参数的 description |

### 2.3 三个工具示例

下面定义三个工具，覆盖"简单参数 / Pydantic 约束 / 纯文本返回"三种场景：

```python
"""tool_calling_demo.py — 第二部分：三个工具定义"""

# ── 工具 1：纯类型注解，简单参数 ──────────────────────
@tool
def get_weather(city: str, unit: str = "celsius") -> str:
    """查询指定城市的当前天气。

    Args:
        city: 城市名，如 '北京'、'上海'。
        unit: 温度单位，'celsius'（默认）或 'fahrenheit'。
    """
    weather_db = {"北京": (25, "晴"), "上海": (28, "多云"), "Tokyo": (18, "小雨")}
    temp, cond = weather_db.get(city, (20, "未知"))
    if unit == "fahrenheit":
        temp = temp * 9 // 5 + 32
    return f"{city}：{cond}，{temp}°{'F' if unit == 'fahrenheit' else 'C'}"


# ── 工具 2：Pydantic BaseModel + Field 做参数约束 ──────
from pydantic import BaseModel, Field


class SearchRoutesInput(BaseModel):
    """路线检索工具的输入参数。"""
    location: str = Field(description="徒步起点，如 '北京'、'杭州'")
    difficulty: str = Field(
        description="难度等级",
        enum=["easy", "medium", "hard"],      # ← 枚举约束，LLM 只能选这三个
    )
    max_results: int = Field(default=3, ge=1, le=10, description="返回路线数，1-10")


@tool(args_schema=SearchRoutesInput)
def search_routes(location: str, difficulty: str, max_results: int = 3) -> str:
    """根据地点和难度检索徒步路线。当用户想找徒步/爬山路线时使用。

    Args:
        location: 起点地名
        difficulty: 难度等级 easy / medium / hard
        max_results: 返回的最大路线数
    """
    routes = {
        ("北京", "easy"): ["香山", "百望山", "奥林匹克森林公园"],
        ("杭州", "hard"): ["千八穿越", "天目山七尖"],
    }
    hits = routes.get((location, difficulty), [f"{location} 暂无 {difficulty} 路线"])
    return f"为 {location}({difficulty}) 找到 {len(hits[:max_results])} 条：{'、'.join(hits[:max_results])}"


# ── 工具 3：纯函数，返回文本 ──────────────────────────
@tool
def calculate_distance(start: str, end: str) -> str:
    """计算两个地点之间的直线距离（公里）。用于规划出行路线。

    Args:
        start: 起点地名
        end: 终点地名
    """
    dist_table = {("北京", "上海"): 1213, ("北京", "Tokyo"): 2100, ("杭州", "上海"): 175}
    d = dist_table.get((start, end)) or dist_table.get((end, start), None)
    if d is None:
        return f"暂无 {start} ↔ {end} 的距离数据"
    return f"{start} → {end} 直线距离约 {d} 公里"
```

### 2.4 args_schema 高级用法：Pydantic Field

当工具参数有**枚举值、数值范围、复杂嵌套**时，用 Pydantic `Field` 比纯类型注解更稳：

```python
from pydantic import BaseModel, Field
from typing import Literal


class BookHotelInput(BaseModel):
    city: str = Field(description="城市名，如 '北京'")
    hotel_name: str = Field(description="酒店名称")
    room_type: Literal["single", "double", "suite"] = Field(
        default="double", description="房型"
    )
    nights: int = Field(default=1, ge=1, le=30, description="入住晚数，1-30")


@tool(args_schema=BookHotelInput)
def book_hotel(city: str, hotel_name: str, room_type: str = "double", nights: int = 1) -> str:
    """预订酒店房间。当用户需要订酒店时使用。"""
    return f"已预订 {city} {hotel_name} {room_type}房 × {nights}晚"
```

`Field` 的 `enum` / `ge` / `le` / `description` 会被 LangChain 自动映射到 JSON Schema 的 `enum` / `minimum` / `maximum` / `description` 字段，LLM 能直接看到约束，大幅提高参数合规率。

---

## 三、ToolRuntime 运行时注入（2026 年新 API——重点）

### 3.1 什么是 ToolRuntime

`ToolRuntime` 是 LangChain 2026 年引入的**运行时上下文注入**机制。工具函数的参数名只要写成 `runtime: ToolRuntime`，LangChain 就会自动注入一个 `ToolRuntime` 对象——这个参数**不会暴露给 LLM**，LLM 看不到它、不会尝试填充它。

```python
from langchain.tools import tool, ToolRuntime
```

### 3.2 ToolRuntime 可访问的资源

| 属性 | 类型 | 用途 | 示例 |
|------|------|------|------|
| `runtime.state` | `dict` | 当前 Agent 状态（messages + 自定义字段） | `runtime.state["messages"]` |
| `runtime.context` | `dict` | 调用时传入的不可变上下文（用户 ID 等） | `runtime.context.get("user_id")` |
| `runtime.store` | `BaseStore` | 长期记忆，跨会话持久 | `await runtime.store.aput(...)` |
| `runtime.stream_writer` | `Callable` | 实时流式更新 | `runtime.stream_writer("进度: 50%")` |
| `runtime.execution_info` | `dict` | 执行信息（thread_id, run_id, node_attempt） | `runtime.execution_info["thread_id"]` |
| `runtime.tool_call_id` | `str` | 当前工具调用的 ID | 匹配 ToolMessage 的 tool_call_id |

### 3.3 用 ToolRuntime 访问 Agent 状态

```python
"""tool_calling_demo.py — 第三部分：ToolRuntime 访问状态和上下文"""

@tool
def check_user_history(query: str, runtime: ToolRuntime) -> str:
    """检查用户历史记录中是否已有相关信息，避免重复查询。

    Args:
        query: 用户的查询内容
    """
    # 1) 读取 Agent 当前状态中的消息历史
    messages = runtime.state.get("messages", [])
    history_count = len(messages)
    user_msg_count = sum(1 for m in messages if getattr(m, "type", "") == "human")

    # 2) 读取调用时传入的不可变上下文
    user_id = runtime.context.get("user_id", "anonymous")
    session_id = runtime.context.get("session_id", "unknown")

    # 3) 读取执行信息
    thread_id = runtime.execution_info.get("thread_id", "N/A")

    # 4) 流式输出进度（前端可实时显示）
    runtime.stream_writer(f"正在查询用户 {user_id} 的历史记录...")

    # 模拟历史查询
    return (
        f"用户 {user_id}（会话 {session_id}，线程 {thread_id}）：\n"
        f"本轮已有 {history_count} 条消息（其中用户发了 {user_msg_count} 条）。\n"
        f"查询词 '{query}' 的历史匹配结果：无重复记录。"
    )
```

### 3.4 用 ToolRuntime 访问长期记忆（store）

`runtime.store` 是一个 `BaseStore` 接口，支持跨会话的持久化键值存取：

```python
"""tool_calling_demo.py — 第四部分：ToolRuntime 长期记忆"""

@tool
def remember_preference(key: str, value: str, runtime: ToolRuntime) -> str:
    """保存用户的偏好设置到长期记忆。

    Args:
        key: 偏好键名，如 'preferred_unit'、'home_city'
        value: 偏好值
    """
    # 写入 store（跨会话持久）
    # 注意：BaseStore 接口是异步的，但在同步工具中可用 put 的同步变体
    namespace = ("user_prefs", runtime.context.get("user_id", "anonymous"))
    runtime.store.put(namespace, key, value={"value": value})
    runtime.stream_writer(f"已保存 {key} = {value}")

    return f"偏好 '{key}' 已设置为 '{value}'，下次对话仍然有效。"


@tool
def recall_preference(key: str, runtime: ToolRuntime) -> str:
    """从长期记忆中读取用户的偏好设置。

    Args:
        key: 偏好键名
    """
    namespace = ("user_prefs", runtime.context.get("user_id", "anonymous"))
    result = runtime.store.get(namespace, key)

    if result is None:
        return f"未找到偏好 '{key}'，请先使用 remember_preference 保存。"

    value = result.get("value", "未知")
    return f"偏好 '{key}' 的值为 '{value}'。"
```

### 3.5 ToolRuntime 关键设计要点

1. **参数名必须是 `runtime: ToolRuntime`**——框架按参数名匹配注入，其他名字不会被特殊处理。
2. **自动隐藏**——LLM 看不到 `runtime` 参数，不会尝试填充它，不会污染 tool schema。
3. **stream_writer 是回调式的**——写入内容会实时推送给前端（适用于进度条/日志场景），不影响工具返回值。
4. **store 是异步接口**——在同步工具中调用同步变体即可，LangChain 内部会处理好事件循环。

---

## 四、工具执行与 Agent 整合：create_agent

### 4.1 从 bind_tools 到 create_agent

Week 02 Day 02 我们用了 `bind_tools` + 手写 while 循环管理工具调用。2026 年 LangChain 提供了更上层的 `create_agent`，把工具循环完全封装起来：

```python
"""tool_calling_demo.py — 第五部分：create_agent 整合"""
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent

model = init_chat_model("gpt-4o-mini", temperature=0)

# 工具列表
TOOLS = [get_weather, search_routes, calculate_distance, check_user_history]

# 创建 Agent——三行搞定
agent = create_agent(
    model=model,
    tools=TOOLS,
)
```

### 4.2 Agent 自动管理了什么

对比 Week 03 手写 vs `create_agent`：

| 环节 | Week 03 手写（约 80 行） | create_agent（1 行） |
|------|------------------------|---------------------|
| 绑定工具 | 每次请求写 `body["tools"] = TOOLS` | `tools=TOOLS` 传参 |
| tool_choice 解析 | 手动判断 `finish_reason` | 自动根据 `tool_calls` 字段判读 |
| 工具 dispatch | 查 `TOOL_REGISTRY` + `**kwargs` | 框架用 `{tool.name: tool}` 自动映射 |
| 结果打包 | 手动 `ToolMessage(content=..., tool_call_id=...)` | 自动产出 ToolMessage |
| 消息回填 | 手动 append AIMessage + ToolMessage | 自动保障消息顺序 |
| 循环终止 | 手写 `max_iter` + while break | 内置 `max_iterations` 参数 |
| 错误处理 | 手动 try/except 每个工具 | 工具内异常自动字符串化回传 |

### 4.3 调用 Agent

```python
# invoke 时传入 messages 列表 + thread_id
response = agent.invoke(
    {"messages": [("human", "北京今天天气如何？顺便查一下北京有什么 easy 的徒步路线。")]},
    config={"configurable": {"thread_id": "thread-001"}},
)

# 在 ToolRuntime 中通过 context 传入用户 ID 等上下文
response = agent.invoke(
    {"messages": [("human", "帮我查一下我的历史记录。")]},
    config={
        "configurable": {
            "thread_id": "thread-001",
            "user_id": "user_zhang_01",      # ← 自动注入到 runtime.context
            "session_id": "session_abc123",
        }
    },
)
```

### 4.4 对比 Week 03：40 行 vs 3 行

```python
# ── Week 03 手写：约 40 行样板 ──
def run_week03_agent(user_input: str) -> str:
    messages = [{"role": "user", "content": user_input}]
    for _ in range(5):
        response = httpx.post(URL, headers=HEADERS, json={
            "model": "gpt-4o-mini",
            "messages": messages,
            "tools": TOOL_SCHEMAS,
        }).json()
        msg = response["choices"][0]["message"]
        if msg.get("finish_reason") != "tool_calls":
            return msg["content"]
        messages.append({"role": "assistant", "content": msg.get("content", "")})
        for tc in msg["tool_calls"]:
            name, args = tc["function"]["name"], json.loads(tc["function"]["arguments"])
            result = TOOL_REGISTRY[name](**args)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
    return "达到最大轮数"

# ── Week 06 create_agent：约 3 行 ──
agent = create_agent(model=model, tools=TOOLS)
response = agent.invoke(
    {"messages": [("human", user_input)]},
    config={"configurable": {"thread_id": "thread-001"}},
)
```

**关键在于**：`create_agent` 没有改变底层逻辑——它仍然是"调模型→解析 tool_calls→执行→回传→再调"的循环。它只是把这个循环从你的代码里搬进了框架里。理解了这个底层，你才不会被框架的抽象困住。

---

## 五、工具设计原则重申

### 5.1 @tool 自动落实 vs 仍需手写

| Week 03 Day 05 六原则 | @tool 是否自动落实 | 说明 |
|----------------------|------------------|------|
| 1. 单一职责 | 否 | 装饰器不管函数干几件事，得自己拆分 |
| 2. 清晰 description | **半自动** | docstring 自动变 `description`，但写不写清楚是你的事 |
| 3. 好参数名 | 否 | 形参名直接当 schema 参数名，命名好坏全看你 |
| 4. 默认值 | **自动** | Python 默认值自动标为可选参数 |
| 5. 错误处理 | 否 | 函数内 try/except 还得自己写 |
| 6. 幂等性 | 否 | 装饰器不区分读/写操作，副作用得自己控 |

### 5.2 好工具 vs 坏工具对比表

```python
# ── ❌ 坏工具：docstring 敷衍、参数缩写、无错误处理 ──
@tool
def search(q: str) -> str:
    """搜索"""
    resp = httpx.get(f"https://api.example.com/search?q={q}")  # 无超时、无异常处理
    return resp.text

# 问题：description 只有"搜索"→ LLM 不知道何时用；
#       参数名 q 有歧义；网络调用无 try/except → 一超时整个 Agent 崩


# ── ✅ 好工具：docstring 写场景、参数全称、内部 try/except ──
@tool
def search_web(query: str, max_results: int = 5) -> str:
    """搜索互联网获取最新信息。当用户问实时新闻、最新文档、或模型训练数据
    未覆盖的事实时使用。query 为搜索词，建议 2-5 个关键词。"""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get("https://api.example.com/search",
                              params={"q": query, "limit": max_results})
            resp.raise_for_status()
            return resp.text[:5000]                      # 限制返回长度，防爆 context
    except httpx.TimeoutException:
        return "错误：搜索超时，建议简化查询词后重试"
    except Exception as e:
        return f"错误：{e}"
```

### 5.3 好工具 vs 坏工具对照

| 维度 | 好工具 | 坏工具 |
|------|--------|--------|
| **docstring** | 写清楚"什么场景调用 + 每个参数的含义" | 敷衍或缺失 |
| **参数名** | 全称、自解释（`query` / `max_results`） | 缩写（`q` / `n`） |
| **类型注解** | 完整标注 `: str / : int` | 缺注解或只用 `: Any` |
| **错误处理** | try/except 捕获 + 字符串化回传 | 裸奔，异常直接抛到顶层 |
| **返回值约束** | 返回短文本（< 5000 字符），防爆 context | 返回长文档或 None |
| **Pydantic 约束** | 枚举/范围用 `Field(enum=, ge=, le=)` | 纯字符串靠 LLM 猜 |

---

## 动手实验

### 🟢 青铜级：用 @tool 定义 + ToolRuntime 读取状态

1. 打开 `tool_calling_demo.py`，把本文第二、三部分的 `get_weather`、`search_routes`、`check_user_history` 三个工具定义完整抄进去。
2. 在文件末尾加一段测试代码，分别打印每个工具的 `name`、`description`、`args`。
3. 特别注意 `check_user_history` 打印出的 `args` 里**没有** `runtime` 参数——验证它被自动隐藏了。

```python
if __name__ == "__main__":
    for t in [get_weather, search_routes, check_user_history]:
        print(f"=== {t.name} ===")
        print(f"  description: {t.description[:60]}...")
        print(f"  args: {t.args}")
```

### 🟡 白银级：用 create_agent 跑通完整对话

1. 把第四部分的 `create_agent` 代码加到 `tool_calling_demo.py`，用 `get_weather` + `search_routes` 两个工具创建 Agent。
2. 调用 `agent.invoke({"messages": [...],}, config={"configurable": {"thread_id": "t1"}})`，输入 "北京今天天气如何？顺便帮我查北京有什么 easy 的徒步路线。"。
3. 观察返回结果，确认 Agent 自动完成了两次工具调用并给出综合回答。
4. （可选）加上 `check_user_history` 工具，在 `configurable` 里传入 `user_id` 和 `session_id`，验证 `runtime.context` 能读到这些值。

### 🔴 王者级：用 ToolRuntime 构建"带记忆的 Agent"

1. 编写一个完整脚本 `memory_agent.py`，包含三个工具：
   - `remember_preference(key, value)`：用 `runtime.store` 写入长期记忆
   - `recall_preference(key)`：用 `runtime.store` 读取长期记忆
   - `get_weather(city, unit)`：查天气
2. 用 `create_agent` 创建 Agent，**在第一次 invoke 中存偏好**，**在第二次 invoke（同一 thread_id）中读偏好**。
3. 验证第二次对话时 Agent 能正确 recall 用户的单位偏好（比如用户说"用华氏度"，第二次查天气自动用了 Fahrenheit）。

> 这个实验充分体现了 ToolRuntime 的价值：手写时代你用全局变量存记忆，会话间会丢失；用文件存又得自己处理序列化。`runtime.store` 把"跨会话持久化"抽象成了一行 `put` / `get`。

---

## 踩坑记录 🕳️

### 坑 1：@tool 忘写 docstring → description 为空 → LLM 不调

```python
@tool
def get_weather(city: str) -> str:
    # 没有 docstring！
    return f"{city} 25°C"

print(get_weather.description)   # '' ← 空字符串
# 结果：LLM 根本不知道这个工具干嘛的，几乎不会调用
```

**解决**：每个 `@tool` 函数第一行必须写 docstring，至少一句"这是什么工具、什么时候用"。没有 docstring = 没有 description = LLM 不会调。

### 坑 2：ToolRuntime 参数名写错或漏类型注解

```python
@tool
def check_history(query: str, runtime):          # ❌ 少了类型注解 : ToolRuntime
    ...

@tool
def check_history(query: str, ctx: ToolRuntime): # ❌ 参数名必须是 runtime，不是 ctx
    ...
```

**解决**：参数名**必须**是 `runtime`，类型注解**必须**是 `: ToolRuntime`。名字错了框架不会注入（当成普通参数暴露给 LLM）；类型错了 IDE 不会提示但框架能通过 `inspect` 匹配。

### 坑 3：在同步工具里直接 await store 的异步方法

```python
@tool
def save_pref(key: str, value: str, runtime: ToolRuntime) -> str:
    # ❌ 同步函数里不能直接 await
    await runtime.store.aput(...)   # SyntaxError: 'await' outside function
```

**解决**：用同步变体 `runtime.store.put(namespace, key, value=...)`。LangChain 的 `BaseStore` 同时提供了同步和异步接口，同步工具里调同步方法即可。

### 坑 4：stream_writer 写了太多内容，把输出淹了

```python
@tool
def long_task(runtime: ToolRuntime) -> str:
    for i in range(100):
        runtime.stream_writer(f"进度: {i}%")  # 前端会被刷屏
    return "完成"
```

**解决**：`stream_writer` 适合写"关键里程碑"而不是"每一步"。建议只在关键节点（开始、完成、错误）或每 10% 写一次，避免高频刷新。

### 坑 5：create_agent 的 configurable 和 context 混用

```python
# ❌ 以为 configurable 的参数会自动变成 runtime.context
agent.invoke(..., config={"configurable": {"my_key": "val"}})
# 结果：runtime.context 里没有 my_key

# ✅ 需要在创建 Agent 时设置 context 映射，或使用更高层的 AgentExecutor
from langchain.agents import create_agent, AgentExecutor
executor = AgentExecutor(agent=agent, tools=TOOLS)
response = executor.invoke(
    {"input": "..."},
    config={"configurable": {"user_id": "zhang_01"}},
)
# ToolRuntime 的 context 来自 AgentExecutor 的 config
```

**解决**：`runtime.context` 需要 Agent 执行器（`AgentExecutor`）正确传递。直接用 `create_agent` 返回的对象 invoke 时，configurable 并不会全部注入 context。推荐用 `AgentExecutor` 封装一层。

---

## 副线笔记：对比 Week 03 手写 Function Calling

### 12 维度详细对比表

| 维度 | Week 03 手写 | Week 06 @tool + ToolRuntime |
|------|-------------|----------------------------|
| **1. Schema 定义** | 手写 20+ 行 JSON Schema | `@tool` + 类型注解自动生成 |
| **2. 参数约束** | JSON Schema 的 `enum` / `required` / `minimum` | Pydantic `Field(enum=, ge=, le=)` |
| **3. tool_calls 解析** | `json.loads(tc["function"]["arguments"])` 字符串->dict | `tc["args"]` 已是 dict，无需手动解析 |
| **4. 工具注册** | 手动维护 `TOOL_REGISTRY[name] = func` | 装饰器自动注册，`tools = [t1, t2]` 直接用 |
| **5. 绑定到模型** | 每次请求手动构造 `body["tools"] = TOOL_SCHEMAS` | `create_agent(model=model, tools=TOOLS)` 一次绑定 |
| **6. 结果回传格式** | 手动构造 `{"role":"tool","tool_call_id":...,"content":...}` 字典 | 框架自动产出 `ToolMessage` |
| **7. 消息顺序保障** | 手写 ensure AIMessage(tool_calls) 在 ToolMessage 之前 | 框架自动保障 |
| **8. 工具循环控制** | 手写 `while` + `max_iter` + `break` | `create_agent` 内置 `max_iterations` 参数 |
| **9. 状态访问** | 不可能——手写时代没有"Agent 状态"的概念 | `runtime.state["messages"]` 直接读取 |
| **10. 运行时上下文** | 只能通过闭包或全局变量传用户 ID | `runtime.context` 自动注入 |
| **11. 长期记忆** | 需要自己实现文件/数据库持久化 | `runtime.store` 一行 `put` / `get` |
| **12. 流式输出** | 不可能——同步返回后才拿到完整结果 | `runtime.stream_writer("进度...")` 实时推送 |
| **单工具代码量** | 约 30 行（Schema + impl + 注册） | 约 5-8 行（@tool + impl） |
| **完整 Agent 代码** | 约 80-120 行 | 约 10 行 |

### 结论：50 行压到 10 行，底层逻辑没变

对比表的前 8 行是"量的变化"——LangChain 把约 50 行的样板代码压到约 10 行。但第 9-12 行是"质的变化"——`ToolRuntime` 提供了手写时代**根本做不到**的能力：工具函数能直接读取 Agent 状态、能接收调用上下文、能访问跨会话持久存储、能实时推送进度。

这是 LangChain 2026 年工具系统最核心的设计进化：**把工具从"纯函数"升级为"有状态运行时的一等公民"**。

但底层的消息循环逻辑没变——"模型返回 tool_calls → 执行 → 回传 ToolMessage → 再调模型"这条流水线，不管是手写 80 行还是框架 10 行，它都在。理解它，框架就是你的工具而不是黑盒。

---

## 今日产出检查清单

- [ ] 用 `@tool` 定义至少 3 个工具，能打印出 `name` / `description` / `args`，且确认 `runtime` 参数不在 `args` 中
- [ ] 用 `ToolRuntime` 在工具中访问 `runtime.state`、`runtime.context`、`runtime.stream_writer`，并验证 `stream_writer` 输出能在终端或前端看到
- [ ] 用 `create_agent(model=model, tools=TOOLS)` 创建 Agent 并跑通一个包含多工具调用的对话
- [ ] 在 `configurable` 中传入 `user_id` 和 `session_id`，在工具中通过 `runtime.context` 读取到它们
- [ ] 能用 12 维度对比表说清 Week 03 手写 vs Week 06 @tool + ToolRuntime 的差异
- [ ] 产出文件 `tool_calling_demo.py` 包含 @tool 定义、ToolRuntime 示例、create_agent 整合三部分

---

> **下一课预告：Day 03 — LangGraph 入门：StateGraph / Node / Edge**。今天我们用 @tool 和 ToolRuntime 把工具的定义和执行升级了，但控制流还靠 create_agent 的内部循环。明天请出 LangGraph：用 `StateGraph` 显式定义状态，用 `Node` 表达每个步骤（调用模型 / 执行工具），用 `Edge` 表达条件分支，把 Agent 循环从"隐式 while"变成"显式图"。你会发现，图不过是把循环的每一行拍平成节点和边——但一旦拍平，复杂控制流的设计和调试就变得无比清晰。
