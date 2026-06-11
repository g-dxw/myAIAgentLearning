# Day 03 — Agent Loop 框架：把手动调用变成自动循环

## 学习目标

把 Day 02 的「手动一次 Function Calling」变成一个**自动循环**——一个真正的 Agent Loop。这是本周最核心的一天。

学完今天你能回答：
- Agent Loop 的 while True 究竟在循环什么？
- messages 为什么不断增长，会有什么问题？
- LLM 陷入「工具死循环」怎么检测和处理？
- 生产级的 Agent 循环和 Demo 有什么区别？

---

## 一、Agent Loop 的定义

### 1.1 从「手动」到「自动」

Day 02 我们手动执行了一次 Function Calling：

```
用户输入 → 调 LLM → 有 tool_calls → 执行工具 → 调 LLM → 有回答 → 结束
```

但是步骤是我们在 `main()` 里**手写死的**。如果：

- LLM 第一次调了工具，第二次还想再调一个工具呢？
- LLM 需要搜索 → 根据搜索结果再算一些东西 → 再整合回答呢？
- 工具执行出错，LLM 想要重试呢？

**手动模式只能处理一轮 tool call，无法应对真正的 Agent 场景。**

### 1.2 Agent Loop 的 while True

```python
# Agent Loop 的核心模式
def agent_loop(user_input):
    messages = [system_prompt, {"role": "user", "content": user_input}]

    while True:
        # 1. 调用 LLM（带工具定义）
        response = call_llm(messages, tools)

        # 2. 解析 LLM 的响应
        if response 有 tool_calls:
            for each tool_call:
                result = execute_tool(tool_call)
                messages.append({"role": "tool", ...})  # 追加结果
            # 🔄 继续循环（再次调 LLM）
        elif response 有文本回答:
            return response.text  # ✅ 结束
        else:
            # 安全处理：LLM 返回了意料之外的格式
            handle_unexpected()
```

```
                ┌─────────────────────────────────────────┐
                │           Agent Loop                     │
                │                                          │
用户输入 ──────►│  ┌─────┐    ┌───────┐    ┌────────┐    │──────► 最终回答
                │  │ LLM  │───►│ 解析   │───►│ 有回答? │ 是 │
                │  └─────┘    └───────┘    └────────┘    │
                │     │           │             │         │
                │     │           │ 有 tool     │ 否      │
                │     │           │ _calls      │         │
                │     ▼           ▼             │         │
                │  ┌─────────────────────┐      │         │
                │  │ 执行工具 → 结果追加  │◄─────┘         │
                │  │ 到 messages         │                │
                │  └─────────────────────┘                │
                └─────────────────────────────────────────┘
```

**Agent = LLM + Tools + Loop**

没有 Loop 的 LLM 调用只是一个聊天机器人。有了 Loop，它才成为 Agent。

### 1.3 每一轮发生了什么

| 轮次 | LLM 输入（messages） | LLM 输出 | 我们做什么 |
|------|---------------------|----------|-----------|
| Turn 1 | system + user | tool_calls(get_weather) | 执行天气查询，结果追加 |
| Turn 2 | system + user + tool_call + tool_result | tool_calls(calculate) | 执行计算，结果追加 |
| Turn 3 | system + user + ... + tool_result2 | text("北京天气...") | ✅ 返回用户 |

每一轮的 messages 都比上一轮**更长**，因为：
- 增加了一条 assistant(tool_calls) 消息
- 增加了 N 条 tool(结果) 消息
- 下一轮 LLM 会「看到」上一轮的所有结果

---

## 二、构建 ToolAgent 类

### 2.1 完整的 ToolAgent

