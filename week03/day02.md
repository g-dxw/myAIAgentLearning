# Day 02 — Function Calling 完整流程：手写实现

## 学习目标

**不依赖框架，纯手工实现一次 Function Calling**。理解 LLM 如何决定调用工具、我们如何执行、结果如何送回。这是 Agent 循环的心脏。

---

## 一、Tool Schema 格式定义

Function Calling 的第一步是告诉 LLM：「你有这些工具可以用」。你把工具的描述写成 JSON Schema，塞进 API 请求的 `tools` 参数。

### OpenAI 兼容的 Tool Schema

```python
"""tools.py — 工具定义"""
from typing import Any

# 工具 1：获取天气
get_weather_schema = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "获取指定城市的当前天气信息",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名，如 '北京'、'上海'、'Tokyo'",
                },
                "unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                    "description": "温度单位，默认 celsius",
                },
            },
            "required": ["city"],
        },
    },
}

# 工具 2：数学计算
calculate_schema = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": "执行数学运算，支持四则运算和幂运算",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，如 '2 + 3 * 4'",
                },
            },
            "required": ["expression"],
        },
    },
}

# 汇总列表
TOOLS = [get_weather_schema, calculate_schema]
```

### 三个关键要点

| 字段 | 作用 | 踩坑点 |
|------|------|--------|
| `name` | 工具名，LLM 用它来标识 | 只能用 `a-z`, `A-Z`, `0-9`, `_`, `-`，不能用空格 |
| `description` | LLM 判断是否用这个工具的依据 | **写详细！** 越模糊 LLM 越不会用 |
| `parameters` | JSON Schema 格式的参数约束 | `required` 字段必须写，否则 LLM 可能不传参数 |

> **为什么不用 Google 的 FunctionDeclaration 格式？**
> 2026 年 OpenAI 格式是事实标准，Anthropic、Google、国产模型全都兼容。学会一套，各平台通用。

---

## 二、模拟真实 LLM 返回 tool_calls

由于我们暂时不想真花钱调 API，先**手动构造** LLM 返回的 `tool_calls` 来理解数据结构。等看懂了解析逻辑，再替换成真实 API 调用。

```python
"""simulate_llm.py — 模拟 LLM 返回 tool_calls"""

# 场景：用户问「东京今天多少度？顺便算一下 2^10」
user_message = {"role": "user", "content": "东京今天多少度？顺便算一下 2^10"}

# 模拟 LLM 响应（真实 API 会返回类似结构）
llm_response = {
    "id": "chatcmpl-abc123",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,  # content 为 None 表示没直接回答
                "tool_calls": [
                    {
                        "id": "call_weather_001",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Tokyo", "unit": "celsius"}',
                        },
                    },
                    {
                        "id": "call_calc_001",
                        "type": "function",
                        "function": {
                            "name": "calculate",
                            "arguments": '{"expression": "2**10"}',
                        },
                    },
                ],
            },
            "finish_reason": "tool_calls",  # ← 关键信号：LLM 要求调用工具
        }
    ],
}
```

### 数据结构解读

```
assistant message
├── content: null           ← 没有文本回答
├── tool_calls: [           ← 可能有多个工具调用（并行！）
│   ├── {
│   │   ├── id: "call_xxx"  ← 唯一标识，后面 tool 角色要引用它
│   │   ├── type: "function"
│   │   └── function: {
│   │       ├── name: "get_weather"
│   │       └── arguments: '{"city":"Tokyo"}'  ← 字符串！需要 json.loads
│   │   }
│   └── ...
]
└── finish_reason: "tool_calls"  ← API 返回这个告诉你为什么停了
```

### 关键理解

1. **`content` 是 `null`**：LLM 选择调用工具时，通常不回文字，直接返回 `tool_calls`。但也有「边回答边调用」的情况（少见）。
2. **`arguments` 是字符串**：不是字典！必须 `json.loads(arguments)` 转成 Python dict。
3. **`finish_reason` 是 `"tool_calls"`**：这是你判断「LLM 是不是要调工具」的依据。
4. **并行调用**：一个 assistant 消息可以携带**多个** `tool_calls`，LLM 会分析哪些调用互不依赖，一次返回。

---

## 三、执行函数的 Handler 模式

有了 `tool_calls`，我们需要一个**注册-派发机制**：把工具名映射到实际的 Python 函数。这就是 **Handler 模式**。

