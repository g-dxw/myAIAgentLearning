# Day 02 — LangChain 工具调用：@tool / bind_tools

## 学习目标

Day 01 我们用 LCEL 把"模型 + Prompt + 输出解析"串成了链，但那条链只会说话、不会动手。今天把 Week 03 手写的 Function Calling 完整流程（定义 schema → 解析 tool_calls → 执行 → 回传结果）整体换成 LangChain 框架写法。核心是三件事：用 `@tool` 装饰器一行生成工具 schema、用 `bind_tools` 把工具绑到模型上、用 `ToolMessage` 把执行结果喂回模型。今天还**不用 LangGraph**，纯 LangChain 手写一个工具循环——为 Day 04 的图循环打底。

学完今天你能：
1. 用 `@tool` 装饰器把普通函数变成 LangChain 工具，并说清 schema 是从 docstring + 类型注解哪里推断出来的
2. 用 `model.bind_tools(...)` 绑定工具并解析返回的 `AIMessage.tool_calls`，区分它和 Week 03 手写的原始 JSON 结构
3. 手写一个完整的"解析 → 执行 → ToolMessage 回传 → 再调用"工具循环（纯 LangChain，不用图）
4. 对照 Week 03 day05 的工具六原则，判断 `@tool` 自动落了哪几条、哪几条还得自己写

---

## 一、回顾 Week 03 手写 Function Calling

Week 03 Day 02 我们不依赖任何框架，纯 `httpx + JSON` 实现了一整套 Function Calling。当时干了四件体力活：

1. **手写 Tool Schema**：每个工具要写一个 20 多行的 JSON Schema 字典，`name / description / parameters / properties / required` 一个字段都不能少。
2. **手动解析 tool_calls**：从 `response["choices"][0]["message"]["tool_calls"]` 里抠出 `function.name` 和 `function.arguments`，还要 `json.loads(arguments)`——因为 arguments 是**字符串不是字典**。
3. **手动 dispatch**：维护一个 `TOOL_REGISTRY: dict[str, Callable]` 注册表，自己写 `execute_tool_call` 查表 + `**kwargs` 解包 + try/except。
4. **手动构造 tool 角色消息**：把结果包成 `{"role": "tool", "tool_call_id": "...", "content": "..."}`，还要记得把带 `tool_calls` 的 assistant 消息也塞回 messages。

当时的 `function_calling.py` 单文件就有 **300+ 行**，其中工具定义 + 注册表 + 执行引擎就占了近 150 行，真正和"业务"相关的只有两个 impl 函数。这套手写非常有价值——它让你看穿了框架的黑盒；但也确实啰嗦。

| Week 03 手写环节 | 当时写的代码量 | 痛点 |
|------------------|---------------|------|
| 定义 2 个工具的 JSON Schema | 约 40 行 | 改一个参数要同步改 schema 和函数签名两处，容易漏 |
| TOOL_REGISTRY 注册表 + execute_tool_call | 约 40 行 | 每加一个工具都要手动注册一次 |
| json.loads(arguments) + tool_call_id 匹配 | 散落各处 | 字符串/字典类型混淆是高频 bug |
| 构造 tool 角色消息 + assistant 消息回填 | 约 20 行 | 消息顺序错了 API 直接 422 |

LangChain 的承诺是：**把"函数即工具"这件事变成一行装饰器**，schema 自动推断、注册自动完成、tool_calls 自动解析成结构化对象。今天就来验收这个承诺兑现了多少。

---

## 二、@tool 装饰器：函数即工具

### 2.1 最小示例

`@tool` 的魔法在于：它从**函数签名 + docstring**自动生成 tool schema，你不用再手写一行 JSON。

```python
"""tool_calling_demo.py — 第一部分：用 @tool 定义工具"""
from langchain_core.tools import tool


@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。city 为城市名，如 '北京'、'Tokyo'。"""
    # 实际项目这里会调天气 API，这里用本地数据演示
    weather_db = {"北京": "晴 25°C", "Tokyo": "小雨 18°C", "上海": "多云 28°C"}
    return weather_db.get(city, f"{city}：暂无天气数据")
```