```python
"""day03/agent_loop.py — Agent 循环框架"""
import json
import os
import time
import httpx
from datetime import datetime
from typing import Callable, Any


class ToolAgent:
    """
    通用的 Agent 循环框架。

    设计原则：
    - LLM 只负责「思考」（决定调什么工具、生成回答）
    - Agent 只负责「行动」（执行函数、管理循环）
    - messages 是 Agent 和 LLM 之间的「共享记事本」
    - 每次循环 = 1 次 LLM 调用 + 0~N 次工具执行
    """

    def __init__(
        self,
        system_prompt: str = "你是一个有用的 AI 助手。",
        tools: list[dict] | None = None,
        tool_handlers: dict[str, Callable] | None = None,
        model: str = "gpt-4o",
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        max_turns: int = 10,
        verbose: bool = True,
    ):
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.tool_handlers = tool_handlers or {}
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = base_url
        self.max_turns = max_turns
        self.verbose = verbose

        # 统计信息
        self.turns_used = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        # 工具循环检测
        self._last_tool_calls: list[tuple[str, str]] | None = None
        self._loop_count = 0

    # ──────────────────────────────────────────
    # LLM 调用
    # ──────────────────────────────────────────

    def call_llm(self, messages: list[dict]) -> dict:
        """调用 LLM API（支持 tool calling）"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "messages": messages,
            "tools": self.tools,
            "tool_choice": "auto",
        }
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    # ──────────────────────────────────────────
    # 工具执行
    # ──────────────────────────────────────────

    def _execute_tool_calls(
        self, tool_calls: list[dict], messages: list[dict]
    ) -> list[dict]:
        """执行一组 tool_calls，返回要追加的 tool 消息列表"""
        tool_messages = []

        for tc in tool_calls:
            func_name = tc["function"]["name"]
            try:
                func_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError as e:
                # LLM 偶尔会输出非法 JSON
                result = {"error": f"参数解析失败: {e}"}
                result_str = json.dumps(result, ensure_ascii=False)
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_str,
                })
                continue

            if self.verbose:
                print(f"  🔧 {func_name}({func_args})")

            handler = self.tool_handlers.get(func_name)
            if handler is None:
                result_str = json.dumps(
                    {"error": f"未知工具: {func_name}"}, ensure_ascii=False
                )
            else:
                try:
                    start = time.time()
                    result = handler(**func_args)
                    elapsed = time.time() - start
                    result_str = json.dumps(result, ensure_ascii=False)
                    if self.verbose:
                        print(f"     ✓ 完成 ({elapsed:.2f}s): {result_str[:80]}")
                except Exception as e:
                    result_str = json.dumps(
                        {"error": f"工具执行异常: {type(e).__name__}: {e}"},
                        ensure_ascii=False,
                    )
                    if self.verbose:
                        print(f"     ✗ 错误: {e}")

            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_str,
            })

        return tool_messages

    def _detect_tool_loop(
        self, current_tool_calls: list[dict]
    ) -> bool:
        """
        检测 LLM 是否陷入了「工具死循环」——连续两次请求相同的工具调用。
        返回 True 表示检测到循环。
        """
        current_normalized = sorted([
            (tc["function"]["name"], tc["function"]["arguments"])
            for tc in current_tool_calls
        ])

        if self._last_tool_calls == current_normalized:
            self._loop_count += 1
            if self._loop_count >= 2:  # 连续相同的工具调用 >= 2 次
                if self.verbose:
                    print("  ⚠️ 检测到工具循环！连续相同的工具调用。")
                return True
        else:
            # 重置检测
            self._last_tool_calls = current_normalized
            self._loop_count = 0

        return False

    # ──────────────────────────────────────────
    # 主循环
    # ──────────────────────────────────────────

    def run(self, user_input: str) -> str:
        """
        运行 Agent 主循环。

        参数:
            user_input: 用户输入文本

        返回:
            Agent 的最终回答文本
        """
        # 初始化消息列表
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]

        self.turns_used = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._last_tool_calls = None
        self._loop_count = 0

        if self.verbose:
            print(f"\n{'='*50}")
            print(f"🤖 Agent 启动 | 模型: {self.model} | max_turns: {self.max_turns}")
            print(f"{'='*50}")
            print(f"📤 用户: {user_input}")

        for turn in range(self.max_turns):
            self.turns_used += 1

            if self.verbose:
                print(f"\n{'─'*40}")
                print(f"🔄 Turn {turn + 1}/{self.max_turns}")
                print(f"   messages 长度: {len(messages)} 条")
                print(f"{'─'*40}")

            # Step 1: 调 LLM
            try:
                response = self.call_llm(messages)
            except httpx.HTTPStatusError as e:
                error_msg = f"API 错误 (HTTP {e.response.status_code}): {e.response.text[:200]}"
                if self.verbose:
                    print(f"  ❌ {error_msg}")
                return f"⚠️ Agent 出错: {error_msg}"
            except httpx.TimeoutException:
                if self.verbose:
                    print("  ❌ API 请求超时")
                return "⚠️ Agent 出错: API 请求超时，请稍后重试。"

            assistant_msg = response["choices"][0]["message"]

            # 统计 token
            if "usage" in response:
                self.total_input_tokens += response["usage"].get("prompt_tokens", 0)
                self.total_output_tokens += response["usage"].get("completion_tokens", 0)

            # Step 2: 检查是否有 tool_calls
            tool_calls = assistant_msg.get("tool_calls")

            if not tool_calls:
                # 没有工具调用 → LLM 用文本回答了 → 结束
                final_text = assistant_msg.get("content") or ""
                if self.verbose:
                    print(f"\n📥 Agent 回答 ({len(final_text)} 字符):")
                    print(f"   {final_text[:300]}")
                return final_text

            # 有工具调用
            # 先做循环检测
            if self._detect_tool_loop(tool_calls):
                forced_msg = (
                    "检测到工具循环。你连续请求了相同的工具调用，"
                    "但没有取得新进展。请基于已有信息直接回答用户的问题，"
                    "不要再调用工具。"
                )
                messages.append({
                    "role": "user",
                    "content": forced_msg,
                })
                # 不追加当前 tool_calls，而是发一条干预消息
                continue

            # 正常处理：追加 assistant 消息
            messages.append(assistant_msg)

            # 执行工具
            if self.verbose:
                print(f"  → 执行 {len(tool_calls)} 个工具调用")

            tool_messages = self._execute_tool_calls(tool_calls, messages)
            messages.extend(tool_messages)

        # 达到 max_turns
        summary = (
            f"⚠️ 达到最大轮数限制 ({self.max_turns})，Agent 被迫停止。\n"
            f"已执行 {self.turns_used} 轮，消耗 "
            f"约 {self.total_input_tokens + self.total_output_tokens} tokens。"
        )
        if self.verbose:
            print(f"\n{summary}")
        return summary

    # ──────────────────────────────────────────
    # 统计信息
    # ──────────────────────────────────────────

    def get_stats(self) -> dict:
        """获取本轮运行的统计数据"""
        return {
            "turns_used": self.turns_used,
            "max_turns": self.max_turns,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
        }

    def print_stats(self):
        """打印统计信息"""
        stats = self.get_stats()
        print(f"\n{'='*50}")
        print("📊 Agent 运行统计")
        print(f"{'='*50}")
        print(f"  轮数:      {stats['turns_used']} / {stats['max_turns']}")
        print(f"  输入 Token: {stats['total_input_tokens']:,}")
        print(f"  输出 Token: {stats['total_output_tokens']:,}")
        print(f"  总计 Token: {stats['total_tokens']:,}")
        print(f"{'='*50}")


# =====================================================
# 工具定义：Handler 注册模式
# =====================================================

def get_weather_handler(city: str) -> dict:
    """获取指定城市的实时天气（模拟）"""
    # 实际项目中可以调 OpenWeatherMap / wttr.in
    return {
        "city": city,
        "temperature": 28,
        "condition": "晴",
        "humidity": 45,
        "wind": "3级",
    }


def calculate_handler(expression: str) -> dict:
    """安全计算器"""
    # 只允许数字和基础运算符
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in expression):
        return {"error": "表达式包含非法字符，只允许数字和 +-*/"}

    # ⚠️ 教学演示用 eval()
    # 生产环境请用 numexpr 或 ast.literal_eval！
    try:
        result = eval(expression)
        return {"expression": expression, "result": result}
    except Exception as e:
        return {"error": f"计算错误: {e}"}


def get_time_handler() -> dict:
    """获取当前时间"""
    now = datetime.now()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return {
        "datetime": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekdays[now.weekday()],
    }


def search_knowledge_handler(query: str) -> dict:
    """模拟知识检索"""
    # 模拟一些内置知识
    knowledge_base = {
        "python": "Python 是一种高级编程语言，广泛用于 AI、数据科学和 Web 开发。",
        "agent": "AI Agent 是能自主感知环境、做出决策并采取行动的系统。",
        "function calling": "Function Calling 是 LLM API 的一项能力，让模型能输出结构化的工具调用请求。",
        "北京": "北京是中国的首都，人口约 2189 万。",
        "上海": "上海是中国最大的城市之一，人口约 2487 万。",
    }

    # 模糊匹配
    for key, value in knowledge_base.items():
        if key in query.lower():
            return {"query": query, "answer": value, "source": "内置知识库"}

    return {"query": query, "answer": f"抱歉，我没有关于「{query}」的知识。"}


# =====================================================
# Tool Schema（OpenAI 格式）
# =====================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的实时天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名，如 北京、上海、广州",
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
            "description": "执行数学计算，支持 + - * / 和括号",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如 '25 * 48 + 100'",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前的日期和时间",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "搜索内置知识库，获取关于某个主题的基本信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如 'Python'、'Agent'",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

# Handler 注册表
HANDLERS = {
    "get_weather": get_weather_handler,
    "calculate": calculate_handler,
    "get_current_time": get_time_handler,
    "search_knowledge": search_knowledge_handler,
}


# =====================================================
# 使用示例
# =====================================================

if __name__ == "__main__":
    agent = ToolAgent(
        system_prompt="你是一个有用的 AI 助手。你可以查询天气、执行计算、查询时间，以及搜索知识库。请用中文回答。",
        tools=TOOLS,
        tool_handlers=HANDLERS,
        max_turns=10,
        verbose=True,
    )

    # === 测试 1：多工具组合 ===
    result = agent.run("北京今天天气怎么样？顺便帮我算 1024 * 768 等于多少？")
    agent.print_stats()

    # === 测试 2：需要多轮推理 ===
    # result = agent.run("调查一下 Python 和 Function Calling 的关系，然后告诉我现在的时间")
    # agent.print_stats()
```

