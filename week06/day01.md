# Day 01 — LangChain 基础：模型 / create_agent / 工具

## 学习目标

Week 03 我们用 httpx 手写过完整的 Agent Loop：手动拼 messages、手动调 API、手动解析 tool_calls、手动 while 循环处理多轮工具调用。那套代码能跑，但每加一个工具、每换一个模型、每想加个记忆功能，都得动底层循环逻辑。今天正式引入 2026 年 LangChain 的推荐 API——`create_agent()`，它把模型、工具、持久化、结构化输出全部封装成一行调用，底层自动用 LangGraph 管理 Agent 循环。同时你也要学会 `init_chat_model` 统一模型接口和 LCEL 管道链，这两者分别是 `create_agent` 的组件基础和理解框架的入口。

学完今天你能：
1. 说清楚 `create_agent()` 的一行调用替代了 Week 03 手写 Agent Loop 里的哪些环节
2. 用 `init_chat_model` 一个函数对接 Ollama / OpenAI / Anthropic，在 `invoke / stream / batch` 间无缝切换
3. 用 `create_agent(model, tools, system_prompt)` 一行创建 Agent，并用 `thread_id` 管理多轮对话会话
4. 区分什么时候用 `create_agent`（需要工具循环），什么时候用 LCEL 简单链（纯推理，无需工具）

---

## 一、为什么用 LangChain：回顾 Week 03 手写 Agent 的痛点

### 1.1 Week 03 我们写过什么

Week 03 你写过两个关键模块：`api_client.py`（手调 LLM API）和 `agent_loop.py`（手写 Tool Calling + while 循环）。

`api_client.py` 里，调一个 LLM 要手动拼 headers、手动拼 payload、手动 `httpx.post`、手动从 `choices[0].message.content` 抠文本、流式还得自己按行解析 SSE 直到 `[DONE]`。结构化输出更繁琐：手动把 Pydantic schema 转成 tools、手动从 `tool_calls[0].function.arguments` 里取 JSON 再 `json.loads`。

`agent_loop.py` 里，Agent 循环是这样写的：

```python
messages = [{"role": "system", "content": "你是一个助手"}]
messages.append({"role": "user", "content": user_input})

while True:
    resp = call_llm(messages)                 # 调 API
    msg = resp["choices"][0]["message"]
    messages.append(msg)

    if not msg.get("tool_calls"):
        break                                  # 没有工具调用 → 输出文本，结束

    for tc in msg["tool_calls"]:
        func_name = tc["function"]["name"]
        args = json.loads(tc["function"]["arguments"])
        result = execute_tool(func_name, args)  # 执行工具
        messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": json.dumps(result, ensure_ascii=False),
        })
    # 继续循环交给模型处理工具结果
```

这一段能让你看清 Agent 的本质——LLM 思考 → 决定调工具 → 执行 → 把结果给 LLM → 直到 LLM 给出最终文本。但它的问题会随项目变大而爆发。

### 1.2 四大痛点

| 痛点 | Week 03 手写的表现 | 后果 |
|------|--------------------|------|
| **模型切换改大段代码** | OpenAI 和 Anthropic 两套 headers/payload，agent_loop 和 api_client 深度耦合 | 换模型供应商要重写循环逻辑 |
| **工具绑定手写** | 手动构造 tools JSON Schema，手动 dispatch tool name → function | 加一个工具要在三处改代码 |
| **多轮对话无状态** | 每次对话 messages 列表在内存里，关掉就丢；要持久化得手写 json.dump | 无法实现跨轮对话的会话隔离 |
| **缺少中间件层** | 没有 Callback / 没有 Retry / 没有 Token 计数 / 没有日志 | 出问题只能加 print 调试 |

### 1.3 LangChain 解决什么

LangChain 不提供 LLM（LLM 还是 OpenAI / Anthropic / Ollama 那些），它做的是**集成抽象**：把"调用不同模型 + 绑定工具 + 管理 Agent 循环 + 持久化"封装成可复用、可组合的组件。而 2026 年官方推荐的 `create_agent()` 则进一步把整个 Agent 循环封装成一行。

