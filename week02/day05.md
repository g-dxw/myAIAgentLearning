# Day 05 — Prompt Caching 原理

## 学习目标

理解 Prompt Caching 的工作原理，掌握缓存命中规则（前缀匹配），了解 cache read/write tokens 的计费模型，能设计 cache-friendly 的 prompt 结构。

---

## 一、Prompt Caching 是什么

### 1.1 一张图说明白

```
没有缓存：
  每次请求都把完整的 prompt 发给模型处理
  请求1: [System Prompt 5K][Messages 2K][Current 500] → 7.5K tokens 全价
  请求2: [System Prompt 5K][Messages 3K][Current 500] → 8.5K tokens 全价
        ↑ 完全相同的部分，每请求都重新计算一次

有缓存：
  请求1: [System Prompt 5K][Messages 2K][Current 500] → 5K 写入缓存，7.5K 全价
  请求2: [System Prompt 5K][Messages 3K][Current 500] → 5K 命中缓存 = 0.5K! 省 90%
        ↑ 相同的 System Prompt 不用重复处理
```

**核心机制：** 如果请求的前缀和之前某个请求的前缀相同，那部分就自动命中缓存。**只需要按超低价格（write 的 10%）支付 cache read tokens。**

### 1.2 缓存命中条件 —— 前缀匹配

```
✅ 能命中的情况：
  请求1 prompt: "You are a helpful assistant. 用户的提问是..."
  请求2 prompt: "You are a helpful assistant. 请帮我翻译..."
                               ↑ 这里分叉了
  结果: "You are a helpful assistant. " 这部分命中缓存

❌ 不能命中的情况：
  请求1 prompt: "You are a helpful assistant.\n用户: 今天天气怎么样？"
  请求2 prompt: "用户: 今天天气怎么样？\nYou are a helpful assistant."
               ↑ 前缀不同！即使内容相同，顺序不同也不行

关键规则：
  1. 缓存匹配的是"从开头算起的连续前缀"
  2. 中间相同但开头不同 → 不命中
  3. 前缀相同后面不同 → 相同的前缀部分命中
  4. 缓存有时效性（通常 5 分钟左右，Anthropic 可能更长）
```

### 1.3 缓存的生命周期

```
缓存写入（cache write）：
  - 每次请求时，Claude 自动决定哪些内容值得缓存
  - 写入有额外成本（write tokens 比普通 input 贵 25%）
  - 缓存通常在 5 分钟内有效

缓存读取（cache read）：
  - 后续请求如果前缀匹配，自动命中
  - 读取的价格是普通 input 的 10%！
  - 不需要你手动管理，全自动

缓存过期：
  - 通常在 5 分钟后过期
  - 过期后下次请求需要重新写入
  - 频繁请求相同前缀 → 持续命中 → 大幅省钱
```

---

## 二、缓存的计费模型

### 2.1 Token 计费的四种类型

```python
# API 响应中的 usage 字段
{
    "usage": {
        "input_tokens": 5000,                  # 总输入 token
        "output_tokens": 800,                  # 输出 token（永远不会缓存）
        "cache_creation_input_tokens": 3000,   # 本次写入缓存的 token 数
        "cache_read_input_tokens": 2000,       # 本次命中缓存的 token 数
    }
}

# 实际计费拆解（以 Sonnet 为例）：
# input: $3/1M tokens
# cache_write: $3.75/1M tokens (+25%)
# cache_read: $0.30/1M tokens (-90%)
# output: $15/1M tokens

# 本次调用的实际费用 =
#   (input - cache_creation - cache_read) * $3      ← 普通的 input
# + cache_creation * $3.75                           ← 写入缓存（溢价 25%）
# + cache_read * $0.30                               ← 命中缓存（1 折！）
# + output * $15                                     ← 输出（全价）
```

### 2.2 成本对比计算

