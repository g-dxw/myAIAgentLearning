# Day 01 — LangChain 基础：模型 / Prompt / LCEL

## 学习目标

Week 03 我们用 httpx 裸调过 LLM API：手拼 messages、手写 SSE 流式解析、手写 `extract_usage` 兼容 OpenAI/Anthropic 两套 usage 字段。那一套能跑，但每换个模型、加段历史、要个结构化输出，都得改一大片代码。今天正式引入 LangChain 框架：用统一的模型抽象屏蔽各家 API 差异，用 Prompt 模板替代 f-string 拼接，用 LCEL 管道符把"拼 prompt → 调模型 → 解析输出"串成一条链。目标是把 Week 03 手写的 httpx 调用换成 LangChain 的框架写法，且因为你手写过底层，所以每用一层抽象都知道它在替你干什么。

学完今天你能：
1. 用 `init_chat_model` 一个函数对接 OpenAI / Anthropic / Ollama，并在 `invoke / stream / batch` 三种调用方式间无缝切换
2. 用 `ChatPromptTemplate` + `MessagesPlaceholder` 替代手拼 messages list，把多轮对话历史模板化
3. 用 LCEL 管道符 `prompt | model | parser` 组装链，并说清楚它本质是 `Runnable.pipe()`，自动支持流式、批量、异步
4. 用 `PydanticOutputParser`（以及 `with_structured_output`）把 Week 03 手写的 JSON 解析 + Pydantic 校验交给框架

---

## 一、为什么用 LangChain：回顾 Week 03 手写 httpx 的痛点

### 1.1 Week 03 我们写过什么

Week 03 的 `api_client.py` 里，调一个 LLM 要干这些事：手动拼 `headers`（OpenAI 用 `Authorization: Bearer`，Anthropic 用 `x-api-key`）、手动拼 `payload`（字段名都不一样）、手动 `httpx.post`、手动 `raise_for_status`、手动从 `choices[0].message.content` 里抠文本、流式还得自己按行解析 `data: {...}` 直到遇到 `[DONE]`。结构化输出那一版更繁琐：手动把 Pydantic schema 转成 tools、手动从 `tool_calls[0].function.arguments` 里取 JSON 再 `json.loads`。

这一套能让你看清 LLM API 的底裤，但它有三个痛点会随项目变大而爆发。

### 1.2 三大痛点

| 痛点 | Week 03 手写 httpx 的表现 | 后果 |
|------|--------------------------|------|
| **模型切换要改代码** | OpenAI 和 Anthropic 是两套 headers、两套 payload、两套 usage 字段，`call_llm` 和 `call_llm_anthropic` 是两个函数 | 换个模型供应商要改调用层，A/B 测试模型几乎不可能 |
| **Prompt 拼接繁琐** | 多轮对话要手动 `messages.append({"role": ..., "content": ...})`，f-string 拼系统提示和用户输入混在一起 | 历史一长 messages list 难维护，模板复用靠复制粘贴 |
| **输出解析手写** | JSON Mode 要 `json.loads(content)`，Function Calling 要抠 `tool_calls[0].function.arguments`，还要自己接 Pydantic 校验 | 每种结构化输出写一遍解析，错误处理全靠 try/except 兜 |

### 1.3 LangChain 解决什么

LangChain 不提供 LLM（LLM 还是 OpenAI / Anthropic / Ollama 那些），它做的是**集成抽象**：把"调用不同模型 + 拼 prompt + 解析输出"这三件每次都要重写的事，封装成可复用、可组合的组件。你写的不再是"调 DeepSeek 的 httpx 代码"，而是"调一个 ChatModel"——底下接谁由配置决定。

| 维度 | Week 03 手写 httpx | LangChain 框架写法 |
|------|--------------------|--------------------|
| 切换模型 | 改函数、改 headers、改 payload 解析 | 改一个 `model_provider` 字符串 |
| Prompt 组织 | 手拼 messages list | `ChatPromptTemplate` 模板变量 |
| 流式输出 | 手写 SSE 行解析 + `[DONE]` 判断 | `chain.stream()` 逐块 yield |
| 批量调用 | 自己写循环 + 并发 | `chain.batch([...])` 一次传多个 |
| 结构化输出 | 手抠 JSON + 手接 Pydantic | `PydanticOutputParser` / `with_structured_output` |
| 异步 | 手写 `httpx.AsyncClient` | `chain.ainvoke()` 自动异步 |