| 维度 | Week 03 手写 | LangChain create_agent |
|------|-------------|------------------------|
| 创建 Agent | 手写 while True 循环 + 工具 dispatch | `create_agent(model, tools, system_prompt)` 一行 |
| 工具绑定 | 手写 JSON Schema + if-elif dispatch | `@tool` 装饰器自动推断 |
| 模型切换 | 改函数、改 headers、改 payload | 改一个 `model` 字符串 |
| 持久化 | 无，或手动 json.dump | `checkpointer=InMemorySaver()` 自动存档 |
| 多轮对话 | 手动维护 messages 列表 | `thread_id` 自动隔离会话 |
| 流式输出 | 手写 SSE 行解析 | `agent.stream_events(version="v3")` |
| 中间件 | 无（出问题加 print） | LangChain Callback 系统（日志/Tracing/Retry） |

> **直觉类比：** Week 03 的手写 Agent 像自己手搓一个引擎——每一步都清楚，但换零件（模型）就得重新设计接口；`create_agent` 像买一台整车——接口统一（方向盘 + 油门），引擎坏了直接换而不改驾驶方式。但你先手搓过引擎（Week 03），才知道它替你封装了什么。

---

## 二、模型抽象：init_chat_model 统一接口

### 2.1 ChatModel 是什么

LangChain 里所有对话模型的基类是 `BaseChatModel`，它定义了统一的调用接口。无论底下接的是 OpenAI、Anthropic 还是本地 Ollama，对外暴露的都是同一套方法：

| 方法 | 作用 | 返回 | 对应 Week 03 |
|------|------|------|--------------|
| `invoke(input)` | 单次同步调用 | `AIMessage` | `call_llm()` 一次 |
| `stream(input)` | 流式调用，逐块产出 | Iterator[`AIMessageChunk`] | `call_llm_stream()` 手写 SSE |
| `batch(inputs)` | 批量并发调用多个 input | list[`AIMessage`] | 自己写循环 + 并发 |
| `ainvoke / astream / abatch` | 上面三个的异步版本 | Coroutine / AsyncIterator | `httpx.AsyncClient` |

注意返回的是 `AIMessage` 对象而不是裸字符串——`content` 是文本，`tool_calls` 是工具调用，`usage_metadata` 是 token 用量。这比 Week 03 从 `choices[0].message.content` 抠字段干净得多。

### 2.2 init_chat_model：一个函数对接所有模型

`init_chat_model` 是 LangChain 提供的工厂函数，按模型标识串自动实例化对应的 ChatModel 类。它最大的价值是**让模型成为配置而非代码**：

```python
"""模型抽象演示：init_chat_model 一个函数对接多供应商"""
import os

from langchain.chat_models import init_chat_model


def get_model(provider: str = "ollama", temperature: float = 0.7):
    """
    按供应商名返回一个 ChatModel 实例。

    切换模型只改 provider 字符串，调用代码一行不动。
    LangChain 本身不提供 LLM，只做集成抽象——
    底下真正发请求的还是各家的 SDK。
    """
    if provider == "openai":
        return init_chat_model(
            "gpt-4o-mini",
            model_provider="openai",
            temperature=temperature,
            api_key=os.getenv("OPENAI_API_KEY"),
        )

    if provider == "deepseek":
        # DeepSeek 是 OpenAI 兼容协议，用 ChatOpenAI 指定 base_url
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            temperature=temperature,
        )

    if provider == "anthropic":
        return init_chat_model(
            "claude-sonnet-4-6",
            model_provider="anthropic",
            temperature=temperature,
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )

    if provider == "ollama":
        # 本地 Ollama，零配置、数据不出本机
        return init_chat_model(
            "qwen2.5:1.5b",
            model_provider="ollama",
            temperature=temperature,
        )

    if provider == "google_genai":
        # Gemini 系列：model 标识串格式 "google_genai:gemini-3.5-flash"
        return init_chat_model(
            "google_genai:gemini-3.5-flash",
            model_provider="google_genai",
            temperature=temperature,
            api_key=os.getenv("GOOGLE_API_KEY"),
        )

    raise ValueError(f"不支持的 provider: {provider}")


if __name__ == "__main__":
    # 切模型只改一个参数，调用方式完全一致
    model = get_model("ollama")              # 本地随便跑，不花钱
    # model = get_model("deepseek")          # 想用云端换一行即可
    # model = get_model("anthropic")         # 换 Claude 也是一行
    # model = get_model("google_genai")      # 换 Gemini 也是一行

    # 同一个 model，三种调用方式无缝切换
    print("=== invoke 同步 ===")
    print(model.invoke("用一句话解释什么是 Agent").content)

    print("\n=== stream 流式 ===")
    for chunk in model.stream("用一句话解释什么是 Tool Calling"):
        print(chunk.content, end="", flush=True)
    print()

    print("\n=== batch 批量 ===")
    results = model.batch(["1+1=?", "2+2=?"])
    for r in results:
        print(r.content)
```