```python
"""handler.py — 工具执行引擎"""

import json
import math
from typing import Any, Callable


# ===== 1. 工具的实际实现 =====

def get_weather_impl(city: str, unit: str = "celsius") -> str:
    """模拟查询天气"""
    # 真实场景这里会调天气 API
    weather_db = {
        "北京": {"temp": 22, "condition": "晴"},
        "上海": {"temp": 28, "condition": "多云"},
        "Tokyo": {"temp": 18, "condition": "小雨"},
        "New York": {"temp": 15, "condition": "阴"},
    }
    data = weather_db.get(city, {"temp": 20, "condition": "未知"})
    unit_symbol = "°C" if unit == "celsius" else "°F"
    return f"{city} 当前天气：{data['temp']}{unit_symbol}，{data['condition']}"


def calculate_impl(expression: str) -> str:
    """安全执行数学表达式"""
    # ⚠️ eval 有安全风险！真实场景用 numexpr 或 ast 解析
    allowed_names = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "pow": pow, "math": math,
        "pi": math.pi, "e": math.e,
    }
    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return f"{expression} = {result}"
    except Exception as e:
        return f"计算错误：{str(e)}"


# ===== 2. 注册表模式（Registry Pattern） =====

# 维护工具名 → 函数的映射
TOOL_REGISTRY: dict[str, Callable] = {
    "get_weather": get_weather_impl,
    "calculate": calculate_impl,
}

# 可选：自动注册装饰器（进阶用法）
def register_tool(name: str):
    """装饰器：自动注册工具"""
    def decorator(func: Callable):
        TOOL_REGISTRY[name] = func
        return func
    return decorator

@register_tool("hello")
def hello_impl(name: str = "World") -> str:
    return f"Hello, {name}!"


# ===== 3. 执行引擎 =====

def execute_tool_call(tool_call: dict) -> dict:
    """
    执行单个 tool_call，返回 tool 角色消息。
    
    输入格式（来自 LLM 响应）：
    {
        "id": "call_xxx",
        "type": "function",
        "function": {
            "name": "get_weather",
            "arguments": '{"city": "Tokyo"}'
        }
    }
    
    输出格式（发回给 LLM）：
    {
        "role": "tool",
        "tool_call_id": "call_xxx",
        "content": "Tokyo 当前天气：18°C，小雨"
    }
    """
    func_name = tool_call["function"]["name"]
    func_args = json.loads(tool_call["function"]["arguments"])
    tool_call_id = tool_call["id"]
    
    # 查找注册的函数
    func = TOOL_REGISTRY.get(func_name)
    if func is None:
        result = f"错误：未知工具 '{func_name}'"
    else:
        try:
            result = func(**func_args)
        except TypeError as e:
            result = f"参数错误：{str(e)}"
        except Exception as e:
            result = f"执行异常：{str(e)}"
    
    # 返回 tool 角色消息
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": str(result),
    }
```

### Handler 模式为什么重要

| 问题 | Handler 方案 |
|------|------------|
| 硬编码 if-else 链 | 注册表 + 名称映射，新增工具只需 `TOOL_REGISTRY["xxx"] = func` |
| 参数不匹配 | `json.loads` 解包 + `**func_args` 自动匹配 |
| 安全风险 | eval 限制命名空间（或用 `numexpr`、`ast.literal_eval`） |
| 测试困难 | 每个工具是独立函数，可以直接单元测试 |

---

## 四、把结果送回 LLM（完整工具调用回合）

工具执行完毕后，把 `tool` 角色消息**追加到消息列表**，重新发给 LLM。LLM 会根据工具返回的结果组织最终回答。