### 2.2 类的核心设计要素

```
ToolAgent
├── __init__()      → 配置：模型、工具、handler、限制
├── call_llm()      → 封装 LLM API 调用
├── run()           → 主循环 while+for（见上）
├── _execute_tool_calls()  → 执行一组工具调用
├── _detect_tool_loop()    → 工具循环检测
├── get_stats()     → 统计信息
└── print_stats()   → 打印统计
```

**设计原则总结：**

| 原则 | 说明 |
|------|------|
| **单一职责** | LLM 只管「思考」，Agent 只管「行动」 |
| **消息驱动** | messages 是唯一的状态载体，append-only |
| **可观测性** | verbose 模式打印每一步，便于调试 |
| **优雅降级** | 出错时返回错误信息，不抛异常崩掉整个循环 |

---

## 三、max_turns 和停止条件

### 3.1 为什么需要 max_turns

Agent 循环如果没有上限，可能永远跑下去：

| 情况 | 说明 |
|------|------|
| LLM 陷入循环 | 反复调工具，永远不给最终回答 |
| 任务太复杂 | 需要 50 轮才能完成，但你只打算花 10 轮的预算 |
| 工具执行异常慢 | 某个工具卡住了，后续轮次无限等待 |
| 意外 bug | 代码有 bug，导致 LLM 的 tool_calls 永远在执行 |