### 2.3 模型标识串格式

`init_chat_model` 的第一个参数是模型标识串，格式为 `"provider:model_name"`：

| 标识串示例 | 含义 | 对应集成包 |
|-----------|------|-----------|
| `"openai:gpt-4o-mini"` | OpenAI GPT-4o-mini | `langchain-openai` |
| `"anthropic:claude-sonnet-4-6"` | Anthropic Claude Sonnet 4-6 | `langchain-anthropic` |
| `"ollama:qwen2.5:1.5b"` | Ollama 本地模型 | `langchain-ollama` |
| `"google_genai:gemini-3.5-flash"` | Google Gemini 3.5 Flash | `langchain-google-genai` |
| `"deepseek-chat"` | DeepSeek（用 ChatOpenAI + base_url） | `langchain-openai` |

> **提示：** 标识串也可以只传模型名（如 `"gpt-4o-mini"`），此时需额外指定 `model_provider` 参数。推荐用完整标识串，更明确。

---

## 三、create_agent() 入门：一行创建完整 Agent

### 3.1 什么是 create_agent

2026 年 LangChain 推出了 `create_agent` 高层 API（`from langchain.agents import create_agent`），它把"模型 + 工具 + Prompt + Checkpointer + 结构化输出"全部封装成一行调用。`create_agent` 底层基于 LangGraph，所以自带持久化、人机交互、流式等能力——但你不需要手动搭 `StateGraph`。

三个核心参数：

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `model` | str 或 ChatModel 实例 | 模型标识串或已初始化的 ChatModel | `"ollama:qwen2.5:1.5b"` |
| `tools` | list[Tool] | 工具列表，每个工具用 `@tool` 装饰器定义 | `[search, calculator]` |
| `system_prompt` | str | 系统提示词，定义 Agent 的角色和行为 | `"你是一个徒步规划助手"` |

### 3.2 完整示例

```python
"""create_agent 完整示例：一行创建 Agent，对比 Week 03 手写 50 行 Agent Loop"""
from langchain.agents import create_agent
from langchain.tools import tool
from langchain.chat_models import init_chat_model


# -------- 工具定义 --------

@tool
def search(query: str) -> str:
    """
    搜索互联网，返回与 query 相关的信息摘要。

    当用户问到实时信息、最新新闻、或需要外部知识时使用此工具。
    """
    # 生产环境此处应调真实搜索 API
    return f"关于「{query}」的搜索结果：找到 3 条相关条目。"


@tool
def calculator(expression: str) -> str:
    """
    计算数学表达式，支持四则运算和括号。

    当用户问到数学计算时使用此工具。expression 是数学表达式字符串。
    示例："(3.5 + 2) * 4"
    """
    try:
        result = eval(expression)  # 注意：仅做演示，生产环境用安全 eval
        return f"{expression} = {result}"
    except Exception as e:
        return f"计算错误：{e}"


# -------- 创建 Agent --------

agent = create_agent(
    model="ollama:qwen2.5:1.5b",         # 模型标识串，支持所有 provider
    tools=[search, calculator],           # 工具列表，@tool 装饰器自动推断
    system_prompt=(
        "你是一个智能助手，可以使用搜索和计算工具来帮助用户。"
        "当需要实时信息时使用搜索，当需要计算时使用计算器。"
    ),
)


# -------- 调用 Agent --------

if __name__ == "__main__":
    # 单轮 invoke
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "3.5 * 4 + 2 等于多少？"}]},
    )
    print(result["messages"][-1].content)
    # 输出：3.5 * 4 + 2 = 16.0
```

### 3.3 对比 Week 03 手写 Agent Loop