```python
"""full_round.py — 完整的工具调用回合"""

import json
import httpx
import os

# ---------- 复用前面定义的模块 ----------
# 假设 tools.py、handler.py 在同一个目录
from tools import TOOLS
from handler import TOOL_REGISTRY, execute_tool_call


def call_llm(messages: list[dict], tools: list | None = None) -> dict:
    """简化版 LLM 调用"""
    api_key = os.getenv("OPENAI_API_KEY", "sk-your-key")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "gpt-4o",
        "messages": messages,
        "tools": tools,
        "temperature": 0.7,
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


def run_tool_round(user_input: str) -> list[dict]:
    """
    一次完整的 Function Calling 回合：
    User → LLM (返回 tool_calls) → 执行工具 → 结果发回 → LLM 整合回答
    """
    messages = [{"role": "user", "content": user_input}]
    
    # Step 1: 发消息给 LLM（带上工具定义）
    print(f">>> 用户: {user_input}\n")
    response = call_llm(messages, tools=TOOLS)
    
    assistant_msg = response["choices"][0]["message"]
    finish_reason = response["choices"][0]["finish_reason"]
    
    # Step 2: 检查是否要调用工具
    if finish_reason == "tool_calls":
        tool_calls = assistant_msg.get("tool_calls", [])
        print(f">>> LLM 请求调用 {len(tool_calls)} 个工具:")
        
        # 把 assistant 消息加入历史（包含 tool_calls）
        messages.append({
            "role": "assistant",
            "content": assistant_msg.get("content"),
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": tc["type"],
                    "function": tc["function"],
                }
                for tc in tool_calls
            ],
        })
        
        # Step 3: 依次执行每个工具
        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            tool_args = json.loads(tc["function"]["arguments"])
            print(f"   - {tool_name}({json.dumps(tool_args, ensure_ascii=False)})")
            
            tool_result = execute_tool_call(tc)
            messages.append(tool_result)
            print(f"     => {tool_result['content']}")
        
        # Step 4: 把工具结果发回 LLM，获取最终回答
        print("\n>>> 将工具结果发回 LLM...")
        final_response = call_llm(messages)
        final_msg = final_response["choices"][0]["message"]
        print(f"\n>>> LLM 最终回答: {final_msg['content']}")
    
    else:
        # LLM 直接回答，不需要工具
        print(f">>> LLM 直接回答: {assistant_msg['content']}")
    
    return messages


# ---------- 测试 ----------
if __name__ == "__main__":
    # 场景 1：需要调用工具
    run_tool_round("东京今天多少度？顺便算一下 2^10")
    
    print("\n" + "=" * 50 + "\n")
    
    # 场景 2：不需要工具（纯聊天）
    run_tool_round("你好，今天天气不错")
    
    print("\n" + "=" * 50 + "\n")
    
    # 场景 3：需要多个工具
    run_tool_round("北京的天气怎么样？再帮我算 (25 + 17) * 3")
```

### 消息流图解

```
回合开始时 messages = [user]

① 发 [user] + tools → LLM
② LLM 返回 {role:assistant, tool_calls:[...], finish_reason:"tool_calls"}
③ messages += [assistant_msg_with_tool_calls]
④ 对每个 tool_call → execute → 产出 tool 消息
⑤ messages += [tool_result_1, tool_result_2, ...]
⑥ 把 messages 发回 LLM（此时已有 user + assistant(含tool_calls) + tool×N）
⑦ LLM 返回 {role:assistant, content:"最终回答", finish_reason:"stop"}
```

### 为什么要把 assistant 消息加进去？

关键点：**LLM 必须看到自己刚才说了什么**。如果你不把包含 `tool_calls` 的 assistant 消息加入历史，LLM 看到一串 tool 消息就不知道它们对应什么请求。

```python
# ❌ 错误：只加 tool 结果，不加 assistant 消息
messages = [user_msg, tool_result_1, tool_result_2]
# LLM 会困惑：这些 tool 结果是谁调用的？

# ✅ 正确：完整的对话上下文
messages = [
    user_msg,
    {"role": "assistant", "content": None, "tool_calls": [...]},
    tool_result_1,
    tool_result_2,
]
# LLM 能理解：用户问了 → 我调了工具 → 这是结果 → 现在整合回答
```

---

## 五、多工具组合调用

现实场景中，LLM 可能会在一次响应中返回**多个 `tool_calls`**，而且后续回答**可能再次触发工具调用**（多轮工具调用）。

### 并行 vs 串行

LLM 返回的多个 `tool_calls` 是**逻辑上并行**的——它们互不依赖。但实际执行时，我们可以选：