装饰完后，`get_weather` 不再是普通函数，而是一个 `BaseTool` 对象，自动长出了三个属性：

```python
print(get_weather.name)         # 'get_weather'   ← 取自函数名
print(get_weather.description)  # '查询指定城市的当前天气...' ← 取自 docstring
print(get_weather.args)         # {'city': {'type': 'string', ...}} ← 取自类型注解
```

### 2.2 schema 推断规则

`@tool` 到底从哪里读什么？规则很清晰：

| schema 字段 | 来源 | 说明 |
|------------|------|------|
| `name` | 函数名 | 可用 `@tool("自定义名")` 覆盖 |
| `description` | docstring 第一行/全文 | **没有 docstring 就没有 description**，LLM 会瞎猜 |
| 参数名 | 函数形参 | 直接用形参名，建议用全称（呼应 Week 03 day05 原则 3） |
| 参数类型 | 类型注解 `: str / : int` | `str/int/float/bool/list/dict` 都能推断，复杂类型建议用 Pydantic |
| `required` | 没有默认值的形参 | 有默认值的参数自动标为可选 |
| 参数描述 | docstring 里的 Args 段 | 写 Google 风格 `Args:` 会被解析进每个参数的 description |

### 2.3 三个工具示例 + Pydantic 进阶

简单参数用类型注解就够了；参数多、有约束（枚举、范围）时，用 Pydantic `args_schema` 更稳。下面给三个工具，正好是 Day 07 多步推理 Agent 要用的"路线推荐 → 天气 → 距离"三件套。

```python
"""tool_calling_demo.py — 第二部分：三个工具 + Pydantic args_schema"""
from pydantic import BaseModel, Field
from langchain_core.tools import tool


# ── 工具 1：简单参数，纯类型注解 ──────────────────────
@tool
def get_weather(city: str, unit: str = "celsius") -> str:
    """查询指定城市的当前天气。

    Args:
        city: 城市名，如 '北京'、'上海'、'Tokyo'。
        unit: 温度单位，'celsius'（默认）或 'fahrenheit'。
    """
    weather_db = {"北京": (25, "晴"), "上海": (28, "多云"), "Tokyo": (18, "小雨")}
    temp, cond = weather_db.get(city, (20, "未知"))
    if unit == "fahrenheit":
        temp = temp * 9 // 5 + 32
    return f"{city}：{cond}，{temp}°{'F' if unit == 'fahrenheit' else 'C'}"


# ── 工具 2：用 Pydantic 做参数约束（枚举 + 范围）─────
class SearchRoutesInput(BaseModel):
    """路线检索工具的输入参数。"""
    location: str = Field(description="徒步起点，如 '北京'、'杭州'")
    difficulty: str = Field(
        description="难度等级",
        enum=["easy", "medium", "hard"],   # ← 枚举约束，LLM 只能选这三个
    )
    max_results: int = Field(default=3, ge=1, le=10, description="返回路线数，1-10")


@tool(args_schema=SearchRoutesInput)
def search_routes(location: str, difficulty: str, max_results: int = 3) -> str:
    """根据地点和难度检索徒步路线。当用户想找徒步/爬山路线时使用。"""
    # 模拟检索（Day 07 会接 Week 05 的向量库）
    routes = {
        ("北京", "easy"): ["香山、百望山、奥林匹克森林公园"],
        ("杭州", "hard"): ["千八穿越、天目山七尖"],
    }
    hits = routes.get((location, difficulty), [f"{location} 暂无 {difficulty} 路线"])
    return f"为 {location}({difficulty}) 找到 {len(hits[:max_results])} 条：{'、'.join(hits[:max_results])}"


# ── 工具 3：返回结构化数据 ──────────────────────────
@tool
def calculate_distance(start: str, end: str) -> str:
    """计算两个地点之间的直线距离（公里）。用于规划出行路线。"""
    # 模拟距离表
    dist_table = {("北京", "上海"): 1213, ("北京", "Tokyo"): 2100, ("杭州", "上海"): 175}
    d = dist_table.get((start, end)) or dist_table.get((end, start), None)
    if d is None:
        return f"暂无 {start} ↔ {end} 的距离数据"
    return f"{start} → {end} 直线距离约 {d} 公里"
```