**max_turns 是安全网**，不是正常流程的一部分。

### 3.2 停止条件的优先级

```python
# Agent 循环的停止逻辑（优先级从高到低）
def should_stop(turn, max_turns, assistant_msg, tool_history):
    # 1. 达到最大轮数 → 强制停止
    if turn >= max_turns:
        return True, "max_turns_reached"

    # 2. LLM 返回了文本回答 → 正常结束
    if assistant_msg.get("content") and not assistant_msg.get("tool_calls"):
        return True, "normal_completion"

    # 3. 检测到工具循环 → 强制停止
    if detect_tool_loop(tool_history):
        return True, "tool_loop_detected"

    # 4. Tool calls 长度异常 → 安全停止
    if len(assistant_msg.get("tool_calls", [])) > 20:
        return True, "too_many_parallel_calls"

    # 5. 继续循环
    return False, "continue"
```

### 3.3 max_turns 的合理值

| 场景 | 建议值 | 说明 |
|------|--------|------|
| 简单问答 | 1~3 | 很少需要多轮工具调用 |
| 组合任务 | 5~10 | 需要查信息 + 计算 + 整合 |
| 复杂推理 | 10~25 | 多步搜索、分析、验证 |
| 代码生成 | 15~30 | 需要生成 → 测试 → 修复循环 |
| 无限制 | 50~100 | 高风险，必须有循环检测 |

**实战建议：** 从 `max_turns=5` 开始，调大直到覆盖你的用例。不要一开始就设 100。

---

## 四、messages 不断增长的机制和问题

### 4.1 为什么 messages 会增长

每一轮循环，messages 增加 1 + N 条：

```
messages = [
    system_prompt,                     # 不变
    user_input,                        # 不变
    # ── Turn 1 ──
    assistant(tool_calls=[...]),       # +1
    tool(get_weather_result),          # +1
    tool(calculate_result),            # +1（如果两个并行工具）
    # ── Turn 2 ──
    assistant(tool_calls=[...]),       # +1
    tool(search_knowledge_result),     # +1
    # ── Turn 3 ──
    assistant(content="..."),          # +1（最终回答）
]
```

**messages = Agent 的「短期记忆」**。越长，模型能「记住」的信息越多。但也越贵、越慢。

### 4.2 messages 增长的代价

| 代价 | 说明 | 数字 |
|------|------|------|
| **Token 消耗** | 每轮都发全部历史给 API | 10 轮约 8K~20K tokens |
| **API 延迟** | 输入越长，首 token 延迟越高 | 10K tokens 约慢 0.5~1s |
| **注意力稀释** | 模型在长上下文中「迷失」 | 研究发现 50K+ tokens 后中间内容被忽略 |
| **成本** | 按 token 计费 | 1 轮 $0.001 → 100 轮 $0.1+ |

```python
# 测算 messages 增长
def estimate_messages_growth(num_turns, tools_per_turn=2):
    """估测 N 轮后的 messages 条数和 token 数"""
    system_token = 500
    user_token = 100
    per_turn_assistant = 150  # tool_calls 本身
    per_tool_result = 200     # 工具结果
    final_answer = 500

    messages_count = 2  # system + user
    token_count = system_token + user_token

    for turn in range(num_turns):
        messages_count += 1  # assistant tool_calls
        token_count += per_turn_assistant
        messages_count += tools_per_turn  # tool results
        token_count += per_tool_result * tools_per_turn

    # 最后加上最终回答
    messages_count += 1
    token_count += final_answer

    return {
        "turn": num_turns,
        "total_messages": messages_count,
        "estimated_tokens": token_count,
        "cost_usd": token_count * 0.000002,  # 假设 $2/M tokens
    }

# print(estimate_messages_growth(10))
# → {'turn': 10, 'total_messages': 33, 'estimated_tokens': 4650, 'cost_usd': 0.0093}
```

### 4.3 messages 增长的三个问题

**问题 1：Context Window 溢出**

```
200K Context Window
┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
│ S  │ U  │ T1 │ R1 │ T2 │ R2 │ T3 │ R3 │ T4 │ R4 │← 还在窗口内
└────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘

... 50 轮后
┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
│ S  │ ❌ 被截断 ❌ ... │ T48│ R48│ T49│ R49│ T50│ R50 │
└────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘
     ↑ 最早的消息丢了，LLM 不记得 system prompt！
```

