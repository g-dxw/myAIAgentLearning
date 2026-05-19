# Day 03 — Thinking / Effort 机制

## 学习目标

深入理解 Claude 的 Thinking（思考）机制，掌握 Effort 参数对思考深度、token 消耗和回复质量的影响，学会在 Agent 场景下针对不同任务选择合适的 effort 级别。

---

## 一、Thinking 是什么

### 1.1 模型不只是"说"，还会"想"

```
没有 Thinking 的模型：
  输入 → [黑盒推理] → 输出
  你只能看到结果，看不到思考过程

有 Thinking 的模型：
  输入 → [思考过程（可见/不可见）] → [基于思考的回复]
  你可以看到模型在"想什么"
```

**Claude 的 Thinking 分两种模式：**

| 模式 | 思考过程可见？ | Token 消耗 | 适用场景 |
|------|--------------|-----------|---------|
| 普通回复 | 不可见 | 正常 | 简单问答、代码生成 |
| Extended Thinking | 可见（单独返回 thinking block） | 思考消耗额外 token | 复杂推理、数学、多步分析 |

### 1.2 Thinking 在 API 中的样子

```python
# API 响应中有 thinking 类型的 content block
response = {
    "content": [
        # 思考过程（如果启用了 thinking）
        {
            "type": "thinking",
            "thinking": "我需要分析这段代码的逻辑。首先看函数签名...\n"
                       "参数类型是 str | int，说明需要处理两种情况...\n"
                       "让我逐步梳理边界条件...",
            "signature": "..."  # 思考的加密签名（验证完整性）
        },
        # 正式回复
        {
            "type": "text",
            "text": "分析结果：这段代码在处理..."
        }
    ],
    "usage": {
        "input_tokens": 500,
        "output_tokens": 350,   # 包含 thinking + text 的 token
    }
}
```

### 1.3 思考 token 也计费，但便宜

```
输出 token 单价 = $75/1M (Opus)
  ├── thinking tokens:  按正常输出计费
  └── text tokens:      按正常输出计费

但 thinking token 的优势：
  - 不显示给用户（可以设为不可见）
  - 让模型更"深思熟虑"，减少后续纠错成本
  - 复杂任务中，花 500 token 思考可能省掉 2000 token 的反复修正
```

---

## 二、Effort 参数

### 2.1 Effort 控制思考深度

```python
# Claude API 的 thinking 参数
import anthropic

client = anthropic.Anthropic()

# Effort 级别（仅 Opus/Sonnet 支持）
# "low"     —— 很少思考，快速回复
# "medium"  —— 适度思考（默认）
# "high"    —— 深入思考

response = client.messages.create(
    model="claude-opus-4-7",
    max_tokens=4096,
    thinking={
        "type": "enabled",
        "budget_tokens": 2000,  # 最多用 2000 token 来思考
        # effort: "high"        # 某些模型支持直接设 effort
    },
    messages=[{"role": "user", "content": "解释量子计算的原理"}],
)

for block in response.content:
    if block.type == "thinking":
        print(f"[思考] {block.thinking[:200]}...")
    elif block.type == "text":
        print(f"[回复] {block.text}")
```

### 2.2 Budget Tokens vs Effort

```
budget_tokens: 思考的最大 token 数（硬上限）
effort:        模型愿意花多少 token 思考（软调节）

- budget_tokens=500,  effort=high   → 模型尽量在 500 token 内深度思考
- budget_tokens=2000, effort=low    → 给了 2000 预算但模型可能只用了 200
- budget_tokens=2000, effort=high   → 模型充分利用 2000 token 深度推理

建议：
  简单问答：budget_tokens=500
  代码审查：budget_tokens=2000
  复杂数学：budget_tokens=4000+
  Agent 规划：budget_tokens=3000
```

### 2.3 什么时候开启 Thinking