### 2.4 对比 Week 03 手写 JSON Schema

同一个 `get_weather`，两种写法的代码量对比：

```python
# ── Week 03 手写（约 22 行 JSON）──
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
# 还要单独写 impl 函数 + 注册到 TOOL_REGISTRY


# ── Week 06 @tool（约 5 行）──
@tool
def get_weather(city: str, unit: str = "celsius") -> str:
    """获取指定城市的当前天气信息。city 为城市名，unit 为温度单位。"""
    ...
```

| 维度 | Week 03 手写 | Week 06 @tool |
|------|-------------|---------------|
| schema 与 impl | 分离两处，改一处漏一处 | 一处，函数即 schema |
| description | 手写字符串 | docstring 自动读 |
| 参数约束 | 手写 JSON Schema | 类型注解 / Pydantic |
| 注册 | 手动 `TOOL_REGISTRY[name] = func` | 装饰器自动完成 |
| 单工具代码量 | 约 30 行 | 约 5 行 |

---

## 三、bind_tools：把工具绑到模型上

### 3.1 绑定与调用

`bind_tools` 返回一个"绑定了工具的模型 Runnable"，调用方式和普通模型一样，只是返回的 `AIMessage` 会带 `tool_calls` 字段。

```python
"""tool_calling_demo.py — 第三部分：bind_tools 绑定与调用"""
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage

# Day 01 用过的 init_chat_model，统一初始化
model = init_chat_model("gpt-4o-mini", temperature=0)

# 把三个工具绑上去
tools = [get_weather, search_routes, calculate_distance]
model_with_tools = model.bind_tools(tools)

# 发一条需要工具的消息
ai_msg: "AIMessage" = model_with_tools.invoke([
    HumanMessage(content="北京今天多少度？顺便查一下北京有什么 easy 的徒步路线"),
])

print(type(ai_msg).__name__)     # AIMessage
print(ai_msg.content)            # '' 或 None（调工具时通常不回文字）
print(ai_msg.tool_calls)         # ← 关键：结构化的工具调用列表
```

### 3.2 AIMessage.tool_calls 的结构

注意：LangChain 已经帮你把 Week 03 里那个 `json.loads(arguments)` 的坑填了——`args` 直接是 **dict**，不是字符串。

```python
# ai_msg.tool_calls 长这样（已经是结构化对象，无需再 json.loads）：
[
    {"name": "get_weather",     "args": {"city": "北京"},                       "id": "call_abc1"},
    {"name": "search_routes",   "args": {"location": "北京", "difficulty": "easy"}, "id": "call_abc2"},
]
```

| Week 03 手写 tool_calls | LangChain AIMessage.tool_calls |
|------------------------|-------------------------------|
| `tc["function"]["name"]` | `tc["name"]` |
| `json.loads(tc["function"]["arguments"])`（字符串！） | `tc["args"]`（已是 dict） |
| `tc["id"]` | `tc["id"]` |
| 要自己判断 `finish_reason == "tool_calls"` | 直接看 `ai_msg.tool_calls` 是否非空 |

### 3.3 tool_choice 参数

`bind_tools` 的第二个参数 `tool_choice` 控制 LLM 何时调用工具，对应 Week 03 Day 02 讲过的四种模式：

```python
# auto（默认）：LLM 自己决定调不调
model.bind_tools(tools, tool_choice="auto")

# any / required：强制必须调至少一个工具
model.bind_tools(tools, tool_choice="any")        # LangChain 通用写法
# 注：OpenAI 原生用 "required"，LangChain 内部会做适配

# none：禁止调用工具（即使绑了也无视）
model.bind_tools(tools, tool_choice="none")

# 指定工具：只能调这一个
model.bind_tools(tools, tool_choice="get_weather")
```

| 模式 | 何时用 | Week 03 对应值 |
|------|--------|---------------|
| `"auto"` | 通用 Agent，让 LLM 自己判断 | `"auto"` |
| `"any"` / `"required"` | 批量处理，强制每条都调工具 | `"required"` |
| `"none"` | 纯对话模式 | `"none"` |
| `"工具名"` | 路由模式，强制只调指定工具 | `{"type":"function","function":{"name":...}}` |