**问题 2：注意力稀释（Lost in the Middle）**

研究发现，LLM 对 messages 中间部分的信息关注度最低：

```
关注度:
高 ─── system_prompt
中 ─── 最近几轮的消息  ← 模型能「记住」
低 ─── 中间轮次的消息  ← 模型「看到了但没注意」
高 ─── 当前轮次的输入  ← 模型最关注
```

这意味着即使 messages 没有溢出，**中间轮次的关键信息也可能被模型忽略**。

**问题 3：输入 token 成本线性增长**

```
10 轮消耗 tokens = 5K → 成本 = $0.01
20 轮消耗 tokens = 10K → 成本 = $0.02
50 轮消耗 tokens = 25K → 成本 = $0.05
```

每次 API 调用都要发送**全部历史**，这是 Agent 模式最主要的花费来源。

### 4.4 生产环境的解决方案（预告）

Week 02 学的 Token 预算管理在这里派上用场：

```
方案 1：滑动窗口
   只保留最近 N 轮（如最近 10 轮，丢弃最早的消息）
   优点：简单
   缺点：可能丢失关键上下文

方案 2：摘要压缩
   把早期 N 轮对话压缩成一段摘要文本
   "用户之前问了北京天气，得到结果 28°C 晴"
   优点：保留关键信息，节省 token
   缺点：压缩本身也需要 LLM 调用

方案 3：Prompt Caching
   API 提供缓存功能（Anthropic Prompt Caching）
   重复的 system prompt 和早期消息不走计费
   优点：省钱、省时间
   缺点：不是所有 API 都支持
```

**本周我们只聚焦「循环框架」本身，不做压缩优化。** 先跑通，再优化。

---

## 五、工具 Handler 注册模式

### 5.1 什么是注册模式

就是**把工具名和对应的 Python 函数映射起来**：

```python
# 注册表 = {工具名: 函数引用}
HANDLERS = {
    "get_weather": get_weather_handler,     # 函数名不带括号！
    "calculate": calculate_handler,
    "search_web": search_web_handler,
}
```

当 LLM 说「我要调 get_weather」时，Agent 查到注册表 → 拿到 `get_weather_handler` 函数 → 调用它。

### 5.2 为什么不直接写 if-else

```python
# ❌ 不推荐：硬编码 if-else
def execute_tool(name, args):
    if name == "get_weather":
        return get_weather_handler(**args)
    elif name == "calculate":
        return calculate_handler(**args)
    elif name == "search_web":
        return search_web_handler(**args)
    # ... 加一个新工具就要加一个 elif ...
    else:
        return {"error": f"未知工具: {name}"}
```

```python
# ✅ 推荐：注册模式
def execute_tool(name, args, handlers):
    handler = handlers.get(name)
    if handler is None:
        return {"error": f"未知工具: {name}"}
    return handler(**args)
```

**注册模式的好处：**

| 特性 | if-else | 注册表 |
|------|---------|--------|
| 加新工具 | 改代码 + 加 elif | 加 dict 项 |
| 动态注册 | 不可能 | 运行时 `handlers["new"] = new_func` |
| 插件化 | 不可能 | 外部模块自动注册 |
| 复杂度 | O(n) 分支 | O(1) 查找 |
| 单元测试 | 必须测整个函数 | 可单独测 handler |

### 5.3 高级注册模式：装饰器注册

如果你想更优雅一点，可以用装饰器：

```python
# 装饰器注册模式（进阶，可选）
TOOL_REGISTRY: dict[str, dict] = {}

def tool(name: str = "", description: str = ""):
    """装饰器：把函数注册为工具"""
    def decorator(func):
        tool_name = name or func.__name__
        TOOL_REGISTRY[tool_name] = {
            "handler": func,
            "description": description or func.__doc__ or "",
        }
        return func
    return decorator

# 使用
@tool(description="获取天气")
def get_weather(city: str) -> dict:
    """获取指定城市的天气"""
    return {"city": city, "temperature": 28}

@tool(description="执行计算")
def calculate(expression: str) -> dict:
    return {"result": eval(expression)}

# 自动生成 schema
def generate_tool_schema(name: str) -> dict:
    """从注册的工具生成 OpenAI 格式的 tool schema"""
    # 需要结合 inspect.signature 获取参数信息
    raise NotImplementedError("留给你的练习")

# 使用注册表
# handlers = {name: info["handler"] for name, info in TOOL_REGISTRY.items()}
```

> **选哪种？** 初学用 dict 注册表就够了。装饰器模式更适合框架作者或需要自动生成 schema 的场景。

---

## 六、错误处理

### 6.1 错误分类和处理策略