| 维度 | Week 03 手写（~50 行） | Week 06 create_agent（1 行） |
|------|-----------------------|-----------------------------|
| 创建 Agent | `while True` 循环 + `break` 条件判断 | `create_agent(model, tools, sys_prompt)` |
| 工具定义 | 手写函数 + 手写 JSON Schema dict | `@tool` 装饰器一行 |
| 工具调度 | `if name == "search": ... elif ...` 函数派发 | 自动绑定，`create_agent` 内部处理 |
| 消息管理 | 手动 `messages.append()` 维护列表 | 自动管理 Graph State |
| 错误重试 | 无，或手写 try/except | LangGraph 内置错误处理 |
| 流式输出 | 手写 SSE 解析 + `[DONE]` 判断 | `agent.stream_events(version="v3")` |
| 持久化 | 无，进程重启全丢 | `checkpointer=InMemorySaver()` 可选传入 |

---

## 四、Agent 调用方式：invoke + 多轮对话

### 4.1 带 thread_id 的 config

`create_agent` 返回的 agent 可以接收一个 `config` 参数，其中 `thread_id` 是关键——它决定了多轮对话的会话隔离。同一个 `thread_id` 的历史会被 Checkpointer 保存，下一个 invoke 会看到上文；不同 `thread_id` 完全隔离。

```python
"""Agent 多轮对话演示：thread_id 决定会话隔离"""
from langchain.agents import create_agent
from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver


@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。city 为城市名称（中文）。"""
    # 演示用 mock 数据
    weather_data = {
        "北京": "晴，25°C",
        "上海": "多云，28°C",
        "深圳": "雷阵雨，30°C",
    }
    return weather_data.get(city, f"{city}：暂无天气数据")


# 创建带持久化的 Agent
agent = create_agent(
    model="ollama:qwen2.5:1.5b",
    tools=[get_weather],
    system_prompt="你是一个天气助手，用中文回答。",
    checkpointer=InMemorySaver(),    # 启用会话持久化
)


if __name__ == "__main__":
    from uuid import uuid7

    # 第一轮对话：thread_id 为 session-1
    thread_id = str(uuid7())
    config = {"configurable": {"thread_id": thread_id}}

    result1 = agent.invoke(
        {"messages": [{"role": "user", "content": "北京今天天气如何？"}]},
        config=config,
    )
    print("User: 北京今天天气如何？")
    print("Agent:", result1["messages"][-1].content)

    # 第二轮对话：同一个 thread_id，Agent 记得上文
    result2 = agent.invoke(
        {"messages": [{"role": "user", "content": "那上海呢？"}]},
        config=config,
    )
    print("\nUser: 那上海呢？")
    print("Agent:", result2["messages"][-1].content)

    # 第三轮：新 thread_id，Agent 不记得前两轮
    new_config = {"configurable": {"thread_id": str(uuid7())}}
    result3 = agent.invoke(
        {"messages": [{"role": "user", "content": "那上海呢？"}]},
        config=new_config,
    )
    print("\n--- 新会话 ---")
    print("User: 那上海呢？")
    print("Agent:", result3["messages"][-1].content)
    # 注意：Agent 不记得前文，可能反问"哪个上海"或要求提供上下文
```

### 4.2 thread_id 的作用

| 场景 | thread_id 策略 | 效果 |
|------|---------------|------|
| 每个用户独立会话 | `uuid7()` 每次会话生成一个新 ID | 各用户互不干扰 |
| 多轮连续对话 | 同一用户多次 invoke 用同一个 thread_id | Agent 记住上文 |
| 测试/调试 | 固定 thread_id（如 `"debug-session"`） | 可复现对话历史 |
| 重置对话 | 生成新 thread_id | 旧历史还在但不影响新对话 |

### 4.3 流式调用：stream_events

2026 年的新流式 API 是 `agent.stream_events`，它返回 typed projections，可以精确区分"文本块"和"工具调用块"：

```python
# 流式输出（2026 年推荐 API）
async for event in agent.stream_events(
    {"messages": [{"role": "user", "content": "计算 (3+5)*2"}]},
    config=config,
    version="v3",
):
    if event.type == "text":
        print(event.data, end="", flush=True)
    elif event.type == "tool_call":
        print(f"\n[调用工具: {event.name}({event.args})]")
    elif event.type == "tool_result":
        print(f"\n[工具返回: {event.data}]")
```