```python
"""multi_tool.py — 多工具处理"""

import json
from handler import execute_tool_call


def process_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """
    处理一组 tool_calls。
    所有调用互不依赖，可以并行执行。
    
    这里先演示串行版本（简单），
    实际上可以用 ThreadPoolExecutor 并行加速。
    """
    tool_messages = []
    for tc in tool_calls:
        result = execute_tool_call(tc)
        tool_messages.append(result)
    return tool_messages


# ===== 进阶：并行执行版本 =====

from concurrent.futures import ThreadPoolExecutor, as_completed

def process_tool_calls_parallel(tool_calls: list[dict]) -> list[dict]:
    """并行执行互不依赖的 tool_calls，性能更强"""
    tool_messages = [None] * len(tool_calls)  # 保持顺序
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        # 提交所有任务
        future_map = {
            executor.submit(execute_tool_call, tc): i
            for i, tc in enumerate(tool_calls)
        }
        # 按完成顺序收集结果
        for future in as_completed(future_map):
            idx = future_map[future]
            tool_messages[idx] = future.result()
    
    return tool_messages


# ===== 完整的多轮工具调用循环 =====

def agent_loop(messages: list[dict], max_turns: int = 5) -> list[dict]:
    """
    多轮工具调用循环。
    LLM 可能第一次返回 tool_calls，
    执行后第二次又返回 tool_calls（链式调用）。
    max_turns 防止无限循环。
    """
    from tools import TOOLS
    
    turn = 0
    while turn < max_turns:
        turn += 1
        print(f"\n--- Turn {turn} ---")
        
        response = call_llm(messages, tools=TOOLS)
        choice = response["choices"][0]
        assistant_msg = choice["message"]
        finish_reason = choice["finish_reason"]
        
        if finish_reason == "tool_calls":
            tool_calls = assistant_msg.get("tool_calls", [])
            print(f"LLM 要求调用 {len(tool_calls)} 个工具")
            
            # 加入 assistant 消息
            messages.append(assistant_msg)
            
            # 执行工具
            tool_results = process_tool_calls_parallel(tool_calls)
            messages.extend(tool_results)
            
            # 如果有结果就打印
            for tr in tool_results:
                print(f"  => {tr['content']}")
            
            # 继续循环（可能再次触发工具调用）
        else:
            # LLM 回答完成或遇到其他 finish_reason
            print(f"LLM 回答: {assistant_msg.get('content', '')}")
            messages.append(assistant_msg)
            break
    
    return messages
```

### 多工具调用的三个陷阱

| 陷阱 | 表现 | 解决 |
|------|------|------|
| **工具名冲突** | 两个工具同名 | 注册表设计成 key-value，后注册的覆盖先注册的 |
| **参数类型错误** | LLM 传字符串但函数要 int | `execute_tool_call` 里加类型校验或转换 |
| **无限循环** | LLM 反复调同一个工具，结果又让它调 | `max_turns` 硬限制 + 检测重复调用模式 |

---

## 六、Tool Choice 四种模式对比

`tool_choice` 参数控制**LLM 何时调用工具**。它是 API 请求里的一个字段。

```python
# tool_choice 的四种值
tool_choice_options = {
    "auto":       None,   # 默认：LLM 自己决定是否调工具
    "required":   "required",  # 强制 LLM 必须调工具（至少调一个）
    "none":       "none",      # 禁止调工具（忽略 tools 定义）
    "specified":  {"type": "function", "function": {"name": "get_weather"}},
    # ↑ 强制 LLM 只能调指定工具
}
```

### 各模式详解

```python
"""tool_choice_demo.py — 四种 tool_choice 模式演示"""

def call_with_tool_choice(
    messages: list[dict],
    tool_choice: str | dict | None = "auto",
) -> dict:
    """演示不同 tool_choice 的效果"""
    api_key = os.getenv("OPENAI_API_KEY", "sk-your-key")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "gpt-4o",
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": tool_choice,
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


# ===== 场景对比 =====
test_messages = [{"role": "user", "content": "你好，今天心情不错"}]

print("=== tool_choice = 'auto' ===")
# LLM 判断：用户没问天气也没让计算 → 直接聊天
resp = call_with_tool_choice(test_messages, tool_choice="auto")
print(f"finish_reason: {resp['choices'][0]['finish_reason']}")
print(f"回答: {resp['choices'][0]['message']['content']}")
# 结果：正常聊天，不调工具

print("\n=== tool_choice = 'required' ===")
resp = call_with_tool_choice(test_messages, tool_choice="required")
print(f"finish_reason: {resp['choices'][0]['finish_reason']}")
# 结果：强制调工具！即使用户没要求，LLM 也会选一个工具调用
msg = resp['choices'][0]['message']
if msg.get('tool_calls'):
    for tc in msg['tool_calls']:
        print(f"  强制调用: {tc['function']['name']}")

print("\n=== tool_choice = 'none' ===")
resp = call_with_tool_choice(test_messages, tool_choice="none")
print(f"finish_reason: {resp['choices'][0]['finish_reason']}")
# 结果：即使 tools 传了，LLM 完全无视，纯聊天

print("\n=== tool_choice = 指定工具 ===")
resp = call_with_tool_choice(
    test_messages,
    tool_choice={"type": "function", "function": {"name": "get_weather"}},
)
print(f"finish_reason: {resp['choices'][0]['finish_reason']}")
msg = resp['choices'][0]['message']
if msg.get('tool_calls'):
    for tc in msg['tool_calls']:
        print(f"  只能调: {tc['function']['name']}")
        print(f"  参数: {tc['function']['arguments']}")
# 结果：LLM 只能调 get_weather，即使用户在其他话题
```