> **直觉类比：** Week 03 的 httpx 写法像「自己接线」——每接一个电器都要剥线、拧螺丝；LangChain 像统一了「插座标准」——电器（模型）和开关（调用方式）都按标准接口做，插上就能用。但你得先知道线怎么接（手写过），才不会把零火线接反。

---

## 二、模型抽象：init_chat_model 与统一接口

### 2.1 ChatModel 是什么

LangChain 里所有对话模型的基类是 `BaseChatModel`，它定义了统一的调用接口。无论底下接的是 OpenAI、Anthropic 还是本地 Ollama，对外暴露的都是同一套方法：

| 方法 | 作用 | 返回 | 对应 Week 03 |
|------|------|------|--------------|
| `invoke(input)` | 单次同步调用 | `AIMessage` | `call_llm()` 一次 |
| `stream(input)` | 流式调用，逐块产出 | Iterator[`AIMessageChunk`] | `call_llm_stream()` 手写 SSE |
| `batch(inputs)` | 批量并发调用多个 input | list[`AIMessage`] | 自己写循环 + 并发 |
| `ainvoke / astream / abatch` | 上面三个的异步版本 | Coroutine / AsyncIterator | `httpx.AsyncClient` |

注意返回的是 `AIMessage` 对象而不是裸字符串——`content` 是文本，`tool_calls` 是工具调用，`usage_metadata` 是 token 用量。这比 Week 03 从 `choices[0].message.content` 抠字段干净得多。

### 2.2 init_chat_model：一个函数对接所有家

`init_chat_model` 是 LangChain 提供的工厂函数，按 `model_provider` 自动实例化对应的 ChatModel 类。它最大的价值是**让模型成为配置而非代码**：

```python
"""模型抽象演示：init_chat_model 一个函数对接多供应商"""
import os

from langchain.chat_models import init_chat_model


def get_model(provider: str = "openai", temperature: float = 0.7):
    """
    按供应商名返回一个 ChatModel 实例。

    切换模型只改 provider 字符串，调用代码一行不动。
    LangChain 本身不提供 LLM，只做集成抽象——
    底下真正发请求的还是 openai / anthropic / ollama 的 SDK。
    """
    if provider == "openai":
        # OpenAI 官方 / 兼容服务（如 DeepSeek）都走 ChatOpenAI
        return init_chat_model(
            "gpt-4o-mini",
            model_provider="openai",
            temperature=temperature,
            api_key=os.getenv("OPENAI_API_KEY"),
        )

    if provider == "deepseek":
        # DeepSeek 是 OpenAI 兼容协议，用 ChatOpenAI 指定 base_url 即可
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            temperature=temperature,
        )

    if provider == "anthropic":
        return init_chat_model(
            "claude-3-5-sonnet-latest",
            model_provider="anthropic",
            temperature=temperature,
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )

    if provider == "ollama":
        # 本地 Ollama，零配置、数据不出本机
        return init_chat_model(
            "llama3.1",
            model_provider="ollama",
            temperature=temperature,
        )

    raise ValueError(f"不支持的 provider: {provider}")


if __name__ == "__main__":
    # 切模型只改一个参数，调用方式完全一致
    model = get_model("ollama")          # 本地随便跑，不花钱
    # model = get_model("deepseek")      # 想用云端换一行即可
    # model = get_model("anthropic")     # 换 Claude 也是一行

    # 同一个 model，三种调用方式无缝切换
    print("=== invoke 同步 ===")
    print(model.invoke("用一句话解释什么是 LCEL").content)

    print("\n=== stream 流式 ===")
    for chunk in model.stream("用一句话解释什么是 RAG"):
        print(chunk.content, end="", flush=True)
    print()

    print("\n=== batch 批量 ===")
    results = model.batch(["1+1=?", "2+2=?"])
    for r in results:
        print(r.content)
```

### 2.3 invoke / stream / batch 对比

同一个 ChatModel，三种调用方式背后是同一套 HTTP 调用逻辑，只是框架帮你包装了不同的迭代/并发策略：

