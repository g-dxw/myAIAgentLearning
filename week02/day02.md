# Day 02 — Context Window & Token 预算管理

## 学习目标

理解 LLM 的 Context Window 限制及其对 Agent 设计的影响，掌握长对话的 Token 预算管理策略（滑动窗口、摘要压缩），能实现对话历史的智能裁剪。

---

## 一、Context Window 是什么

### 1.1 上下文窗口 = 模型的"记忆容量"

```
Context Window = 模型一次能"看到"的最大 token 数

┌─────────────────── Context Window (200K tokens) ──────────────────┐
│ System Prompt │ 历史消息1 │ 历史消息2 │ ... │ 当前消息 │ 预留输出 │
│    ~500 t     │  ~300 t   │  ~400 t   │     │  ~500 t   │ ~4000 t │
└───────────────────────────────────────────────────────────────────┘
    如果累计超过 200K → 最前面的内容被截断或报错
```

常见模型的 Context Window：

| 模型 | Context Window | 约等于 |
|------|---------------|--------|
| Claude Opus 4.7 | 200K tokens | ~150K 英文单词 / ~300 页 |
| Claude Sonnet 4.6 | 200K tokens | 同上 |
| Claude Haiku 4.5 | 200K tokens | 同上 |
| GPT-4 Turbo | 128K tokens | ~96K 英文单词 |
| DeepSeek V3 | 128K tokens | ~96K 英文单词 |

**200K tokens 听起来很大，但在 Agent 场景下消耗很快**，因为：
- System prompt（工具定义）可能占 2K~5K
- 每轮对话 500~1000 tokens
- Tool use 每轮额外 2K~5K（工具结果）
- 50 轮对话 + 5 次工具调用就能轻松破 200K

### 1.2 超过 Context Window 会怎样

```python
# 情况 1：API 直接报错
# HTTP 400: "Input is too long for the model"

# 情况 2：模型"遗忘"（静默截断）
# API 可能成功，但模型只看到了最后 N 个 token
# 前面的 system prompt、对话历史全丢了
# 模型行为变奇怪，但不报错——更难排查！

# 情况 3：prefill 失败
# 输入在预填充阶段就超过限制，直接拒绝
```

### 1.3 Context Window 里的"座位分配"

```
200K token 预算怎么分：

┌──────────────┬──────────────┬──────────────┬──────────────┐
│ System       │ 对话历史      │ 附件/上下文    │ 输出预留      │
│ Prompt       │ Messages     │ Documents    │ max_tokens   │
├──────────────┼──────────────┼──────────────┼──────────────┤
│ 固定开销      │ 持续增长      │ 按需注入      │ 必须预留      │
│ ~1K-5K       │ ~1K-50K      │ ~0-50K       │ ~4K-16K      │
└──────────────┴──────────────┴──────────────┴──────────────┘

实际可用给对话历史的 ≈ 200K - System - 附件 - 输出预留
                    ≈ 200K - 5K - 0 - 8K
                    ≈ 187K → 大概够 150~200 轮普通对话
```

---

## 二、长对话管理的三种策略

### 2.1 策略一：滑动窗口（Sliding Window）

最简单：只保留最近 N 条消息或最近 N 个 token。

```python
"""滑动窗口 —— 只保留最近的消息"""
import tiktoken

enc = tiktoken.get_encoding("cl100k_base")

def sliding_window(
    messages: list[dict],
    max_tokens: int,
    system_prompt: str = "",
) -> list[dict]:
    """
    保留 system prompt + 最近的消息，总 token 不超过 max_tokens
    从最新往旧裁剪
    """
    system_tokens = len(enc.encode(system_prompt)) if system_prompt else 0
    budget = max_tokens - system_tokens

    result = []
    if system_prompt:
        result.append({"role": "system", "content": system_prompt})

    # 从后往前加，直到超出预算
    total = 0
    reversed_selected = []
    for msg in reversed(messages):
        msg_tokens = len(enc.encode(msg.get("content", ""))) + 6  # 6 = 格式开销
        if total + msg_tokens > budget:
            break
        total += msg_tokens
        reversed_selected.append(msg)

    result.extend(reversed(reversed_selected))
    return result

# 示例
history = [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！有什么可以帮助你的？"},
    {"role": "user", "content": "解释一下 Python 装饰器"},
    {"role": "assistant", "content": "装饰器是..." * 500},  # 很长的回复
    {"role": "user", "content": "能举个实例吗？"},
    {"role": "assistant", "content": "当然，这里有一个计时装饰器..."},
]

trimmed = sliding_window(history, max_tokens=2000, system_prompt="You are helpful.")
print(f"原始消息数: {len(history)}, 裁剪后: {len(trimmed)}")
```