---

## 四、ToolMessage 与完整工具循环

### 4.1 为什么要 ToolMessage

模型返回 `tool_calls` 只是"声明要调工具"，真正执行得我们自己来。执行完的结果必须用 `ToolMessage` 包起来回传，**且 `tool_call_id` 必须对上**——这一步和 Week 03 手写的 `{"role":"tool","tool_call_id":...}` 完全对应，只是换了 LangChain 的消息类。

```python
"""tool_calling_demo.py — 第四部分：ToolMessage 回传"""
from langchain_core.messages import AIMessage, ToolMessage

# 假设 ai_msg 是上一步带 tool_calls 的 AIMessage
# 执行第一个工具调用，结果包成 ToolMessage
tc = ai_msg.tool_calls[0]                      # {"name":"get_weather","args":{"city":"北京"},"id":"call_abc1"}
result = get_weather.invoke(tc["args"])        # 直接用工具对象的 invoke，传入 args dict
tool_msg = ToolMessage(
    content=str(result),        # 工具执行结果，必须是字符串
    tool_call_id=tc["id"],      # ← 必须对上 AIMessage 里那个 id，否则报错
)
```

### 4.2 工具映射表 + 完整循环

把 Week 03 的 `TOOL_REGISTRY` 换成 `{tool.name: tool}` 的字典，循环逻辑保持"调模型 → 有 tool_calls 就执行 → 回传 → 再调"的四步。今天还**不用 LangGraph**，纯 while 循环——这正是 Day 04 要用 StateGraph 替换的部分。

```python
"""tool_calling_demo.py — 第五部分：完整工具循环（纯 LangChain，不用图）"""
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

# 工具名 → 工具对象的映射（替代 Week 03 的 TOOL_REGISTRY）
TOOLS = [get_weather, search_routes, calculate_distance]
TOOL_MAP = {t.name: t for t in TOOLS}

model = init_chat_model("gpt-4o-mini", temperature=0)
model_with_tools = model.bind_tools(TOOLS)


def run_agent(user_input: str, max_iter: int = 5) -> str:
    """
    手写工具循环：调模型 → 解析 tool_calls → 执行 → ToolMessage 回传 → 再调。

    这就是 Week 03 的 while True 循环，只是消息类型换成了 LangChain 的 Message 类。
    Day 04 会用 LangGraph 的条件边把这个 while 变成图。
    """
    messages = [
        SystemMessage(content="你是一个徒步出行助手，可以查天气、检索路线、算距离。"),
        HumanMessage(content=user_input),
    ]

    for i in range(max_iter):
        # ① 调用带工具的模型
        ai_msg = model_with_tools.invoke(messages)
        messages.append(ai_msg)                          # ← 关键：assistant 消息必须回填

        # ② 没有 tool_calls → 模型已给出最终回答，退出循环
        if not ai_msg.tool_calls:
            return ai_msg.content

        # ③ 有 tool_calls → 逐个执行，结果包成 ToolMessage 回传
        print(f"[iter {i+1}] 模型请求调用 {len(ai_msg.tool_calls)} 个工具")
        for tc in ai_msg.tool_calls:
            tool_obj = TOOL_MAP.get(tc["name"])
            if tool_obj is None:
                content = f"错误：未知工具 '{tc['name']}'"
            else:
                try:
                    content = str(tool_obj.invoke(tc["args"]))
                except Exception as e:
                    content = f"工具执行异常：{e}"       # 错误也字符串化回传，让 LLM 自己应对
            messages.append(ToolMessage(content=content, tool_call_id=tc["id"]))
            print(f"   - {tc['name']}({tc['args']}) => {content[:40]}")
        # ④ 循环回到 ①，带着工具结果再调一次模型

    return "达到最大轮数，强制停止"


if __name__ == "__main__":
    print(run_agent("我想从北京去上海徒步，帮我查北京和上海的天气，再算两地距离"))
```

### 4.3 消息流对照

这个循环的消息演化过程和 Week 03 一模一样，只是类型从 dict 换成了 Message 对象：