### 四种模式决策树

```
用户消息来了，LLM 怎么决定？
         │
         ▼
  tool_choice = "none" ? ──Yes──→ 纯聊天，无视 tools
         │No
         ▼
  tool_choice = "required" ? ──Yes──→ 必须调用至少一个工具
         │No
         ▼
  tool_choice = 指定工具 ? ──Yes──→ 只能调用这个工具
         │No
         ▼
  tool_choice = "auto"（默认）
         │
         ▼
  LLM 分析：用户想调工具吗？ ──No──→ 直接回答
         │Yes
         ▼
  LLM 选哪个工具？→ 填充参数 → 返回 tool_calls
```

### 实际使用场景

| 模式 | 什么时候用 | 例子 |
|------|-----------|------|
| `auto` | **日常使用**，让 LLM 自己判断 | 通用 Agent |
| `required` | **批量处理**，需要 LLM 对每条数据都调用工具 | 翻译所有用户输入后处理 |
| `none` | **纯对话**，不想让 LLM 调用任何工具 | 客服闲聊模式 |
| `指定工具` | **路由模式**，强制 LLM 只用一个工具 | 先判断意图→路由到对应工具 |

---

## 七、完整版：可运行的 Function Calling 脚本

下面是一个可运行的 `function_calling.py`，整合了以上所有概念。