| 调用方式 | 底层机制 | Week 03 对应手写量 | 适用场景 |
|----------|----------|--------------------|----------|
| `invoke` | 单次 POST，等完整响应 | `call_llm()` ~50 行 | 一次性问答、后台任务 |
| `stream` | POST + `stream=True`，按 SSE 解析 | `call_llm_stream()` ~40 行手写行解析 | 用户可见的逐字输出 |
| `batch` | 并发多个 POST（默认 max_concurrency=5） | 自己写 `asyncio.gather` + 重试 | 批量评测、数据集处理 |

> **关键认知：** Week 03 你为「流式」单独写了一个函数、为「批量」还得自己写并发。LangChain 里这三个是同一个 model 对象上的方法，写法一致、错误处理一致。这就是抽象的回报。

---

## 三、Prompt 模板：从 f-string 拼接升级到模板变量

### 3.1 Week 03 的拼法回顾

Week 03 里多轮对话是这样拼的：

```python
messages = [
    {"role": "system", "content": f"你是{role}，请简洁回答。"},
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！有什么可以帮你？"},
    {"role": "user", "content": user_input},
]
resp = call_llm(messages)
```

问题：系统提示和对话历史混在一个裸 list 里，想复用模板得复制粘贴，历史消息一长就乱。

### 3.2 ChatPromptTemplate：模板变量替代 f-string

`ChatPromptTemplate` 把「消息结构」和「变量填充」分开：模板定义消息骨架，`invoke` 时传变量值。

```python
"""Prompt 模板演示"""
from langchain_core.prompts import ChatPromptTemplate


# 普通模板：用 {变量} 占位，invoke 时填充
prompt = ChatPromptTemplate.from_template(
    "你是资深 {role}，请用一句话向 {audience} 解释 {topic}。"
)

# 渲染：传一个 dict，得到 ChatPromptValue（内部是格式化好的消息列表）
rendered = prompt.invoke({"role": "Python 工程师", "audience": "产品经理", "topic": "装饰器"})
print(rendered)
# → messages=[HumanMessage(content="你是资深 Python 工程师，请用一句话向 产品经理 解释 装饰器。")]
```

模板渲染出的 `ChatPromptValue` 可以直接喂给 model：`model.invoke(rendered)`。比起 Week 03 的 f-string，好处是模板可复用、变量显式声明（少一个会报错而不是悄悄拼成空串）。

### 3.3 MessagesPlaceholder：多轮对话历史的模板化

真正的多轮对话有「固定部分」（system + 当前 user 输入）和「可变部分」（历史消息列表）。`MessagesPlaceholder` 就是为可变的历史消息列表设计的占位符：

```python
"""带历史消息的 Prompt 模板"""
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# 模板定义消息骨架，history 是可变长度的历史消息占位
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个徒步旅行顾问，回答要基于实际经验，简洁实用。"),
    MessagesPlaceholder(variable_name="history"),  # 历史对话，长度可变
    ("human", "{input}"),                          # 当前用户输入
])

# 历史消息以 BaseMessage 列表形式传入
from langchain_core.messages import HumanMessage, AIMessage

history = [
    HumanMessage(content="下周想去黄山，两天行程怎么安排？"),
    AIMessage(content="建议 Day1 爬前山，Day2 走后山看日出..."),
]

rendered = prompt.invoke({
    "history": history,
    "input": "那需要带什么装备？",  # 模型会基于上文「黄山两天」回答
})
# 渲染结果是 [system, ...history, human] 完整消息列表
```

| 对比项 | Week 03 手拼 messages list | ChatPromptTemplate + MessagesPlaceholder |
|--------|---------------------------|------------------------------------------|
| 模板复用 | 复制粘贴 | 定义一次，多处 invoke |
| 变量校验 | 漏填变量静默变空串 | 漏填变量直接报错 |
| 历史消息 | 手动 append 进 list | `history` 占位符自动展开 |
| 与链结合 | 手动拼完再传 model | 模板本身就是链的一个 Runnable 节点 |

> **关键认知：** `ChatPromptTemplate` 本身也是一个 `Runnable`——它能 `invoke`、能 `stream`、能 `|` 进管道。这就是 LCEL 能把 prompt 当一个组件串进链的前提（见下一节）。

---

## 四、LCEL 表达式链：用管道符串联 prompt | model | parser