```python
"""缓存成本计算器"""
from dataclasses import dataclass

@dataclass
class CachePricing:
    input_per_1m: float       # 普通输入
    cache_write_per_1m: float # 缓存写入（+25%）
    cache_read_per_1m: float  # 缓存读取（-90%）
    output_per_1m: float      # 输出

# Sonnet 4.6 参考价
sonnet = CachePricing(
    input_per_1m=3.0,
    cache_write_per_1m=3.75,
    cache_read_per_1m=0.30,
    output_per_1m=15.0,
)

def calculate_cost(
    pricing: CachePricing,
    input_tokens: int,
    cache_write: int,
    cache_read: int,
    output_tokens: int,
) -> dict:
    """计算实际费用"""
    normal_input = input_tokens - cache_write - cache_read

    normal_cost = normal_input / 1_000_000 * pricing.input_per_1m
    write_cost = cache_write / 1_000_000 * pricing.cache_write_per_1m
    read_cost = cache_read / 1_000_000 * pricing.cache_read_per_1m
    output_cost = output_tokens / 1_000_000 * pricing.output_per_1m

    total = normal_cost + write_cost + read_cost + output_cost

    # 对照：如果不开缓存
    without_cache = input_tokens / 1_000_000 * pricing.input_per_1m + output_cost

    return {
        "total": total,
        "without_cache": without_cache,
        "saved": without_cache - total,
        "saved_pct": (1 - total / without_cache) * 100 if without_cache > 0 else 0,
        "breakdown": {
            "normal_input": normal_cost,
            "cache_write": write_cost,
            "cache_read": read_cost,
            "output": output_cost,
        }
    }

# 场景：System Prompt 5K token，在 100 次请求中
# 请求1：写入缓存
cost1 = calculate_cost(sonnet,
    input_tokens=5500, cache_write=5000, cache_read=0, output_tokens=500)
print(f"第 1 次（写入缓存）: ${cost1['total']:.4f} (含写入溢价)")

# 请求2-100：命中缓存（假设 5 分钟内）
cost_hit = calculate_cost(sonnet,
    input_tokens=5500, cache_write=0, cache_read=5000, output_tokens=500)
print(f"第 2-100 次（命中缓存）: ${cost_hit['total']:.4f}/次")

total_100 = cost1["total"] + cost_hit["total"] * 99
without_100 = cost1["without_cache"] * 100
print(f"\n100 次请求总成本:")
print(f"  有缓存: ${total_100:.2f}")
print(f"  无缓存: ${without_100:.2f}")
print(f"  节省: ${without_100 - total_100:.2f} ({(1 - total_100/without_100)*100:.0f}%)")
```

### 2.3 缓存是否值得 —— 决策表

```
│ 场景                        │ 写缓存成本 │ 读缓存收益 │ 净收益   │
│ System Prompt (5K, 100次)   │ +$0.00375  │ -$0.0135   │ 省钱     │
│ 固定工具定义 (2K, 50次)     │ +$0.0015   │ -$0.0054   │ 省钱     │
│ 长篇文档 (50K, 5次)         │ +$0.0375   │ -$0.135    │ 省钱     │
│ 每次不同的 User 消息 (1K)   │ N/A        │ N/A        │ N/A      │
│ 只调用一次的 prompt         │ +溢价      │ 0          │ 亏       │
│                                                            │
│ 经验法则：                                                  │
│   - 同样内容重复 3 次以上 → 值得缓存                        │
│   - 只调用 1-2 次 → 不需要考虑缓存                          │
│   - Agent 场景几乎一定值得（多轮对话反复用 system prompt）   │
```

---

## 三、设计 Cache-Friendly 的 Prompt

### 3.1 把不变的内容放前面

```python
# ✅ 好的设计：静态内容在前，动态内容在后
def build_prompt_cache_friendly(
    system_prompt: str,         # 不变的
    tool_definitions: str,      # 不变的
    context_documents: str,     # 可能变，但尽量放前面
    conversation_history: list[dict],  # 每次变
    current_message: str,       # 每次变
) -> list[dict]:
    """
    关键原则：把最不容易变的内容放最前面！
    缓存命中从前缀开始匹配，前面的不变 = 高命中率
    """
    system_content = system_prompt
    if tool_definitions:
        system_content += f"\n\n可用工具:\n{tool_definitions}"

    messages = [
        {"role": "system", "content": system_content},
    ]

    # 如果有上下文文档，也放在前面（如果文档不变，也能缓存）
    if context_documents:
        messages.append({
            "role": "user",
            "content": f"参考以下文档回答问题：\n\n{context_documents}"
        })

    # 对话历史 —— 这部分每次都变
    messages.extend(conversation_history)

    # 当前消息 —— 一定在最后
    messages.append({"role": "user", "content": current_message})

    return messages
```

### 3.2 缓存断点 —— 放在动态内容之前