> **注意：** 流式 API 需要模型和工具都支持流式。本地小模型（如 qwen2.5:1.5b）可能不支持完整流式，会退化成一次性输出。生产环境建议用 OpenAI / Anthropic 等云模型。

---

## 五、LCEL 作为补充：什么时候用链，什么时候用 Agent

### 5.1 两者的区别

| 维度 | `create_agent` | LCEL 链 `prompt | model | parser` |
|------|---------------|-----------------------------------------|
| 适用场景 | 需要工具循环（搜索、计算、调 API） | 纯推理链（翻译、摘要、分类） |
| 工具调用 | 内置工具循环，自动多轮 | 无工具循环，需手动 bind_tools |
| 持久化 | 内置 Checkpointer | 无，需手动实现 |
| 控制流 | 固定 ReAct 循环 | 通过自定义 Runnable 实现 |
| 复杂度 | 高（含 Graph 状态管理） | 低（线性管道） |
| 流式 | `stream_events(version="v3")` | `chain.stream()` 自动支持 |

### 5.2 什么时候用 LCEL

当你的任务**不需要工具**时，LCEL 更轻量：

```python
"""LCEL 链示例：纯推理场景，不需要工具"""
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 翻译链——不需要工具，单纯 prompt → model → parser
prompt = ChatPromptTemplate.from_template(
    "将以下英文翻译成中文：\n{text}"
)
model = init_chat_model("ollama:qwen2.5:1.5b")
chain = prompt | model | StrOutputParser()

result = chain.invoke({"text": "LangChain is a framework for building LLM applications."})
print(result)
# 输出：LangChain 是一个用于构建 LLM 应用的框架。
```

### 5.3 什么时候用 create_agent

当你的任务**需要工具循环**（模型可能需要多次调用工具才能得到最终答案）时，一定要用 `create_agent`：

```python
"""create_agent 示例：需要工具的场景"""
from langchain.agents import create_agent
from langchain.tools import tool

@tool
def search_stock(code: str) -> str:
    """查询股票行情。code 为股票代码。"""
    return f"{code} 当前价格：15.80 元，涨幅 +2.3%"

# 需要搜索工具，Agent 可能先查股票再分析
agent = create_agent(
    model="ollama:qwen2.5:1.5b",
    tools=[search_stock],
    system_prompt="你是股票分析助手，查询行情后进行简单分析。",
)
```

### 5.4 选择决策树

```
你的任务需要调工具（搜索/计算/API）吗？
├── 是 → 用 create_agent（自动管理工具循环）
│   ├── 需要多轮对话持久化？ → 加 checkpointer
│   └── 不需要持久化？ → 不加也行
└── 否 → 你的任务有复杂控制流吗？
    ├── 是（条件分支、循环、并行）→ 手写 LangGraph StateGraph
    └── 否（线性推理）→ LCEL 链 prompt|model|parser
```

> **核心原则：** `create_agent` 是"预包装的完整 Agent"；LCEL 是"搭积木的工具"。当你只需要搭一个简单积木（推理链）时用 LCEL；当你需要一个完整产品（Agent）时用 `create_agent`。两者不是替代关系，而是不同抽象层次的选择。

---

## 动手实验

### 🟢 青铜级：跑通 langchain_basics.py

把今日产出 `langchain_basics.py` 跑起来，用本地 Ollama（不花钱）验证三个关键能力：

```bash
# 先确保 Ollama 起着、拉了模型
ollama serve
ollama pull qwen2.5:1.5b

# 跑今日产出
python week06/langchain_basics.py
```

依次验证：
1. `init_chat_model` 成功初始化模型，`invoke / stream / batch` 都通
2. `create_agent` 一行创建 Agent，跑通一次工具调用（比如 `calculator`）
3. 多轮对话在同一 `thread_id` 下记住了上文

### 🟡 白银级：多模型 + 多工具对比

1. 用 `get_model()` 分别接 Ollama / DeepSeek / OpenAI（哪个有 key 用哪个），对同一个问题跑同一条工具链，对比三个模型"是否自动决定调工具"的表现。注意：弱模型（本地小参数）经常不主动调工具，这是模型能力问题。
2. 加至少一个自定义工具（比如 `get_time()` 返回当前时间），注册进 `create_agent`，验证 Agent 能在需要时自动调它。

### 🔴 王者级：手写 stream_events 消费器