```
回合开始: [System, Human]

① invoke → AIMessage(tool_calls=[w, r])
   messages: [System, Human, AIMessage(tool_calls)]

② 执行 w → ToolMessage(id=w)
   执行 r → ToolMessage(id=r)
   messages: [System, Human, AIMessage(tool_calls), ToolMsg_w, ToolMsg_r]

③ 再 invoke → AIMessage(content="最终回答", tool_calls=[])
   messages: [..., AIMessage(回答)]   ← tool_calls 为空，循环退出
```

> 关键不变量：**带 tool_calls 的 AIMessage 必须先回填，再接 ToolMessage**。顺序错了（ToolMessage 在 AIMessage 前面）OpenAI 直接 422。这条 Week 03 踩过的坑，LangChain 不替你兜底——它只是把消息包装成了对象，顺序还得你自己保证。

---

## 五、工具设计原则回顾：@tool 落实了哪几条

Week 03 Day 05 提了工具六原则。现在回头看，`@tool` 帮我们自动落了哪几条，哪几条还得自己写。

| 原则 | @tool 是否自动落实 | 说明 |
|------|------------------|------|
| 1. 单一职责 | 否 | 装饰器不管你函数干几件事，得自己拆 |
| 2. 清晰触发条件（description） | **半自动** | docstring 自动变成 description，但写不写清楚是你的事 |
| 3. 好参数名 | 否 | 形参名直接当 schema 参数名，命名好坏全看你 |
| 4. 默认值 | **自动** | Python 默认值 `unit="celsius"` 自动标成可选参数 |
| 5. 错误处理 | 否 | 工具函数内部的 try/except 还得自己写 |
| 6. 幂等性 | 否 | 装饰器不区分读/写操作，副作用得自己控 |

### 5.1 好工具 vs 坏工具（@tool 版）

```python
# ── ❌ 坏工具：docstring 敷衍，参数缩写，没有错误处理 ──
@tool
def search(q: str) -> str:
    """搜索"""
    resp = httpx.get(f"https://api.example.com/search?q={q}")  # 无超时、无异常处理
    return resp.text

# 问题：description 只有"搜索"两个字 → LLM 不知道何时用；
#       参数名 q 有歧义；网络调用无 try/except → 一超时整个 Agent 崩


# ── ✅ 好工具：docstring 写场景，参数全称，内部 try/except ──
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
        return "错误：搜索超时，建议简化查询词后重试"      # 错误也回传给 LLM
    except Exception as e:
        return f"错误：{e}"
```

### 5.2 @tool 的额外能力

除了自动生成 schema，`@tool` 还顺手解决了 Week 03 的几个老问题：

- **自动注册**：装饰完就是 `BaseTool` 对象，直接丢进 `tools` 列表，不用手动维护注册表。
- **统一调用接口**：`tool.invoke(args_dict)` 是所有工具的统一入口，dispatch 逻辑被收敛进框架。
- **直接转 ToolMessage**：`tool.invoke` 在 AgentExecutor 等高层封装里会自动产出 ToolMessage，今天手写循环我们手动包，是为了看清底层。
- **可组合**：工具本身是 Runnable，能和 LCEL 链拼起来（Day 01 的 `|` 管道）。

---

## 动手实验

### 🟢 青铜级：跑通 `tool_calling_demo.py`

把上面五个部分的代码拼成一个可运行文件，跑 `run_agent("我想从北京去上海徒步...")`，观察终端打印的 `[iter N] 模型请求调用 X 个工具` 日志，确认你看到了"调模型→执行工具→回传→再调模型给最终回答"的完整两轮。把输出贴到笔记里。

### 🟡 白银级：加一个工具并测 tool_choice

自己用 `@tool` 写一个 `send_email(to: str, subject: str, body: str)` 工具（模拟即可，不真发），绑到模型上。然后用三种 `tool_choice` 各调一次同一条消息"帮我给 alice@example.com 发封问候邮件"：
- `"auto"`：观察 LLM 是否调工具
- `"any"`：观察是否强制调了
- `"send_email"`：观察是否只调了这一个

记录三者的 `ai_msg.tool_calls` 差异。

### 🔴 王者级：手写多轮链式调用