### 4.1 什么是 LCEL

LCEL（LangChain Expression Language）是 LangChain 的链组装语法，核心就一个符号：管道符 `|`。它把多个 `Runnable` 组件像 Unix 管道一样串联起来，前一个的输出自动喂给后一个的输入：

```python
chain = prompt | model | output_parser
```

这一行等价于：把 `prompt.invoke(input)` 的结果传给 `model.invoke()`，再把结果传给 `output_parser.invoke()`。看起来像语法糖，但它带来三个实打实的能力：**自动流式、自动批量、自动异步**。

### 4.2 LCEL 的本质：Runnable.pipe()

`|` 在 Python 里是 `__or__` 运算符。LangChain 给所有 `Runnable` 实现了 `__or__`，让它返回一个新的组合 Runnable。所以下面两种写法完全等价：

```python
# 写法一：管道符（LCEL 语法糖，推荐）
chain = prompt | model | StrOutputParser()

# 写法二：显式 pipe（等价，本质就是这个）
chain = prompt.pipe(model).pipe(StrOutputParser())
```

理解了 `.pipe()` 这个本质，你就知道链是怎么工作的：链本身也是一个 `Runnable`，它把子组件的 `invoke / stream / batch / ainvoke` 串起来调用。Claude Code 审查你的链时，它也是从这个角度理解底层的（见副线笔记）。

### 4.3 完整链示例 + 逐组件拆解

```python
"""LCEL 完整链示例：把 Week 03 的手写流程换成链"""
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser


def build_chain(model):
    """
    构建一个 LCEL 链：prompt → model → parser。

    prompt 负责把变量渲染成消息；
    model 负责调 LLM 生成回复；
    StrOutputParser 负责从 AIMessage 里抠出纯文本。
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是徒步旅行顾问，回答简洁实用。"),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ])
    # 管道符把三个 Runnable 串成一条链
    return prompt | model | StrOutputParser()


if __name__ == "__main__":
    model = init_chat_model("llama3.1", model_provider="ollama")
    chain = build_chain(model)

    history = [
        HumanMessage(content="下周想去黄山两天。"),
        AIMessage(content="建议 Day1 前山，Day2 后山看日出。"),
    ]

    # 1. invoke —— 单次同步，等完整结果（Week 03 的 call_llm）
    answer = chain.invoke({"history": history, "input": "带什么装备？"})
    print(answer)

    # 2. stream —— 流式逐块输出（Week 03 的 call_llm_stream，但不用手写 SSE 解析）
    print("\n=== 流式 ===")
    for chunk in chain.stream({"history": history, "input": "海拔多少？"}):
        print(chunk, end="", flush=True)
    print()

    # 3. batch —— 批量并发（Week 03 要自己写 asyncio.gather）
    answers = chain.batch([
        {"history": [], "input": "黄山几月去最好？"},
        {"history": [], "input": "泰山需要几天？"},
    ])
    for a in answers:
        print(a)
```

### 4.4 逐组件拆解：数据如何流动

链 `prompt | model | parser` 的数据流是这样的：

| 步骤 | 组件 | 输入 | 输出 | 对应 Week 03 |
|------|------|------|------|--------------|
| 1 | `prompt` | `{"history": [...], "input": "..."}` | `ChatPromptValue`（消息列表） | 手拼 messages list |
| 2 | `model` | `ChatPromptValue` | `AIMessage`（含 content + usage） | `call_llm()` 返回的 dict |
| 3 | `StrOutputParser` | `AIMessage` | `str`（纯文本） | 从 `choices[0].message.content` 抠文本 |

### 4.5 LCEL 对比 Week 03 手写流程

| 流程环节 | Week 03 手写 | LCEL 链 |
|----------|--------------|---------|
| 拼 prompt | 手动 list.append | `prompt.invoke({...})` |
| 调模型 | `call_llm(messages)` | `model.invoke(prompt_value)` |
| 解析输出 | `resp["choices"][0]["message"]["content"]` | `parser.invoke(aimessage)` |
| 流式 | 单独写 `call_llm_stream` 手解 SSE | 链不变，`chain.stream()` 即可 |
| 批量 | 自己写循环/并发 | 链不变，`chain.batch([...])` 即可 |
| 异步 | 自己 `httpx.AsyncClient` | 链不变，`chain.ainvoke()` 即可 |