```
Agent 执行过程
│
├─ 🔴 第一阶段：调用 LLM
│   ├─ API key 错误 → HTTP 401 → 不重试，直接报错
│   ├─ 模型不存在  → HTTP 404 → 不重试，检查配置
│   ├─ 请求超时    → Timeout  → 可重试 1-2 次
│   ├─ 频率限制    → HTTP 429 → 等待后重试（retry-after）
│   └─ 服务器错误  → HTTP 500 → 可重试 1 次
│
├─ 🟡 第二阶段：解析工具调用
│   ├─ JSON 解析失败 → 告诉 LLM 格式错误，让它重发
│   ├─ 参数缺字段    → 同上
│   └─ 类型不匹配    → 同上
│
├─ 🟠 第三阶段：执行工具
│   ├─ 函数抛异常    → 把错误信息返回给 LLM，让它自行决策
│   ├─ 工具超时      → 同上
│   └─ 工具返回异常数据 → 同上
│
└─ 🔵 第四阶段：工具循环检测
    ├─ 相同工具连续调用 → 干预 LLM，迫使用已有结果回答
    └─ 超过 max_turns  → 强制结束
```

### 6.2 关键错误处理原则

**原则 1：工具执行错误 ≠ Agent 崩溃**

```python
# ❌ 错误做法：工具异常直接抛出去
try:
    result = handler(**args)
except Exception as e:
    raise  # 整个 Agent 炸了！用户什么都没看到

# ✅ 正确做法：把错误作为 tool 结果返回给 LLM
try:
    result = handler(**args)
except Exception as e:
    result = {"error": f"{type(e).__name__}: {str(e)}"}
# 让 LLM 自己决定：重试 / 换方法 / 告诉用户
```

为什么？因为 LLM 比你的 Agent 更「聪明」——它可能知道怎么处理这个错误。

```python
# 实际效果：
# 工具返回错误 → 发给 LLM →
# LLM: "看来 get_weather('火星') 失败了。火星没有天气数据。
#        让我检查一下支持的参数，或者告诉用户只支持地球城市。"
```

**原则 2：LLM 格式错误 = 优雅降级**

```python
# LLM 偶尔会输出不是有效 JSON 的 tool arguments
tc["function"]["arguments"]  # 可能是 '{'city':'北京'}' ← 单引号，非法 JSON！

# 处理方式：捕获 JSONDecodeError，发消息让 LLM 修正
try:
    func_args = json.loads(tc["function"]["arguments"])
except json.JSONDecodeError:
    tool_messages.append({
        "role": "tool",
        "tool_call_id": tc["id"],
        "content": json.dumps({
            "error": "参数不是合法 JSON，请重新发送，确保使用双引号"
        }),
    })
    continue  # 跳过当前工具，让 LLM 重试
```

### 6.3 LLM 陷入工具循环的检测

**什么是工具循环？**

```
Turn 1: LLM → get_weather("北京") → 结果: 28°C
Turn 2: LLM → get_weather("北京") → 结果: 28°C  ← 跟上次一样！
Turn 3: LLM → get_weather("北京") → 结果: 28°C  ← 还在循环！
         ↑ 明明有了结果，LLM 却还在问同一个问题
```

**为什么会发生？**

- LLM 不理解「我已经有答案了」——它对 tool 结果产生了怀疑
- 工具返回了意外数据，LLM 想再试一次
- 上下文太长，LLM 忘了之前已经调过这个工具
- **这是 LLM 自身的局限，不是你的代码问题**

**检测算法：**

```python
def detect_tool_loop(tool_history: list[list[tuple[str, str]]]) -> bool:
    """
    检测工具循环。

    参数:
        tool_history: 每轮的工具调用记录
                      [[(name1, args1), (name2, args2)], [(name1, args1)], ...]

    返回:
        True 如果检测到循环
    """
    if len(tool_history) < 3:
        return False  # 至少需要 3 轮才能判断

    # 取最近 3 轮
    last_3 = tool_history[-3:]

    # 检查是否完全相同
    if last_3[0] == last_3[1] == last_3[2]:
        return True

    # 检查「轮次内完全一样，但轮次间不完全一样」
    # 比如: [A, A, A] → 循环
    #       [A, B, A] → 不是循环（可能是在试不同的工具）

    # 检查「工具名相同但参数不同」
    last_names = [set(name for name, _ in turn) for turn in last_3]
    if last_3[0] and last_3[1] and last_3[2]:
        if all(n == last_names[0] for n in last_names):
            return True  # 3 轮都调了同一组工具

    return False
```

**我们的实战版本（`_detect_tool_loop` 方法）** 做了简化：只检查连续两次的 tool call 是否相同。连续相同 ≥ 2 次就触发。

**检测到循环后做什么？**

```python
# 方案 A：温柔干预（推荐）
if detected_loop:
    messages.append({
        "role": "user",
        "content": "检测到工具循环。你已获得了所需信息，请直接回答用户的问题，不要再调用工具。"
    })
    continue  # 继续循环，但让 LLM 知道要停止

# 方案 B：强制结束
if detected_loop:
    return "⚠️ 检测到工具循环，Agent 已终止。"

# 方案 C：指数退避（进阶）
if detected_loop:
    # 让 LLM 等 5 秒再继续（成本惩罚）
    time.sleep(5)
```