构造一个需要**链式工具调用**的提问，比如"查北京天气，如果低于 20 度就再查北京有什么 easy 路线，最后算北京到上海的距离"。让你的 `run_agent` 循环跑出 2 轮以上的工具调用（第一轮查天气，第二轮根据天气结果决定是否查路线）。思考：纯 while 循环处理这种"依赖前一步结果"的链式调用，代码已经开始变绕了——这正是 Day 04 LangGraph 条件边要解决的问题，提前感受一下痛点。

---

## 踩坑记录 🕳️

### 坑 1：@tool 的函数没写 docstring → description 为空

```python
@tool
def get_weather(city: str) -> str:
    # 没有 docstring！
    return f"{city} 25°C"

print(get_weather.description)   # ''  ← 空字符串
# 结果：LLM 根本不知道这个工具干嘛的，几乎不会调用它
```

**解决**：`@tool` 的 description 完全来自 docstring，没 docstring 等于没 description。每个工具函数第一行必须写清楚"这是什么工具、什么时候用"。呼应 Week 03 day05 原则 2。

### 坑 2：把 args 当字符串处理（Week 03 的肌肉记忆）

```python
# ❌ Week 03 的老习惯，在 LangChain 里会报错
import json
args = json.loads(tc["args"])    # TypeError: the JSON object must be str...
city = args["city"]

# ✅ LangChain 的 tool_calls["args"] 已经是 dict
city = tc["args"]["city"]
```

**解决**：Week 03 里 `arguments` 是 JSON 字符串必须 `json.loads`；LangChain 已经帮你解析好了，`tc["args"]` 直接就是 dict。换框架时要改掉这个肌肉记忆。

### 坑 3：ToolMessage 的 tool_call_id 对不上

```python
# ❌ id 拼错或忘了传
ToolMessage(content="北京 25°C")                       # 没有 tool_call_id
ToolMessage(content="北京 25°C", tool_call_id="wrong") # 和 AIMessage 里的 id 对不上
# 结果：OpenAI API 报 400 "tool_call_ids must match previous tool_calls"
```

**解决**：每个 ToolMessage 的 `tool_call_id` 必须严格等于对应 `ai_msg.tool_calls[i]["id"]`。循环里直接用 `tc["id"]` 传进去，别手写 id。

### 坑 4：忘记把带 tool_calls 的 AIMessage 回填到 messages

```python
# ❌ 只 append ToolMessage，不 append AIMessage
for tc in ai_msg.tool_calls:
    messages.append(ToolMessage(content=..., tool_call_id=tc["id"]))
# 再 invoke 时 LLM 困惑：这些 ToolMessage 是谁调的？→ 报错或乱答

# ✅ 先 append AIMessage，再 append ToolMessage
messages.append(ai_msg)
for tc in ai_msg.tool_calls:
    messages.append(ToolMessage(content=..., tool_call_id=tc["id"]))
```

**解决**：消息顺序必须是 `AIMessage(tool_calls) → ToolMessage → ToolMessage → ...`。这条 Week 03 Day 02 坑 4 已经踩过，换了框架坑还在——LangChain 只包装消息类型，不替你管顺序。

### 坑 5：工具返回 None 或非字符串

```python
@tool
def get_weather(city: str) -> dict:           # 返回类型标了 dict
    return {"city": city, "temp": 25}          # 返回 dict

# ToolMessage(content=result) 时 content 不是 str → 序列化/解析出问题
```

**解决**：`ToolMessage.content` 必须是字符串。工具函数要么返回 `str`，要么在包 ToolMessage 前 `str(result)` / `json.dumps(result, ensure_ascii=False)`。复杂结构建议返回 JSON 字符串，让 LLM 自己解析。

---

## 副线笔记：对比 Week 03 手写 Function Calling

今天的主线是把 Week 03 Day 02 手写的 Function Calling 换成 LangChain 写法。两套代码做的是**完全一样的事**，差别只在工程量。这正是 Week 06 开篇说的"手写过，所以用框架不是黑盒"。

### 详细对比表