```python
#!/usr/bin/env python3
"""
function_calling.py — 手写 Function Calling 完整实现

不依赖 LangChain、Semantic Kernel 等框架。
纯 HTTP + JSON。

运行：
  export OPENAI_API_KEY="sk-xxx"
  python function_calling.py
"""

import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import httpx


# ====================================================================
# 第一部分：Tool Schema 定义
# ====================================================================

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的当前天气信息。支持国内和国外主要城市。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名，如 '北京'、'上海'、'Tokyo'、'New York'",
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "温度单位，默认 celsius（摄氏度）",
                    },
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "执行数学运算，支持四则运算(+-*/)、幂运算(**)、取整、三角函数等",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如 '2 + 3 * 4'、'2**10'、'math.sqrt(144)'",
                    },
                },
                "required": ["expression"],
            },
        },
    },
]


# ====================================================================
# 第二部分：工具实现
# ====================================================================

def get_weather_impl(city: str, unit: str = "celsius") -> str:
    """模拟天气查询"""
    weather_db = {
        "北京": {"temp": 22, "condition": "晴"},
        "上海": {"temp": 28, "condition": "多云"},
        "广州": {"temp": 30, "condition": "阵雨"},
        "深圳": {"temp": 29, "condition": "阴"},
        "Tokyo": {"temp": 18, "condition": "小雨"},
        "New York": {"temp": 15, "condition": "阴"},
        "London": {"temp": 12, "condition": "雾"},
        "Paris": {"temp": 20, "condition": "晴"},
    }
    data = weather_db.get(city, {"temp": 20, "condition": "未知"})
    symbol = "°C" if unit == "celsius" else "°F"
    return f"{city} 当前天气：{data['temp']}{symbol}，{data['condition']}"


def calculate_impl(expression: str) -> str:
    """安全计算数学表达式"""
    allowed = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "pow": pow, "math": math,
        "pi": math.pi, "e": math.e, "sqrt": math.sqrt,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
    }
    try:
        result = eval(expression, {"__builtins__": {}}, allowed)
        return f"{expression} = {result}"
    except Exception as e:
        return f"计算错误：{e}"


# ====================================================================
# 第三部分：Handler 注册表
# ====================================================================

TOOL_REGISTRY: dict[str, Callable] = {
    "get_weather": get_weather_impl,
    "calculate": calculate_impl,
}


def execute_tool_call(tool_call: dict) -> dict:
    """执行单个 tool_call，返回 tool 角色消息"""
    func_name = tool_call["function"]["name"]
    func_args = json.loads(tool_call["function"]["arguments"])
    call_id = tool_call["id"]

    func = TOOL_REGISTRY.get(func_name)
    if func is None:
        result = f"错误：未知工具 '{func_name}'"
    else:
        try:
            result = func(**func_args)
        except TypeError as e:
            result = f"参数错误：{e}"
        except Exception as e:
            result = f"执行异常：{e}"

    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": str(result),
    }


# ====================================================================
# 第四部分：LLM 调用封装
# ====================================================================

LLM_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")


def call_llm(
    messages: list[dict],
    tools: list | None = None,
    tool_choice: str | dict | None = "auto",
) -> dict:
    """通用 LLM 调用"""
    if not LLM_API_KEY:
        raise ValueError("请设置 OPENAI_API_KEY 环境变量")

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "tool_choice": tool_choice,
    }
    if tools:
        body["tools"] = tools

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


# ====================================================================
# 第五部分：Agent 循环
# ====================================================================

def agent_loop(
    user_input: str,
    system_prompt: str | None = None,
    max_turns: int = 5,
    tool_choice: str | dict | None = "auto",
) -> list[dict]:
    """
    完整的 Agent 循环。
    
    Args:
        user_input: 用户输入
        system_prompt: 可选系统提示词
        max_turns: 最大工具调用轮数
        tool_choice: tool_choice 模式
    
    Returns:
        完整的消息历史
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_input})

    print(f"\n{'='*60}")
    print(f"用户: {user_input}")
    print(f"Tool Choice: {tool_choice}")
    print(f"{'='*60}")

    turn = 0
    while turn < max_turns:
        turn += 1
        print(f"\n--- Round {turn} ---")

        response = call_llm(messages, tools=TOOL_SCHEMAS, tool_choice=tool_choice)
        choice = response["choices"][0]
        assistant_msg = choice["message"]
        finish_reason = choice["finish_reason"]

        if finish_reason == "tool_calls":
            tool_calls = assistant_msg.get("tool_calls", [])
            print(f"→ LLM 调用了 {len(tool_calls)} 个工具")

            # 加入 assistant 消息
            messages.append(assistant_msg)

            # 并发执行工具
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {
                    executor.submit(execute_tool_call, tc): tc
                    for tc in tool_calls
                }
                tool_results = [None] * len(tool_calls)
                for future in as_completed(futures):
                    tc = futures[future]
                    idx = tool_calls.index(tc)
                    tool_results[idx] = future.result()

            for tr in tool_results:
                print(f"  🛠  {tr['content']}")
            messages.extend(tool_results)

            # 如果是 required 模式、切回 auto 防止死循环
            if tool_choice == "required":
                tool_choice = "auto"

        else:
            # finish_reason 为 "stop" 或 "length"
            content = assistant_msg.get("content", "")
            print(f"→ LLM 回答: {content}")
            messages.append(assistant_msg)
            break

    else:
        print(f"\n⚠️  达到最大轮数 ({max_turns})，强制停止")

    return messages


# ====================================================================
# 第六部分：主入口 / 测试
# ====================================================================

def demo_auto():
    """tool_choice='auto' 演示"""
    print("\n\n>>> DEMO: tool_choice='auto' - 需要工具的场景")
    agent_loop("东京今天多少度？", tool_choice="auto")


def demo_required():
    """tool_choice='required' 演示"""
    print("\n\n>>> DEMO: tool_choice='required' - 强制调用")
    agent_loop("今天心情不错", tool_choice="required")


def demo_none():
    """tool_choice='none' 演示"""
    print("\n\n>>> DEMO: tool_choice='none' - 禁止调用工具")
    agent_loop("东京今天多少度？帮我算 2^10", tool_choice="none")


def demo_specific():
    """指定工具演示"""
    print("\n\n>>> DEMO: tool_choice=指定工具(get_weather)")
    agent_loop(
        "帮我算 100 * 3.14，顺便看看北京天气",
        tool_choice={"type": "function", "function": {"name": "get_weather"}},
    )


def demo_multi_tool():
    """多工具组合调用演示"""
    print("\n\n>>> DEMO: 多工具组合调用")
    agent_loop("帮我查查北京和东京的天气，再算一下 2^16 等于多少")


if __name__ == "__main__":
    if not LLM_API_KEY:
        print("❌ 请设置 OPENAI_API_KEY 环境变量")
        print("   export OPENAI_API_KEY='sk-your-key'")
        print("\n⚠️  模拟模式：演示数据结构，不实际调 API")
        
        # 模拟模式：展示数据结构
        print("\n=== 模拟：LLM 返回的 tool_calls 结构 ===")
        mock_tool_calls = [
            {
                "id": "call_weather_001",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"city": "Tokyo", "unit": "celsius"}',
                },
            },
            {
                "id": "call_calc_001",
                "type": "function",
                "function": {
                    "name": "calculate",
                    "arguments": '{"expression": "2**10"}',
                },
            },
        ]
        print(json.dumps(mock_tool_calls, indent=2, ensure_ascii=False))
        
        print("\n=== 执行结果 ===")
        for tc in mock_tool_calls:
            result = execute_tool_call(tc)
            print(f"  {tc['function']['name']}: {result['content']}")
        
        print("\n=== tool_choice 四种模式对比 ===")
        print(f"{'模式':<20} {'值':<30} {'效果'}")
        print("-" * 70)
        print(f"{'auto':<20} {'None (默认)':<30} {'LLM 自主决定'}")
        print(f"{'required':<20} {'\"required\"':<30} {'强制调用工具'}")
        print(f"{'none':<20} {'\"none\"':<30} {'禁止调用工具'}")
        print(f"{'指定工具':<20} {'{\"type\":\"function\",...}':<30} {'只能调指定工具'}")
        
        sys.exit(0)

    # 正常模式：调 API
    demo_auto()
    demo_multi_tool()
```