> **关键认知：** 同一条链，`invoke / stream / batch / ainvoke` 四种调用方式都能用，行为由链的编排逻辑保证——这是 LCEL 最大的回报。Week 03 你为每种调用方式各写一套代码；LCEL 写一条链，四种方式白送。

---

## 五、输出解析器：把 LLM 的文本变成结构化对象

### 5.1 Week 03 的结构化输出回顾

Week 03 的 `structured_output.py` 里，让 LLM 返回结构化数据要：把 Pydantic schema 手动转成 `tools`、手动 `tool_choice` 强制调用、再从 `tool_calls[0].function.arguments` 里 `json.loads` 取出 dict、最后 `Model(**dict)` 校验。一整套下来 30 多行，且 JSON Mode 和 Function Calling 是两套不同的解析逻辑。

LangChain 的 Output Parser 把这套流程封装成链的最后一个组件。

### 5.2 三种常用解析器

| 解析器 | 作用 | 输出类型 | 适用场景 |
|--------|------|----------|----------|
| `StrOutputParser` | 从 AIMessage 抠纯文本 | `str` | 普通问答，只要文本 |
| `JsonOutputParser` | 把文本解析成 JSON（部分模型支持流式解析） | `dict` | 要 JSON 但不想定义严格 schema |
| `PydanticOutputParser` | 把文本解析成 Pydantic 对象 + 字段校验 | `BaseModel` 实例 | 严格结构化输出，复用 Week 03 的 Pydantic |

### 5.3 PydanticOutputParser 完整示例

`PydanticOutputParser` 会自动生成「格式说明」塞进 prompt，让 LLM 按要求输出 JSON，然后解析成 Pydantic 对象并校验。复用 Week 03 的 `ExtractedInfo` 模型：

```python
"""PydanticOutputParser 演示：复用 Week 03 的 Pydantic 模型"""
from pydantic import BaseModel, Field

from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser


class ExtractedInfo(BaseModel):
    """从自然语言中提取的个人信息（沿用 Week 03 的定义）"""
    姓名: str = Field(description="人物的中文全名")
    年龄: int = Field(description="年龄（周岁）", ge=0, le=150)
    城市: str = Field(description="所在城市")
    技能: list[str] = Field(default_factory=list, description="掌握的技能列表")


def build_extract_chain(model):
    """
    构建信息提取链：prompt(含格式说明) → model → PydanticOutputParser。

    parser.get_format_instructions() 会生成一段「请按以下 JSON schema 输出」的说明，
    .partial() 把它预先填进模板，这样每次 invoke 只传 {text} 即可。
    """
    parser = PydanticOutputParser(pydantic_object=ExtractedInfo)

    prompt = ChatPromptTemplate.from_template(
        "从下面的文本中提取个人信息。\n"
        "{format_instructions}\n\n"
        "文本: {text}"
    ).partial(format_instructions=parser.get_format_instructions())

    return prompt | model | parser


if __name__ == "__main__":
    model = init_chat_model("gpt-4o-mini", model_provider="openai")
    chain = build_extract_chain(model)

    # 直接拿到 Pydantic 对象，字段校验已由 parser 完成
    info: ExtractedInfo = chain.invoke({
        "text": "我叫张三，今年28岁，住北京，会Python和数据分析。"
    })
    print(info)                # 姓名='张三' 年龄=28 ...
    print(info.技能)           # ['Python', '数据分析']
    print(type(info))          # <class 'ExtractedInfo'>
```

对比 Week 03：链里 `parser` 这一步，干的就是 Week 03 里「`json.loads(arguments)` + `ExtractedInfo(**dict)`」那两步，外加自动重试解析失败。你写的 Pydantic 模型一行没改，直接复用。

### 5.4 更现代的写法：with_structured_output

如果模型原生支持 Function Calling / tool calling（Day 02 会深入），还有更省事的写法——`with_structured_output` 让 model 直接吐 Pydantic 对象，连 parser 都不用写：

```python
# 模型原生支持工具调用时，一行搞定结构化输出
structured_model = model.with_structured_output(ExtractedInfo)
info: ExtractedInfo = structured_model.invoke("我叫李四，30岁，住上海，会Go")
```