| 维度 | Week 03 手写 | Week 06 LangChain |
|------|-------------|-------------------|
| **schema 定义** | 手写 20+ 行 JSON Schema 字典 | `@tool` 装饰函数，从 docstring + 注解自动生成 |
| **参数约束** | JSON Schema 的 enum/required | 类型注解 + Pydantic `Field(enum=, ge=, le=)` |
| **工具注册** | 手动 `TOOL_REGISTRY[name] = func` | 装饰器自动注册，`tools = [t1, t2]` 直接用 |
| **绑定到模型** | 每次请求 `body["tools"] = TOOLS` | `model.bind_tools(tools)` 一次，返回带工具的 Runnable |
| **tool_calls 解析** | `tc["function"]["name"]` + `json.loads(tc["function"]["arguments"])` | `tc["name"]` + `tc["args"]`（已是 dict） |
| **是否调工具判断** | `finish_reason == "tool_calls"` | `ai_msg.tool_calls` 是否非空 |
| **结果回传格式** | `{"role":"tool","tool_call_id":...,"content":...}` | `ToolMessage(content=..., tool_call_id=...)` |
| **错误处理** | 自己 try/except + 字符串化 | 同样自己写，但错误字符串回传的模式一致 |
| **tool_choice** | 请求体里 `"tool_choice": "auto"` | `bind_tools(..., tool_choice="auto")` |
| **单工具代码量** | 约 30 行（schema + impl + 注册） | 约 5 行（@tool + impl） |
| **完整循环代码量** | 约 80 行 | 约 30 行 |
| **底层逻辑** | 手写裸 HTTP + JSON | 框架封装，但消息顺序、id 匹配仍需自己保证 |

### 结论：50 行压到 10 行，但底层没变

LangChain 把 Week 03 那套**约 50 行的工具定义+注册+解析样板代码**压到了**约 10 行**（`@tool` + `bind_tools` + `ToolMessage`）。但仔细看对比表会发现：**底层逻辑一行没变**——还是要解析 tool_calls、还是要按顺序回填消息、还是 tool_call_id 必须对上、还是要 try/except 处理工具异常、还是 max_iter 防死循环。LangChain 帮你省的是"重复的样板"，省不了的是"对机制的理解"。

这就是手写的价值：当你今天看到 `ToolMessage(content=..., tool_call_id=...)` 时，你脑子里会自动浮现 Week 03 那个 `{"role":"tool","tool_call_id":...,"content":...}` 字典——你**知道这一行在干什么**，而不是把它当成一个黑盒 API 调用。等 Day 04 LangGraph 把这个 while 循环再抽象成"条件边 + 节点"时，你同样能看穿：图的循环边就是 `while True`，节点就是循环体里的几行代码。

> 一句话：**框架是站在手写的肩膀上的糖，不是替代品。** 手写过的人吃糖知道甜在哪，没手写过的人吃糖只知道甜、不知道为什么甜。

---

## 今日产出检查清单

- [ ] 用 `@tool` 定义了 3 个工具（get_weather / search_routes / calculate_distance），并能打印出自动生成的 `name / description / args`
- [ ] 用 `model.bind_tools(...)` 绑定工具，成功拿到带 `tool_calls` 的 `AIMessage`，确认 `args` 已是 dict
- [ ] 手写了完整的 `run_agent` 工具循环（解析 → 执行 → ToolMessage 回传 → 再调），跑通至少一个两轮调用的例子
- [ ] 测过至少两种 `tool_choice`（auto / any 或指定工具），观察调用行为差异
- [ ] 能对照表格说出 @tool 自动落实了六原则的哪几条、哪几条还得自己写
- [ ] 产出文件 `tool_calling_demo.py` 可独立运行（无 API key 时至少能跑模拟模式）

---

> **下一课预告：Day 03 — LangGraph 入门：StateGraph / Node / Edge**。今天我们用 LangChain 手写了一个 while 工具循环，逻辑清楚了但代码已经开始绕——链式调用、条件分支都得自己 if/else 拼接。明天请出 LangGraph：用 `StateGraph` 把"状态"显式化，用"Node"把每一步变成函数节点，用"Edge"把控制流变成边，把今天的 while 循环重写成一张图。你会发现，图不过是把循环的每一行拍平成节点和边而已。