---

## 八、踩坑记录 🕳️

> 这些都是真实踩过的坑，不是搬运文档。

### 坑 1：`arguments` 是字符串，不是字典

```python
# ❌ 错误
args = tool_call["function"]["arguments"]
city = args["city"]  # TypeError: string indices must be integers

# ✅ 正确
args = json.loads(tool_call["function"]["arguments"])
city = args["city"]  # ✅
```

LLM API 返回的 `arguments` 是 **JSON 字符串**，不是已经解析好的对象。不做 `json.loads` 直接取 key 必报错。

### 坑 2：忘记把 assistant 消息加入历史

```python
# ❌ 错误：messages 只有 [user, tool_result_1, tool_result_2]
messages = [user_msg]
for tc in tool_calls:
    messages.append(execute_tool_call(tc))
# LLM 收到后懵了：谁调的这些工具？

# ✅ 正确：必须包含 assistant 消息
messages = [user_msg]
assistant_msg = {
    "role": "assistant",
    "content": None,
    "tool_calls": tool_calls,
}
messages.append(assistant_msg)
for tc in tool_calls:
    messages.append(execute_tool_call(tc))
```

### 坑 3：`tool_call_id` 不匹配

```python
# ❌ 错误：tool_call_id 拼错了或没传
{"role": "tool", "content": "18°C"}
# API 返回错误：tool_call_ids 必须与之前的 tool_calls 匹配

# ✅ 正确：tool_call_id 必须等于对应的 tool_call id
{"role": "tool", "tool_call_id": "call_weather_001", "content": "18°C"}
```

每个 `tool` 消息必须通过 `tool_call_id` 关联到上一条 assistant 消息中的某个 `tool_call`。不匹配会报错。

### 坑 4：OpenAI 要求 tool 消息必须在 assistant(tool_calls) 之后

消息顺序必须严格：
```
user → assistant(tool_calls) → tool(1) → tool(2) → ... → assistant(回答)
```

不能交叉：
```python
# ❌ 错误顺序
[user, tool_result_1, assistant(with tool_calls), tool_result_2]
# API 422 错误

# ✅ 正确顺序
[user, assistant(with tool_calls), tool_result_1, tool_result_2]
```

### 坑 5：Tool 描述不够详细 → LLM 永远不调用

```python
# ❌ 太模糊
"description": "获取天气"

# ✅ 足够详细
"description": "获取指定城市的当前天气信息，支持国内和国外主要城市。调用此工具时需要提供城市名称。"
```

LLM 通过 `description` 判断是否用这个工具。写得太短，LLM 在复杂场景下会直接回答而不调用工具。