1. 如果模型支持流式，实现一个完整的 `stream_events` 消费者，把文本块逐字输出、工具调用高亮显示、工具结果折叠展示，做成一个类似 ChatGPT 的终端聊天界面效果。
2. 对比 `invoke` 和 `stream_events` 的耗时差异，记录：流式首 token 延迟（TTFT）和总完成时间。
3. 思考：`stream_events` 返回的 typed projection 相比 Week 03 手写 SSE 解析，框架替你封装了哪些工作？

---

## 踩坑记录 🕳️

### 坑 1：create_agent 的 model 参数传了字符串却报错

```
ValueError: Unknown model provider: 'ollama'
```

**解决：** `create_agent` 的 `model` 参数支持字符串和已初始化的 ChatModel。传字符串时，它会内部调用 `init_chat_model` 去解析，这要求对应集成包已安装。报这个错说明没装 `langchain-ollama` / `langchain-anthropic` 等。用谁装谁：`pip install langchain-ollama`。也可以先自己 `init_chat_model` 得到实例再传进去，更可控。

### 坑 2：Agent 不调用工具，直接文本回答

Agent 收到需要搜索或计算的问题时，直接输出文本而不调工具。

**解决：** 这是最常见的 Agent 失败模式，通常有三个原因：
- **模型太弱**：本地小模型（1.5B、3B 参数）经常不主动调工具，换 7B+ 或云端模型解决。
- **system_prompt 不够明确**：在 system_prompt 里明确说"如果需要实时信息，请使用 search 工具""如果需要计算，请使用 calculator 工具"。
- **工具描述太模糊**：`@tool` 的 docstring 要写清楚"什么时候用这个工具"和"参数含义"。比如 `search(query: str) -> str` 的 docstring 里写"当用户问到实时信息或最新新闻时使用此工具"，比只写"搜索互联网"有效得多。

### 坑 3：多轮对话中 Agent 忘了上下文

```
User: 北京天气如何？
Agent: 北京晴 25°C
User: 那上海呢？
Agent: 请问您说的是哪个上海？
```

**解决：** 检查是否传了相同的 `thread_id`。新 `thread_id` 意味着全新会话，Agent 看不到之前的历史。确保：
1. `create_agent` 时传了 `checkpointer=InMemorySaver()`
2. 每次 invoke 都传了 `config={"configurable": {"thread_id": "同一个"}}`
3. 如果需要 Agent 记住多轮，thread_id 在会话期间保持一致

### 坑 4：invoke 的输入格式不对

```python
# ❌ 错误：传了裸字符串
agent.invoke("北京天气如何？")

# ❌ 错误：messages 格式不对
agent.invoke({"input": "北京天气如何？"})

# ✅ 正确：messages 列表格式
agent.invoke({"messages": [{"role": "user", "content": "北京天气如何？"}]})
```

**解决：** `create_agent` 返回的 agent 期望输入是 dict 格式 `{"messages": [{"role": "...", "content": "..."}]}`。这个格式兼容 OpenAI 的消息格式，也是 LangGraph State 的默认输入结构。如果传错格式，Agent 会报错或静默失败。

### 坑 5：stream_events 不输出任何内容

```python
# ❌ Agent 的 stream_events 返回空
async for event in agent.stream_events(input, config, version="v3"):
    print(event)
```

**解决：** 原因通常是模型不支持流式（本地小模型）或配置不对。检查：
1. 模型是否支持流式输出（Ollama 的 qwen2.5:1.5b 流式支持有限）
2. 是否用了 `version="v3"`（新 API 必需）
3. 实在不行退回到 `invoke` 先确保功能性正常，流式做优化项

---

## 副线笔记

### Claude Code 审查 Agent 代码：让 AI 帮你分析 Agent 配置

今天的副线是把你的 `create_agent` 定义交给 Claude Code 审查。不是让它夸你写得好，而是让它帮你**分析配置合理性**——你的 Agent 配置参数是否合适？还缺什么中间件？模型选择是否正确？

### 怎么让 Claude Code 审查

把 `langchain_basics.py` 里 `create_agent` 的定义贴给 Claude Code，问它这几个问题：

1. **「这个 create_agent 配置合适吗？」** —— Claude Code 会从 `model` 选择、`tools` 的工具描述质量、`system_prompt` 的指令清晰度三个维度分析。比如它会指出：本地 1.5B 模型可能不会主动调工具，建议换 7B+ 或云端模型；或者工具 docstring 不够详细导致模型不知道什么时候用。