### 2.2 策略二：摘要压缩（Summarization）

用 LLM 把历史对话压缩成一段摘要。**优点**是信息密度高，**缺点**是丢失细节。

```python
"""摘要压缩 —— 把旧对话压缩成一段简短摘要"""

async def summarize_history(
    messages: list[dict],
    client,  # httpx.AsyncClient
    model: str = "claude-haiku-4-5",  # 用便宜的模型做摘要
) -> str:
    """把对话历史压缩为摘要"""
    # 把 messages 序列化为文本
    transcript = "\n".join(
        f"[{m['role']}]: {m['content'][:200]}"  # 每条只取前 200 字符
        for m in messages
    )

    resp = await client.post("https://api.anthropic.com/v1/messages", json={
        "model": model,
        "max_tokens": 500,
        "messages": [{
            "role": "user",
            "content": f"请用 2-3 句话总结以下对话的关键信息，保留所有重要事实和决策：\n\n{transcript}"
        }],
    })
    data = resp.json()
    return data["content"][0]["text"]


def build_context_with_summary(
    full_history: list[dict],
    max_tokens: int,
    summary: str,
    recent_count: int = 6,  # 保留最近 6 条完整消息
) -> list[dict]:
    """
    用摘要替代旧消息：summary + 最近 N 条完整消息
    """
    result = []
    if summary:
        result.append({
            "role": "user",
            "content": f"[前情提要]\n{summary}\n---\n以下是最近的对话："
        })

    # 保留最后 recent_count 条
    result.extend(full_history[-recent_count:])

    # Token 检查（简化版）
    return result
```

### 2.3 策略三：混合策略（推荐）

```
对话历史管理策略（生产级）：

全部历史
│
├─ 最近 N 条消息 ──────────────→ 原样保留（滑动窗口）
│
├─ N 条之前的消息 ─────────────→ 用 cheap model 生成摘要
│
└─ 超长单条消息 ───────────────→ 截断到 max_length

什么时候触发压缩：
  - Token 数超过阈值的 70%（预警线）
  - Token 数超过阈值的 90%（强制压缩）
  - 消息条数超过 N 条
```

```python
"""混合策略 —— 滑动窗口 + 摘要压缩"""
from enum import Enum

class ContextStrategy:
    RECENT_WINDOW = 10      # 最近 10 条完整保留
    SUMMARY_EVERY = 20      # 每 20 条做一次摘要
    WARNING_RATIO = 0.7     # 70% 容量时预警
    FORCE_RATIO = 0.9       # 90% 容量时强制压缩

async def smart_trim_context(
    messages: list[dict],
    model_context_limit: int,
    max_output_tokens: int,
    summary: str | None = None,
    client = None,
) -> tuple[list[dict], str | None]:
    """
    智能裁剪上下文。
    返回 (裁剪后的消息列表, 新摘要)
    """
    budget = model_context_limit - max_output_tokens

    # 1. 如果消息很少，直接返回
    estimated_tokens = sum(len(enc.encode(m.get("content", ""))) for m in messages)
    if estimated_tokens < budget * ContextStrategy.WARNING_RATIO:
        return messages, summary

    # 2. 超过预警线：对前 80% 的消息做摘要
    if client and len(messages) > ContextStrategy.SUMMARY_EVERY:
        old_messages = messages[:-ContextStrategy.RECENT_WINDOW]
        recent_messages = messages[-ContextStrategy.RECENT_WINDOW:]
        new_summary = await summarize_history(old_messages, client)
        return build_context_with_summary(
            messages, budget, new_summary or summary or "", ContextStrategy.RECENT_WINDOW
        ), new_summary

    # 3. 没有 client：降级为纯滑动窗口
    return sliding_window(messages, budget), summary
```