### 坑 6：`max_turns` 不加 = 无限烧钱

```python
# ❌ 危险：没有限制
while True:
    response = call_llm(messages, tools=TOOLS)
    # LLM 可能无限循环调用工具 → API 账单爆炸

# ✅ 安全：加 max_turns 限制
MAX_TURNS = 5
for turn in range(MAX_TURNS):
    response = call_llm(messages, tools=TOOLS)
```

不加限制的 Agent 循环可能进入死循环（例如 LLM 调用了工具，但工具返回的结果又触发它继续调同一个工具），每个循环都要花 API 费用。

### 坑 7：`required` 模式可能导致 LLM 编造参数

当 `tool_choice="required"` 时，LLM **必须**调用工具。如果用户输入和所有工具都不相关，LLM 可能会编造参数：

```python
# 用户说"你好"，LLM 必须调工具
# → LLM 自己编造：get_weather(city="Paris")
# 不是 bug，是设计——你要求的
```

解决方法：`required` 模式只在**确定需要调用工具的场景**使用，且第一轮后切回 `auto`。

---

## 九、副线笔记

### Function Calling 不是函数调用

中文翻译「函数调用」容易让人误解。实际上：

- **Function Calling = LLM 决定调用哪个函数**（决策阶段）
- **函数执行 = 我们自己在本地运行代码**（执行阶段）
- LLM 并不「运行」代码，它只是**声明**「我要用这个工具，参数是这些」

所以更准确的理解是：**Tool Declaration（工具声明）** 或 **Tool Invocation Decision（工具调用决策）**。

### 为什么 Anthropic 的 Tool Use 不一样？

Anthropic 的 API 把工具叫做 `tools` 而不是 `functions`，但核心逻辑一致：

| 概念 | OpenAI | Anthropic |
|------|--------|-----------|
| 工具定义 | `tools` | `tools` |
| 调用标识 | `tool_calls`（在 assistant 里） | `content` 里 type=non-tool_use 的块 |
| 结果返回 | `role: tool` | `role: user` 里加 tool_result content block |
| finish_reason | `tool_calls` | `stop_reason: end_turn` + content 里有 tool_use 块 |

Anthropic 的设计实际上更干净——它把 tool_use 当作 content block 的一种类型，和文字并列。但 OpenAI 格式更流行。

### Tool Schema 是 Agent 的 API 网关

如果你把 Agent 看作微服务：

```
用户请求 → [Agent (API 网关)] → 路由判断 → [工具 1: 天气服务]
                                            → [工具 2: 计算服务]
                                            → [工具 3: 数据库查询]
```

Tool Schema 就是**网关的路由表**。每个工具是一个微服务端点，description 是路由规则，parameters 是请求参数定义。

### 安全性思考

`eval()` 在例子里只是为了演示方便。生产环境请用：

1. **`numexpr`**：专门的安全数学表达式求值库，`pip install numexpr`
2. **AST 解析**：先用 `ast.parse` 检查语法树，只允许特定节点类型
3. **沙箱执行**：在隔离容器或子进程中运行不可信代码

```python
# 更安全的计算方案：numexpr
import numexpr as ne

def safe_calculate(expression: str) -> str:
    try:
        result = ne.evaluate(expression.replace("^", "**"))
        return f"{expression} = {result}"
    except Exception as e:
        return f"计算错误：{e}"
```

### 2026 年的趋势

- **OpenAI Structured Outputs** 可以直接让 tool_calls 的 arguments 严格按 schema 输出，不会再出现参数类型错误
- **Anthropic Tool Use (Beta)** 支持 tool_use + 文字混合输出，比纯并行调用更灵活
- **国产模型**（DeepSeek V4、Qwen3、GLM-5）都兼容 OpenAI 的 tool_calls 格式，代码基本不用改
- **MCP (Model Context Protocol)** 正在标准化工具发现机制，但底层的 tool_calls 格式不会变——学会了今天的内容，未来也用得上

---

> **Day 02 总结：** 你手动实现了一次完整的 Function Calling——从定义 Tool Schema，到解析 LLM 返回的 tool_calls，到用 Handler 模式执行函数，再到把结果发回 LLM 获取最终回答。这些代码就是所有 Agent 框架（LangChain、Semantic Kernel、AutoGen）底层在做的事。下周的 Agent Loop 就是把这个过程循环起来。