这背后其实就是 Day 02 要讲的 `bind_tools` + 自动解析。今天先用 `PydanticOutputParser` 理解「输出解析」这个环节在链里的位置，明天再换更底层的工具调用写法。

---

## 动手实验

### 🟢 青铜级：跑通 LCEL 链

把今日产出 `langchain_basics.py` 跑起来，用本地 Ollama（不花钱）验证 `invoke / stream / batch` 三种调用方式都通。重点观察：流式输出是不是真的逐块 yield、batch 是不是真的并发。

```bash
# 先确保 Ollama 起着、拉了模型
ollama serve
ollama pull llama3.1

# 跑今日产出
python week06/langchain_basics.py
```

### 🟡 白银级：模型切换对比

用 `get_model()` 分别接 Ollama / DeepSeek / Anthropic（哪个有 key 用哪个），对同一个问题跑同一条链，对比三个模型的回答风格、耗时、token 用量。记录：换模型改了几行代码？（理想答案是：一行）

### 🔴 王者级：结构化提取对比

用 `PydanticOutputParser` 链和 `with_structured_output` 两种方式，对同一段文本做信息提取，对比：解析成功率、失败时的报错信息、能否流式产出。思考：为什么 `PydanticOutputParser` 能配合 `stream()`，而 `with_structured_output` 的流式行为依赖模型是否支持流式 tool calling？

---

## 踩坑记录 🕳️

### 坑 1：init_chat_model 找不到 provider

```
ValueError: Unknown model provider: 'ollama'
```

**解决：** `init_chat_model` 按需懒加载对应集成包。报这个错说明没装 `langchain-ollama` / `langchain-anthropic` 等。LangChain 把各家集成拆成了独立包，`pip install langchain` 不会带上所有 provider 包。用谁装谁：`pip install langchain-ollama`。

### 坑 2：流式没生效，一次性吐出全部

链 `prompt | model | StrOutputParser()` 调 `chain.stream()` 却一次返回完整字符串，不逐块。

**解决：** 检查 `model` 有没有用 `streaming=True` 或对应配置。部分模型集成默认不开流式，需要在实例化时显式开启（如老版 `ChatOpenAI(streaming=True)`）。新版 `init_chat_model` 一般默认支持，但 Ollama 本地偶尔因缓冲区问题需要确认 `ollama serve` 正常。另外确认你消费的是 `for chunk in chain.stream(...)` 而不是 `chain.stream(...)` 本身（它返回的是迭代器，要迭代才逐块产出）。

### 坑 3：PydanticOutputParser 解析失败：模型没按要求输出 JSON