### 6.4 完整的错误处理流程

```python
def run_with_error_handling(self, user_input: str) -> str:
    """带完整错误处理的 Agent 运行"""
    # ... 初始化 ...

    for turn in range(self.max_turns):
        try:
            # ── LLM 调用阶段 ──
            try:
                response = self.call_llm(messages)
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code == 429:
                    retry_after = int(e.response.headers.get("retry-after", 5))
                    print(f"  频率限制，等待 {retry_after}s...")
                    time.sleep(retry_after)
                    response = self.call_llm(messages)  # 重试一次
                elif code in (500, 502, 503):
                    print("  服务器错误，重试...")
                    time.sleep(2)
                    response = self.call_llm(messages)
                else:
                    raise  # 其他错误不重试

            assistant_msg = response["choices"][0]["message"]

            # ── 解析阶段 ──
            tool_calls = assistant_msg.get("tool_calls")

            if not tool_calls:
                return assistant_msg.get("content") or ""

            # ── 循环检测 ──
            if self._detect_tool_loop(tool_calls):
                messages.append({
                    "role": "user",
                    "content": "检测到工具循环，请直接回答。"
                })
                continue

            messages.append(assistant_msg)

            # ── 工具执行阶段 ──
            tool_messages = self._execute_tool_calls(tool_calls, messages)
            messages.extend(tool_messages)

        except Exception as e:
            # 兜底：任何未捕获的异常
            return f"⚠️ Agent 遇到意外错误: {type(e).__name__}: {str(e)}"

    return f"⚠️ 达到最大轮数限制 ({self.max_turns})。"
```

---

## 七、动手实验

### 实验 1：跑通基础 Agent

```bash
cd week03/day03
python agent_loop.py
```

输入：「北京天气怎么样？顺便算一下 1024 * 768 等于多少？」

预期输出：
```
🤖 Agent 启动 | 模型: gpt-4o | max_turns: 10
📤 用户: 北京天气怎么样？顺便算一下 1024 * 768 等于多少？
────────────────────────────────────────
🔄 Turn 1/10
  → 执行 2 个工具调用
  🔧 get_weather({"city": "北京"})
     ✓ 完成 (0.00s): {"city": "北京", "temperature": 28, ...}
  🔧 calculate({"expression": "1024 * 768"})
     ✓ 完成 (0.00s): {"expression": "1024 * 768", "result": 786432}

🔄 Turn 2/10
📥 Agent 回答 (XX 字符):
   北京今天 28°C，晴，湿度 45%。1024 * 768 = 786432。
```

### 实验 2：测试 max_turns 超时

```python
# 创建一个永远调工具的 Agent（通过一个奇怪的 prompt 诱导）
agent = ToolAgent(
    system_prompt="你将不断使用 get_current_time 工具，每次调用前先反思一下之前的结果。",
    tools=TOOLS,
    tool_handlers=HANDLERS,
    max_turns=3,  # 只给 3 轮！
)

result = agent.run("现在几点了？")
print(result)
# 预期输出: ⚠️ 达到最大轮数限制 (3)，Agent 被迫停止。
```

### 实验 3：加一个新工具

给你的 Agent 添加一个 `translate` 工具：

```python
def translate_handler(text: str, target_lang: str) -> dict:
    """翻译文本（模拟）"""
    # 可以调真正的翻译 API
    translations = {
        ("hello", "中文"): "你好",
        ("goodbye", "中文"): "再见",
    }
    result = translations.get((text.lower(), target_lang), f"[模拟翻译] {text} → {target_lang}")
    return {"original": text, "target_lang": target_lang, "result": result}

# 注册
HANDLERS["translate"] = translate_handler

# 添加 tool schema
TOOLS.append({
    "type": "function",
    "function": {
        "name": "translate",
        "description": "将文本翻译成目标语言",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待翻译的文本"},
                "target_lang": {"type": "string", "description": "目标语言，如 中文、English、日本語"},
            },
            "required": ["text", "target_lang"],
        },
    },
})
```

**加一个新工具只需要 4 步：**
1. 写 handler 函数
2. 注册到 `HANDLERS` dict
3. 添加 tool schema 到 `TOOLS` list
4. 重启 Agent

### 实验 4：观察 messages 增长

```python
# 在 ToolAgent.run() 中加一行调试输出
for turn in range(self.max_turns):
    print(f"  messages 当前长度: {len(messages)} 条")

    # ... 调 LLM ...

    # 发现 tool_calls 后
    print(f"  本轮增加: 1 assistant + {len(tool_calls)} tool = {1 + len(tool_calls)} 条")
    print(f"  messages 新长度: {len(messages)} 条")
```

### 实验 5：故意触发工具循环

```python
# 用一个「有 bug」的 handler 来触发循环
counter = 0

def buggy_search_handler(query: str) -> dict:
    """每次返回不同的结果，让 LLM 困惑"""
    global counter
    counter += 1
    return {"query": query, "result": f"第 {counter} 次结果", "complete": counter >= 3}

# 注册 buggy handler，观察循环检测是否生效
```