2. **「工具定义还缺什么？」** —— Claude Code 会审查你的 `@tool` 函数的 docstring 是否规范。工具调用的成功率和 docstring 质量直接相关。它可能会建议：加参数校验、加错误处理、加使用示例。

3. **「Middleware / Callback 还缺什么？」** —— Claude Code 会帮你检查：有没有加 Token 计数、有没有加日志 Tracing、有没有加重试机制。生产级的 Agent 还缺 LangSmith Tracing、LangFuse 监控等。

4. **「stream_events 为什么没输出？」** —— 告诉 Claude Code 你的模型和配置，它会指出流式 API 的依赖链：模型必须支持流式 → `stream_events` 才有输出 → 没有输出通常是模型不支持流式。

### 示例审查对话

```
你：这个 create_agent 配置有什么问题？

agent = create_agent(
    model="ollama:qwen2.5:1.5b",
    tools=[search, calculator],
    system_prompt="你是一个助手",
)

Claude Code：我从三个角度分析：

1. 模型选择：qwen2.5:1.5b 只有 1.5B 参数，工具调用能力很弱。
   建议换 7B+（如 qwen2.5:7b 或云端模型）。

2. 工具描述：search 的 docstring 只有"搜索互联网"，
   缺少「什么时候用」。建议改为：
   "搜索互联网获取实时信息。当用户问到最新新闻、
   实时数据或你不知道的知识时使用此工具。"

3. system_prompt：只写了"你是一个助手"，没有说明
   工具的使用策略。建议加上：
   "当需要实时信息时使用 search 工具，
   当需要数学计算时使用 calculator 工具。"

另外建议加 checkpointer 以支持多轮对话：
   checkpointer=InMemorySaver(),
```

### 为什么这个审查有价值

| 审查维度 | 自己检查容易漏 | Claude Code 能帮你 |
|----------|---------------|-------------------|
| 模型选择 | 只关心能不能跑，不关心参数大小 | 根据工具复杂度推荐合适的模型规模 |
| 工具描述 | docstring 写了，但不够详细 | 从"模型怎么理解这个工具"的角度优化描述 |
| system_prompt | 只写了角色没写工具策略 | 补充工具使用策略的指令 |
| 缺少组件 | 不知道还缺什么 | 提醒加 checkpointer / Tracing / Callback |
| 流式问题 | 各种试错 | 直接指出流式依赖链和瓶颈 |

### 今日观察任务

- 把你的 `create_agent` 定义和三个工具函数贴给 Claude Code，让它做一次完整的 Agent 配置审查。
- 记下 Claude Code 指出的至少 2 个可优化点，在 Day 02 的 `@tool` 高级用法里用上。
- 如果有时间，问 Claude Code "如果不建议用这个本地模型，你推荐哪个？"——它可能会对比 qwen2.5:7b、deepseek-chat、claude-sonnet-4-6 在工具调用上的表现差异。

---

## 今日产出检查清单

- [ ] 用 `init_chat_model` 成功初始化了至少一个 model provider（Ollama / OpenAI / Anthropic / Gemini）
- [ ] 同一个 model 跑通了 `invoke / stream / batch` 三种调用方式
- [ ] 用 `create_agent(model, tools, system_prompt)` 一行创建了 Agent，并成功调用了至少一个工具
- [ ] 理解了 `thread_id` 的会话隔离作用，跑通了多轮对话（同一 thread_id 记住上文，新 thread_id 全新开始）
- [ ] 能区分 `create_agent`（需要工具循环）和 LCEL 链（纯推理）的适用场景
- [ ] 让 Claude Code 审查过你的 `create_agent` 配置，并根据建议做了至少一处优化

---

> **下一课预告：Day 02 — 工具调用深入：@tool / ToolRuntime / 状态注入**。今天我们用 `@tool` 装饰器定义了两个简单工具，并由 `create_agent` 自动管理工具循环。明天深入工具调用的底层机制：`@tool` 的参数校验与缓存、ToolRuntime 的执行上下文、工具状态注入、以及 `bind_tools` 的高级用法。同时讲清楚 `create_agent` 底部如何把 `@tool` 转成 LangGraph 的工具节点。