```
✅ 应该开启的场景：
  - 数学计算、逻辑推理
  - 复杂代码分析（多文件、多依赖）
  - Agent 规划和决策（"我该用哪个工具？"）
  - 多步骤问题的分步推理
  - 需要解释推理过程的场景

❌ 不需要的场景：
  - 简单翻译、改写
  - 格式转换（JSON ↔ YAML）
  - 已经确定的工具调用
  - 极低延迟要求的场景
  - 用 Haiku 模型（不支持 thinking）
```

---

## 三、Thinking 的实战模式

### 3.1 模式对比实验

```python
"""对比：有 Thinking vs 无 Thinking 的回复质量"""
import asyncio
import httpx
import json
import os

async def compare_thinking_vs_normal(prompt: str):
    """用同一个 prompt 测试 think vs no-think 的区别"""
    headers = {
        "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        # 请求 1：启用 thinking
        resp1 = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 4096,
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 2000,
                },
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        data1 = resp1.json()

        # 请求 2：不启用 thinking
        resp2 = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        data2 = resp2.json()

        # 对比
        thinking_tokens = data1["usage"]["output_tokens"]
        normal_tokens = data2["usage"]["output_tokens"]

        thinking_text = data1["content"][-1]["text"] if data1["content"] else ""
        normal_text = data2["content"][-1]["text"] if data2["content"] else ""

        print(f"=== 对比结果 ===")
        print(f"Thinking 版: 输出 {thinking_tokens} tokens")
        print(f"普通版:     输出 {normal_tokens} tokens")
        print(f"Thinking 回复长度: {len(thinking_text)} 字符")
        print(f"普通版回复长度:    {len(normal_text)} 字符")

        return data1, data2

# 运行
# asyncio.run(compare_thinking_vs_normal(
#     "分析以下代码的时间复杂度，并给出优化建议：\n" +
#     "def find_duplicates(arr):\n    for i in range(len(arr)):\n        for j in range(i+1, len(arr)):\n            if arr[i] == arr[j]:\n                return True\n    return False"
# ))
```

### 3.2 让 Thinking 过程也可见（Agent 调试利器）

```python
"""在 Agent 中展示 Thinking 过程"""
async def agent_with_visible_thinking(user_message: str, history: list[dict]):
    """带可见 thinking 的 Agent 执行"""
    thinking_steps = []

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 4096,
                "thinking": {"type": "enabled", "budget_tokens": 3000},
                "messages": history + [{"role": "user", "content": user_message}],
            },
        )
        data = resp.json()

        for block in data["content"]:
            if block["type"] == "thinking":
                # 收集思考过程（调试用）
                thinking_steps.append(block["thinking"])
                print(f"\n🧠 [Thinking]\n{block['thinking'][:200]}...")
            elif block["type"] == "tool_use":
                print(f"\n🔧 [Tool Call] {block['name']}({block['input']})")
            elif block["type"] == "text":
                print(f"\n💬 [Reply]\n{block['text']}")

    return data["content"], thinking_steps
```

---

## 四、Thinking 的成本权衡

### 4.1 用一个表格说清楚

```
任务：分析一个复杂函数的 bug，给出修复方案

                    普通模式          Thinking 模式
─────────────────────────────────────────────────────
思考 token              0                  1200
回复 token             800                  600
总输出 token           800                 1800
输出成本 (Opus)      $0.060              $0.135
回复质量              找到 1 个 bug      找到 3 个 bug + 给出根因
是否需要二次追问      是                  否
二次追问成本          +$0.080             $0
实际总成本            $0.140              $0.135  ← 反而更便宜
─────────────────────────────────────────────────────
结论：复杂任务开 Thinking 可能反而更省钱
```

### 4.2 选择 Effort 的决策表

| 任务类型 | 推荐 Effort | Budget | 理由 |
|---------|------------|--------|------|
| 闲聊/简单问答 | 不开 | — | 不需要思考，直接回答 |
| 代码补全 | 不开 | — | 模式匹配为主 |
| Bug 诊断 | medium/high | 2000 | 需要推理因果链 |
| 架构设计 | high | 4000 | 多约束权衡 |
| Agent 规划 | high | 3000 | 需要思考工具选择和顺序 |
| 数学证明 | high | 4000+ | 每步都需要严格推理 |
| 合同/法律分析 | high | 4000+ | 不能出错 |