---

## 八、踩坑记录

### 坑 1：max_turns 不是超时时间

```
❌ 误解：max_turns=10 表示「最多运行 10 秒」
✅ 正解：max_turns=10 表示「最多调用 10 次 LLM API」

一个慢工具（如网页抓取，5 秒）+ 10 轮 = 至少 50 秒
你的 HTTP 客户端超时（timeout=30）可能先触发！
```

**解决：** 要么设大的 timeout（`timeout=120` 给复杂 Agent），要么单独给慢工具设超时。

### 坑 2：tool_call_id 不匹配

```
❌ 错误：
  assistant(tool_calls=[{"id": "call_abc", ...}])
  → 执行工具
  tool(tool_call_id="call_def", ...)  ← id 不对！
  → API 报错：找不到对应的 tool_call

✅ 正确：
  tool(tool_call_id="call_abc", ...)  ← 必须和 assistant 消息里的 id 一致
```

**关键：** `tool_call_id` 是 LLM API 返回的**唯一 ID**，不是你自己生成的！

### 坑 3：LLM 返回的参数是字符串，不是对象

```python
# LLM API 返回的原始响应
tool_call = {
    "id": "call_abc",
    "function": {
        "name": "get_weather",
        "arguments": '{"city": "北京"}'  # ← 字符串！不是 dict！
    }
}

# 必须解析
args = json.loads(tool_call["function"]["arguments"])
```

### 坑 4：tool 消息不能有 system

有些 API 的 tool 角色消息不能包含 `role: system` 前面没有对应的 tool_calls。确保：
```
消息顺序必须是：
system → user → assistant(tool_calls) → tool → tool → assistant(text)
```

**不能：**
```
system → user → tool(xxx)  ← ❌ tool 前没有 assistant(tool_calls)
```

### 坑 5：流式模式下 tool_calls 的处理

如果你用了 streaming（流式输出），tool_calls 是**分块到达**的：

```python
# 流式 chunk 1: {"delta": {"tool_calls": [{"index": 0, "function": {"name": "get_"}]}}
# 流式 chunk 2: {"delta": {"tool_calls": [{"index": 0, "function": {"name": "weather"}]}}
# 流式 chunk 3: {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\""}]}}
# ...

# 你需要按 index 拼接！
```

**结论：** 非流式模式处理 tool_calls 简单得多。初学时先用非流式。

### 坑 6：LLM 可能一次请求 10+ 个工具

虽然 LLM 通常一次请求 1-5 个工具，但某些配置下（如 `tool_choice: "required"`）它可能一次请求很多个。你的 Agent 需要能处理任意数量的并行 tool_calls。

```python
# 安全处理
max_parallel_tools = 10
tool_calls = assistant_msg.get("tool_calls", [])
if len(tool_calls) > max_parallel_tools:
    # 截断或分批次执行
    tool_calls = tool_calls[:max_parallel_tools]
    print(f"⚠️ 工具请求过多，只执行前 {max_parallel_tools} 个")
```

---

## 九、副线笔记

### 今日思考题

1. **Claude Code 的 Agent Loop 长什么样？** 观察它处理复杂任务时的 tool call 序列——它是一次发多个并行 tool call 还是一个个串行？它的 max_turns 是多少？

2. **对比两种循环实现：**
   - `while True` + `break`（上面的实现方式）
   - `for turn in range(max_turns)` + `return`（我们用 for 实现）
   - 各有什么优缺点？

3. **如果 API 不支持 tools 参数怎么办？** （比如某些国产模型）你怎么在没有 Function Calling 的情况下实现 Agent Loop？

4. **messages 里 system prompt 占了很大比例。** 有什么办法能不每次都发 system prompt？

### 扩展阅读

- [OpenAI Function Calling 官方文档](https://platform.openai.com/docs/guides/function-calling)
- [Anthropic Tool Use 文档](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172)

### 今天用 Claude Code 做了什么：

__________

### 代码仓库检查清单

- [ ] `agent_loop.py` 能正常运行，输出正确结果
- [ ] 测试了多工具组合请求（weather + calculate）
- [ ] 测试了 max_turns 超时场景
- [ ] 验证了 `_detect_tool_loop` 检测逻辑
- [ ] 尝试加了一个新工具（如 translate）
- [ ] 阅读了 `__main__` 里的运行结果

---

## Day 03 总结

| 概念 | 一句话 | 
|------|--------|
| Agent Loop | `while True: call_llm → parse → execute → append` |
| ToolAgent | 封装了 messages 管理、工具注册、循环控制的类 |
| max_turns | 安全网：防止 Agent 无限运行 |
| messages 增长 | 每轮 append，是 Agent 的短期记忆，但会耗尽 Context Window |
| Handler 注册 | dict 映射工具名 → 函数，而不是 if-else |
| 工具循环检测 | 连续相同 tool call 时，干预 LLM 或强制结束 |
| 错误处理原则 | 工具错误不抛异常，返回给 LLM 自行决策 |