模型输出了一段解释文字 + JSON，或 JSON 外面裹了 ```json 代码块，解析器报 `OutputParserException`。

**解决：** 一是确保 `get_format_instructions()` 真的塞进了 prompt（用 `.partial()` 预填）；二是换能力更强的模型，弱模型（小参数本地模型）经常不遵守格式说明；三是用 `with_structured_output`（走 Function Calling，约束更强）；四是给 parser 配 `partial_json_handling` 容错（部分 parser 支持）。Week 03 你手写时也遇到过 JSON Mode 要在 system 里强调 'json'，本质一样。

### 坑 4：模板变量漏填，链直接报错而非返回空

Week 03 手拼 f-string 时漏填变量顶多拼成空串，链还能跑；LCEL 模板漏填直接 `KeyError`。

**解决：** 这其实是好事——早报错比悄悄拼错好。如果某些变量有默认值，用 `prompt.partial({"key": default})` 预填默认值；动态变量再在 `invoke` 时传。养成习惯：模板里出现的 `{变量}` 都要么 `.partial` 预填、要么 invoke 必传。

### 坑 5：把 model 和 chain 的输入类型搞混

`model.invoke("字符串")` 可以，但 `chain.invoke("字符串")` 报错——因为链的第一个组件是 prompt，它要的是 `{"input": ..., "history": ...}` 这样的 dict，不是裸字符串。

**解决：** 记住链的输入类型由**第一个组件**决定：第一个是 prompt 就传 dict，第一个是 model 才能传字符串/消息。理解了 `.pipe()` 本质（上一节）就不会搞混——链就是把输入交给第一个 Runnable。

---

## 副线笔记

### Claude Code 审查 LCEL 链：让它帮你拆解管道符底层

今天的副线是把你的 LCEL 链代码交给 Claude Code 审查。不是让它夸你写得好，而是让它帮你**对照底层**——LCEL 的管道符看着像语法糖，但它到底替你做了什么？让 Claude Code 把链展开成等价的「手写流程」给你看。

### 怎么让 Claude Code 审查

把 `langchain_basics.py` 里那条 `prompt | model | StrOutputParser()` 链贴给 Claude Code，问它三个问题：

1. **「这个链有没有更简洁的写法？」** —— 它可能会指出：如果你的 prompt 只是单条用户消息，`ChatPromptTemplate.from_messages([("human","{input}")])` 可以换成更简短的 `from_template`；或者结构化输出用 `with_structured_output` 能省掉整个 parser。
2. **「流式为什么没生效？」** —— 它会从 `Runnable` 的角度帮你排查：链的 `stream()` 是把上一个组件的 `stream()` 输出喂给下一个组件的 `stream()`，如果中间某个组件不支持流式（比如某些自定义 Runnable），整条链的流式就会退化成「先攒齐再吐」。
3. **「`|` 这个管道符底层到底干了什么？」** —— 让它把 `prompt | model | parser` 翻译成 `.pipe()` 调用，再展开成等价的手写流程。

### 管道符的本质：Runnable.pipe()

Claude Code 帮你看清的关键是：**LCEL 的 `|` 本质就是 `Runnable.__or__` 调用 `self.pipe(other)`**，返回一个新的 `RunnableSequence`。这个组合体也是个 `Runnable`，它的 `invoke` 是这样工作的：

```python
# prompt | model | parser 等价于：
class RunnableSequence:
    def __init__(self, first, last):
        self.first = first  # prompt
        self.last = last    # model | parser（递归组合）

    def invoke(self, input):
        # 把输入交给第一个组件，输出喂给剩下的链
        return self.last.invoke(self.first.invoke(input))

    def stream(self, input):
        # 流式：第一个组件流式产出，逐块喂给后面的链
        for chunk in self.first.stream(input):
            yield from self.last.stream(chunk)
```

看懂这个，你就明白为什么「同一条链自动支持流式/批量/异步」——因为 `RunnableSequence` 把这些调用方式都委托给子组件，只要子组件支持，链就支持。Week 03 你手写时，流式和批量是两套独立代码；LCEL 里它们是同一个 `RunnableSequence` 的三种方法，复用同一套编排逻辑。

### 今日观察任务

- 把你的链贴给 Claude Code，让它写出等价的「不用 LCEL、纯手写」版本，对比行数和理解成本。
- 问它「如果中间要插入一个自定义函数处理消息，怎么接进链」——答案是 `RunnableLambda` 或 `@chain` 装饰器，明天工具调用会用到。
- 记下 Claude Code 指出的你链里能简化的地方，明天 Day 02 写工具调用链时直接用上。

---

## 今日产出检查清单

- [ ] 用 `init_chat_model` 成功对接了至少一个 provider（Ollama / OpenAI / Anthropic）
- [ ] 同一个 model 跑通了 `invoke / stream / batch` 三种调用方式
- [ ] 用 `ChatPromptTemplate` + `MessagesPlaceholder` 拼了一个带历史的多轮对话模板
- [ ] 用 LCEL 管道符 `prompt | model | parser` 组装了至少一条链，并理解它等价于 `.pipe()` 链式调用
- [ ] 用 `PydanticOutputParser`（或 `with_structured_output`）跑通了一次结构化输出，复用了 Week 03 的 Pydantic 模型
- [ ] 让 Claude Code 审查过你的 LCEL 链，并理解了管道符的 `Runnable.pipe()` 本质

---

> **下一课预告：Day 02 — LangChain 工具调用：@tool / bind_tools**。今天我们把 Week 03 手写的「拼 messages → 调 API → 解析输出」换成了 LangChain 框架写法。明天继续把 Week 03 手写的 Function Calling 也换成框架写法：用 `@tool` 装饰器声明工具、用 `bind_tools` 绑定到 model、用 `ToolMessage` 回传执行结果，并对比手写版理解框架替你封装了什么。