---

## 三、System Prompt 的 Token 优化

### 3.1 精简 System Prompt

```python
# ❌ 冗长的 system prompt（~500 tokens）
system_prompt = """
You are an AI assistant specializing in Python programming.
You have extensive knowledge of Python 3.8+, FastAPI, Pydantic v2,
SQLAlchemy 2.0+, async/await patterns, and best practices for building
production-grade web applications. You always provide type-safe code
examples and explain the reasoning behind your design decisions.
...
"""

# ✅ 精简版（~100 tokens）
system_prompt = """You are a Python expert. Write type-safe, async-first
code with FastAPI + Pydantic v2 + SQLAlchemy. Prefer brevity."""

# 每个 token 都要问自己：删掉这句，模型能力会变差吗？
```

### 3.2 工具定义的 Token 优化

```python
# ❌ 工具定义里写一堆废话
tools = [{
    "name": "search_database",
    "description": "This tool allows you to search the database for records. "
                   "You can use it to find information about users, products, "
                   "orders, and other entities stored in the system. "
                   "The query parameter should be a valid SQL-like query string.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query string. This should be a "
                               "properly formatted search query that the "
                               "database can understand and execute."
            }
        }
    }
}]

# ✅ 精简版：description 只写"什么时候用"和"参数格式"
tools = [{
    "name": "search_database",
    "description": "Search DB records. query: SQL-like string.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL-like search query"
            }
        }
    }
}]
```

---

## 四、Token 预算监控

### 4.1 实现一个 TokenBudget 类

```python
"""Token 预算管理和预警"""
import tiktoken
from dataclasses import dataclass

@dataclass
class TokenBudget:
    context_limit: int        # 模型上下文上限
    max_output: int = 8192   # 预留输出 token
    warning_ratio: float = 0.7
    critical_ratio: float = 0.9

    def __post_init__(self):
        self._enc = tiktoken.get_encoding("cl100k_base")
        self._effective_limit = self.context_limit - self.max_output

    def check(self, messages: list[dict]) -> dict:
        """检查当前消息列表的 token 状态"""
        total = 0
        for msg in messages:
            total += len(self._enc.encode(msg.get("content", "")))
            total += 4  # 格式开销

        ratio = total / self._effective_limit
        status = "ok"
        if ratio >= self.critical_ratio:
            status = "critical"
        elif ratio >= self.warning_ratio:
            status = "warning"

        return {
            "total_tokens": total,
            "limit": self._effective_limit,
            "ratio": ratio,
            "status": status,
            "remaining": self._effective_limit - total,
        }

# 使用
budget = TokenBudget(context_limit=200_000, max_output=8192)

messages = [{"role": "user", "content": "Hello " * 50000}]  # 模拟大量内容
status = budget.check(messages)
print(f"Token: {status['total_tokens']}/{status['limit']} ({status['ratio']:.1%}) → {status['status']}")
# Token: 50004/191808 (26.1%) → ok
```

### 4.2 在 Agent 循环中集成

```python
async def agent_loop_with_budget(
    user_message: str,
    history: list[dict],
    budget: TokenBudget,
    llm_client,
):
    """带 token 预算检查的 Agent 循环"""
    # 添加用户消息
    history.append({"role": "user", "content": user_message})

    # 检查预算
    status = budget.check(history)
    print(f"[Token] {status['total_tokens']}/{status['limit']} ({status['ratio']:.1%})")

    if status["status"] == "critical":
        print("[Token] ⚠️ 接近上限，触发强制压缩...")
        history, _ = await smart_trim_context(
            history, budget.context_limit, budget.max_output, client=llm_client
        )
        new_status = budget.check(history)
        print(f"[Token] 压缩后: {new_status['total_tokens']}/{new_status['limit']} ({new_status['ratio']:.1%})")

    elif status["status"] == "warning":
        print("[Token] ⚡ 预警：token 使用超过 70%")

    # 调用 LLM...
    return history
```

---

## 五、今日练习（约 2 小时）

### 练习 1：实现滑动窗口（30 min）