---

## 五、今日练习（约 2 小时）

### 练习 1：观察 Thinking 效果（30 min）

用同一个复杂 Prompt（比如："设计一个分布式限流算法，要处理时钟偏移问题"），分别测试：
1. 不开 Thinking
2. Thinking + budget_tokens=1000
3. Thinking + budget_tokens=4000

对比：回复质量、token 消耗、思考过程（如果有的话）是否合理。

### 练习 2：实现 Thinking 模式的 Cost 对比工具（30 min）

```python
@dataclass
class ThinkingComparison:
    prompt: str
    no_think_tokens: int = 0
    think_tokens: int = 0
    no_think_quality: int = 0    # 1-5 主观评分
    think_quality: int = 0

    def report(self) -> str:
        no_cost = self.no_think_tokens / 1_000_000 * 75  # output price
        think_cost = self.think_tokens / 1_000_000 * 75
        return (
            f"无思考: {self.no_think_tokens}t, 质量 {self.no_think_quality}/5, ${no_cost:.4f}\n"
            f"有思考: {self.think_tokens}t, 质量 {self.think_quality}/5, ${think_cost:.4f}\n"
            f"性价比: {'思考更优' if self.think_quality/think_cost > self.no_think_quality/no_cost else '不思考更优'}"
        )
```

### 练习 3：Agent 决策日志（30 min）

实现一个 Agent 装饰器，把每次 API 调用的 thinking 内容记录到日志文件：

```python
@log_thinking("agent_decision.log")
async def agent_decide(context: dict) -> str:
    """Agent 做决策，自动记录思考过程"""
    ...
```

### 练习 4：设计你Agent 的思考策略（30 min）

为你的养老护工项目设计 Thinking 使用策略：
- 哪些环节需要开启 Thinking？
- budget_tokens 设多少？
- 思考内容要不要存下来（审计/调试）？
- 成本和延迟预算？

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
| ❌ thinking token + reply token 超出 max_tokens | 回复被截断 | max_tokens 必须 ≥ budget_tokens + 预期回复长度 |
| ❌ thinking 内容不适合展示给用户 | 用户看到"我觉得这个方案不太好" | 过滤 thinking blocks，只传 text blocks 给前端 |
| ❌ 简单任务也开 thinking | 回复变慢、token 翻倍、质量没提升 | 按上面的决策表判断 |
| ❌ Haiku 模型设了 thinking | API 报错或参数被忽略 | 只有 Opus/Sonnet 支持 thinking |

---

## Day 03 检查清单

- [ ] 理解 Thinking 是什么和作用
- [ ] 会用 `thinking.enabled` + `budget_tokens` 参数
- [ ] 知道 Effort 对思考深度的影响
- [ ] 能根据任务类型选择是否开启 Thinking
- [ ] 能解析 API 响应中的 thinking block
- [ ] 理解 Thinking 的成本权衡
- [ ] 能在 Agent 中正确过滤/记录 thinking 内容

---

## 副线：Claude Code 实战

### 今天的任务：对比 Claude Code 的 Thinking 表现

Claude Code 默认开启了 Thinking。今天观察：

1. 找一个复杂问题（比如让你写一个多文件的项目），观察 Claude Code 会不会先"想"再写
2. 找一个简单问题（比如"这个变量名叫什么好"），观察它会不会也"想"很多
3. 用 `/status` 或查看 token 信息，对比 thinking token 和 output token 的比例

### CLI Agent 认知笔记

```
Claude Code 什么情况下 thinking 最有价值：____________________
thinking token 占总输出的比例：____________________
下次怎么利用 thinking 提高任务质量：____________________
```

---

## 明天计划

- [ ] Day 04 — Streaming：SSE 事件类型深入、流式 vs 非流式的延迟对比、在 Agent 中集成流式输出