```python
"""使用 cache_breakpoint 精确控制缓存边界"""
# Claude API 支持 cache_breakpoint，标记"缓存到这里为止"

messages = [
    {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": "You are a helpful assistant.",
                "cache_control": {"type": "ephemeral"}  # ← 标记缓存点
            }
        ]
    },
    {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": "可用工具有: ...",
                "cache_control": {"type": "ephemeral"}  # ← 又一个缓存点
            }
        ]
    },
    # 下面的内容不缓存（每次不同）
    {"role": "user", "content": "今天的日期是 2026-01-15"},
]

# 效果：
# - "You are a helpful assistant." → 缓存
# - "可用工具有: ..."               → 缓存
# - "今天的日期是..."               → 不缓存
```

**cache_breakpoint 的用法：**
- 放在一个 content block 的最后一段 text 中
- 标记"到这里可以缓存"
- 一个请求可以有多个 breakpoint
- 如果前面的内容被多次使用，就值得标记

### 3.3 多轮对话的缓存策略

```python
"""Agent 多轮对话的缓存优化"""
class CacheAwareAgent:
    def __init__(self, system_prompt: str, tools: list[dict]):
        self.system_prompt = system_prompt
        self.tools = tools

    def build_messages(self, history: list[dict], new_message: str) -> list[dict]:
        """
        策略：
        1. System prompt → 标记 cache_breakpoint（每轮相同）
        2. 最近 3 轮对话 → 标记 cache_breakpoint（连续请求中相同）
        3. 更早的对话 → 单独放（变化频繁，不值得缓存）
        4. 新消息 → 不缓存
        """
        messages = []

        # Layer 1: System + Tools（永远不变，标记缓存）
        system_text = self.system_prompt
        if self.tools:
            system_text += "\n\n## 可用工具\n" + json.dumps(self.tools, ensure_ascii=False)

        messages.append({
            "role": "system",
            "content": [{
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"}
            }]
        })

        # Layer 2: 固定上下文（如果存在）
        # 例如：项目 CLAUDE.md、知识库片段
        if self.fixed_context:
            messages.append({
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": self.fixed_context,
                    "cache_control": {"type": "ephemeral"}
                }]
            })

        # Layer 3: 滑动窗口内的历史（部分可缓存）
        recent_history = history[-6:]  # 最近 6 条
        if len(recent_history) >= 4:
            # 前 4 条大概率下轮还在 → 标记缓存
            for msg in recent_history[:4]:
                messages.append(msg)
            # 最后 2 条下轮就滚出去了 → 不标记
            for msg in recent_history[4:]:
                messages.append(msg)
        else:
            for msg in recent_history:
                messages.append(msg)

        # Layer 4: 新消息（动态内容，永远在最后）
        messages.append({"role": "user", "content": new_message})

        return messages
```

---

## 四、缓存命中率监控

### 4.1 监控指标

```python
"""缓存命中率追踪"""
from dataclasses import dataclass, field

@dataclass
class CacheMetrics:
    total_requests: int = 0
    total_input_tokens: int = 0
    total_cache_write: int = 0
    total_cache_read: int = 0
    total_cost: float = 0.0
    total_cost_without_cache: float = 0.0

    def record(self, usage: dict, pricing: CachePricing) -> None:
        self.total_requests += 1
        self.total_input_tokens += usage.get("input_tokens", 0)
        self.total_cache_write += usage.get("cache_creation_input_tokens", 0)
        self.total_cache_read += usage.get("cache_read_input_tokens", 0)

        # 计算成本
        result = calculate_cost(
            pricing,
            usage.get("input_tokens", 0),
            usage.get("cache_creation_input_tokens", 0),
            usage.get("cache_read_input_tokens", 0),
            usage.get("output_tokens", 0),
        )
        self.total_cost += result["total"]
        self.total_cost_without_cache += result["without_cache"]

    @property
    def cache_hit_rate(self) -> float:
        """缓存命中率 = cache_read / total_input"""
        if self.total_input_tokens == 0:
            return 0.0
        return self.total_cache_read / self.total_input_tokens

    @property
    def total_saved(self) -> float:
        return self.total_cost_without_cache - self.total_cost

    def report(self) -> str:
        return (
            f"=== 缓存报告 ===\n"
            f"请求数: {self.total_requests}\n"
            f"总输入 token: {self.total_input_tokens:,}\n"
            f"缓存写入: {self.total_cache_write:,}\n"
            f"缓存命中: {self.total_cache_read:,}\n"
            f"命中率: {self.cache_hit_rate:.1%}\n"
            f"总成本: ${self.total_cost:.4f}\n"
            f"节省: ${self.total_saved:.4f} ({self.total_saved/self.total_cost_without_cache*100:.1f}%)"
        )
```