完善上面的 `sliding_window` 函数：
1. 支持 system prompt 必须保留
2. 支持"至少保留最近 N 条"参数
3. 正确处理 tool_use 和 tool_result 的配对（不能拆散）

### 练习 2：实现 TokenBudget 监控（30 min）

完善 `TokenBudget` 类：
1. 添加 `estimate_message(msg)` 方法，精确计算单条消息的 token
2. 添加 `can_add(msg)` 方法，判断还能不能加一条消息
3. 添加日志回调：当状态从 ok→warning 时触发

### 练习 3：模拟长对话 Token 增长曲线（30 min）

```python
"""画一条 Token 增长曲线（控制台即可）"""
def simulate_token_growth(
    initial_system_tokens: int,
    avg_turn_tokens: int,
    num_turns: int,
    context_limit: int,
):
    """模拟 N 轮对话的 token 消耗"""
    total = initial_system_tokens
    print(f"初始 (system): {total} tokens")
    print(f"{'轮次':<8} {'本轮新增':<12} {'累计':<12} {'占比':<10} {'状态'}")
    print("-" * 55)

    for i in range(1, num_turns + 1):
        total += avg_turn_tokens
        ratio = total / context_limit
        status = "🟢" if ratio < 0.7 else ("🟡" if ratio < 0.9 else "🔴")
        print(f"第{i}轮     +{avg_turn_tokens:<10} {total:<12} {ratio:>7.1%}    {status}")

    return total

simulate_token_growth(
    initial_system_tokens=2000,
    avg_turn_tokens=800,
    num_turns=200,
    context_limit=200_000,
)
```

### 练习 4：三种策略对比测试（30 min）

用一段模拟的长对话，对比三种策略的效果：
1. 不裁剪（原始）
2. 滑动窗口
3. 滑动窗口 + 摘要

记录每种策略的 token 消耗和信息损失。

---

## 六、踩坑记录

```
[ ] 坑 1：____________________
解决：____________________

[ ] 坑 2：____________________
解决：____________________
```

**常见坑预警：**

| 坑 | 表现 | 解决 |
|----|------|------|
| ❌ tool_use 和 tool_result 被滑动窗口拆散 | API 报错：tool_result 找不到对应的 tool_use | 滑动窗口以"完整 turn"为单位裁剪，不拆散配对 |
| ❌ 只统计 content 的 token，忽略 role 和结构 | 实际 token 比估算的多 20%+ | 每条消息加 4~8 token 的格式开销 |
| ❌ Context Window 200K 就以为能装 200K 消息 | 输入到 150K 就开始不稳定 | 始终预留 20% 的 buffer，不要顶满 |
| ❌ 裁剪后忘了更新摘要 | 摘要说的是"前面讨论过 X"，但 X 其实被保留了 | 摘要只覆盖真正被裁剪掉的消息 |

---

## Day 02 检查清单

- [ ] 理解 Context Window 的概念和限制
- [ ] 知道 200K tokens 在 Agent 场景下的实际可用量
- [ ] 能实现滑动窗口策略
- [ ] 能实现摘要压缩策略
- [ ] 知道三种策略的优劣和适用场景
- [ ] 能实现 TokenBudget 监控类
- [ ] 知道 tool_use/tool_result 必须成对裁剪
- [ ] 理解为什么要预留 20% buffer

---

## 副线：Claude Code 实战

### 今天的任务：观察 Claude Code 的 Context 管理

Claude Code 本身就是一个 Agent，它也在管理 Context Window。今天观察：

1. 当对话变长（50+ 轮），Claude Code 会不会"忘记"你之前说过的话？
2. 它在什么时候会压缩上下文？（如果你看到 "summarizing conversation..." 之类的提示）
3. 对比：开一个新的对话 vs 在长对话里继续，Claude Code 的反应有什么不同？

### CLI Agent 认知笔记

```
长对话时 Claude Code 的表现变化：____________________
它有没有"忘记"之前的约定：____________________
下次面对长任务，怎么规划对话节奏：____________________
```

---

## 明天计划

- [ ] Day 03 — Thinking / Effort：理解 Claude 的思考机制、Effort 参数、Extended Thinking 的使用场景