### 4.2 在 Agent 中集成

```python
# 在每个 Agent 的 API 调用后记录
metrics = CacheMetrics()

async def call_llm_with_metrics(messages, client, metrics):
    resp = await client.post(...)
    data = resp.json()
    metrics.record(data["usage"], sonnet)
    if metrics.total_requests % 10 == 0:
        print(f"[Cache] 命中率: {metrics.cache_hit_rate:.1%} | 节省: ${metrics.total_saved:.4f}")
    return data
```

---

## 五、今日练习（约 2 小时）

### 练习 1：缓存原理验证实验（30 min）

写一个脚本，验证缓存行为：
1. 第一次请求：发送 System Prompt（500 token）+ 用户消息
2. 等待 2 秒
3. 第二次请求：同样的 System Prompt + 不同的用户消息
4. 对比两次的 usage（观察 cache_creation 和 cache_read）

### 练习 2：Cache Cost Calculator（25 min）

完善上面的 `calculate_cost` 和 `CacheMetrics`，添加：
1. 支持多个模型的定价配置
2. 输出 "何时回本" 的计算（第几次请求后缓存开始省钱）
3. 图表数据导出（CSV 格式）

### 练习 3：Cache-Friendly Prompt 设计（30 min）

给你现有的一个 Agent（或设计一个新的），用 cache-friendly 原则重构它的 prompt 结构：
1. 标记 cache_breakpoint
2. 估算缓存命中率
3. 计算 100 次请求的预期节省

### 练习 4：缓存策略文档（35 min）

为你的养老护工项目写一页缓存策略文档：
- 哪些内容放在前面（高缓存价值）
- 哪些内容放在后面（高频变化）
- 预期的命中率目标和成本节省

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
| ❌ 把时间戳放 prompt 最前面 | 每次前缀都不同，缓存 0 命中 | 动态内容永远放最后 |
| ❌ 缓存过期没注意 | 隔了 10 分钟再请求，缓存没了 | 在 Agent 循环里保持请求频率；必要时手动刷新缓存 |
| ❌ 首次请求的写入溢价没预算 | 切换 prompt 后首请求成本突增 25% | 在成本预估中计入写入溢价 |
| ❌ 不同用户共享缓存？ | 以为多租户能共享缓存 | 缓存按 API key 隔离（通常），不同 key 不共享 |
| ❌ system prompt 在不同对话间微调 | 只改了 1 个字，整个缓存失效 | System prompt 尽量模板化，变量用模板替换 |

---

## Day 05 检查清单

- [ ] 理解 Prompt Caching 的前缀匹配机制
- [ ] 知道缓存写入和读取的计费差异（写入 +25%，读取 -90%）
- [ ] 理解缓存的生命周期（5 分钟过期）
- [ ] 能设计 cache-friendly 的 prompt 结构
- [ ] 会使用 cache_breakpoint 标记缓存点
- [ ] 能为多轮对话设计缓存策略
- [ ] 能监控缓存命中率和成本节省
- [ ] 能计算缓存在第几次请求后开始回本

---

## 副线：Claude Code 实战

### 今天的任务：观察 Claude Code 的缓存行为

Claude Code 在长对话中大量使用 Prompt Caching。今天观察：

1. 开一个新对话，写一个简短的 CLAUDE.md（~500 字）
2. 连续问 5 个不同的问题，观察回复速度有没有变化
3. 每次回复后查看 token 信息（看有没有 cache_read 数据）
4. 思考：CLAUDE.md 为什么在缓存里？它放在 prompt 的什么位置？

### CLI Agent 认知笔记

```
Claude Code 哪些内容被缓存了（推测）：____________________
缓存对长对话的影响：____________________
你的项目里哪些内容最适合放缓存：____________________
```

---

## 明天计划

- [ ] Day 06 — Prompt Caching 实战：System Prompt 缓存策略、cache breakpoints 深入、缓存命中率监控与优化
