# Day 06 — Prompt Caching 实战

## 学习目标

在 Day 05 的理论基础上进行实战，实现 System Prompt 缓存策略、多层级 cache breakpoints、缓存命中率实时监控，以及对比有/无缓存的成本和延迟差异。

---

## 一、System Prompt 缓存策略实战

### 1.1 单层缓存 vs 多层缓存

```
单层缓存（只缓存 System Prompt）：
┌──────────────────────────────────────────────────────┐
│ [System Prompt — cached] │ [History] │ [New Message] │
└──────────────────────────────────────────────────────┘
  每次命中 ~2K tokens      每次重新计算

多层缓存（System + Tools + 固定上下文）：
┌──────────────────────────────────────────────────────────────┐
│ [System — cached] │ [Tools — cached] │ [Docs — cached] │ [...] │
└──────────────────────────────────────────────────────────────┘
  每次命中 ~5-10K tokens → 节省更多
```

### 1.2 实现多层缓存结构

```python
"""多层缓存 prompt 构建器"""
import json
from typing import Any

class LayeredPromptBuilder:
    """构建带多层缓存标记的 messages 列表"""

    def __init__(self):
        self._layers: list[dict] = []

    def add_cached_layer(self, role: str, content: str) -> "LayeredPromptBuilder":
        """添加一个缓存层（放在前面，会被缓存）"""
        self._layers.append({
            "role": role,
            "content": [{
                "type": "text",
                "text": content,
                "cache_control": {"type": "ephemeral"}
            }]
        })
        return self

    def add_dynamic_layer(self, role: str, content: str) -> "LayeredPromptBuilder":
        """添加动态层（不标记缓存）"""
        self._layers.append({
            "role": role,
            "content": content
        })
        return self

    def build(self, user_message: str) -> list[dict]:
        """构建最终的 messages"""
        return self._layers + [
            {"role": "user", "content": user_message}
        ]

# Agent 应用示例
class AgentCacheSetup:
    def __init__(self):
        self.builder = LayeredPromptBuilder()

        # Layer 1: System Prompt（几乎不变 → 缓存）
        self.builder.add_cached_layer("system", """You are a caregiving AI assistant.
Your role is to help caregivers record and analyze elderly care data.
Always respond in Chinese. Be professional and empathetic.""")

        # Layer 2: Tool Definitions（系统启动时确定 → 缓存）
        tools_json = json.dumps([
            {"name": "log_care_activity", "description": "记录照护活动"},
            {"name": "query_elder_info", "description": "查询老人信息"},
            {"name": "analyze_health_trend", "description": "分析健康趋势"},
        ], ensure_ascii=False)
        self.builder.add_cached_layer("system", f"## 可用工具\n{tools_json}")

        # Layer 3: 知识库片段（按需注入，会话期间不变 → 缓存）
        self.knowledge_layer_idx: int | None = None

    def set_knowledge(self, knowledge: str):
        """设置知识库上下文（会触发缓存重建）"""
        self.builder.add_cached_layer("user",
            f"## 参考知识\n以下信息来自机构知识库，请参考回答问题：\n\n{knowledge}")

    def build_chat(self, history: list[dict], user_msg: str) -> list[dict]:
        """构建一次对话的消息"""
        messages = list(self.builder._layers)  # 缓存层
        messages.extend(history[-10:])         # 历史（动态）
        messages.append({"role": "user", "content": user_msg})
        return messages
```

---

## 二、Cache Breakpoints 深入

### 2.1 单请求多个 breakpoint

```python
"""
一个请求中可以设置多个 cache breakpoints：

请求结构:
  [Block 1: System Prompt]   ← breakpoint 1 (独立缓存)
  [Block 2: Tool Defs]       ← breakpoint 2 (独立缓存)
  [Block 3: Context Docs]    ← breakpoint 3 (独立缓存)
  [Block 4: Chat History]    ← 不缓存（每次变）
  [Block 5: User Message]    ← 不缓存（每次变）

好处：
  如果下次请求只改了 Context Docs，前两个 block 仍然命中
  如果下次请求换了 Tool Defs，至少 System Prompt 还能命中
"""

def build_with_breakpoints(
    system: str,
    tools: str,
    docs: str,
    history: list[dict],
    user_msg: str,
) -> list[dict]:
    return [
        # 独立缓存层 1
        {"role": "system", "content": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]},
        # 独立缓存层 2
        {"role": "system", "content": [
            {"type": "text", "text": f"## Tools\n{tools}", "cache_control": {"type": "ephemeral"}}
        ]},
        # 独立缓存层 3
        {"role": "user", "content": [
            {"type": "text", "text": f"## Reference\n{docs}", "cache_control": {"type": "ephemeral"}}
        ]},
        # 动态层
        *history,
        {"role": "user", "content": user_msg},
    ]
```

### 2.2 缓存层越多越好吗？

```
并非！每个 breakpoint 都有代价：

优点                          缺点
────────────────────────────────────────────
精细控制缓存粒度               增加 prompt 复杂度
单层失效不影响其他层           每层额外的格式开销（~10 tokens/breakpoint）
可以独立更新某一层             太多层 → 管理成本上升

推荐：3~5 个缓存层（system / tools / docs / examples / guidelines）
超过 5 层 → 边际收益递减
```

### 2.3 缓存验证脚本

```python
"""验证缓存配置是否按预期工作"""
import asyncio
import httpx
import json
import os

async def verify_cache_behavior():
    """发送两次请求，检查缓存是否正确命中"""
    headers = {
        "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    # 构建带缓存的 messages
    messages = build_with_breakpoints(
        system="You are a math tutor.",
        tools="[tool: calculator, solver]",
        docs="Pi ≈ 3.14159, e ≈ 2.71828",
        history=[],
        user_msg="What is pi?",
    )

    async with httpx.AsyncClient(timeout=60) as client:
        # 第一次请求（写入缓存）
        resp1 = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 200,
                "messages": messages,
            },
        )
        d1 = resp1.json()
        usage1 = d1["usage"]
        print(f"请求 1 (写缓存): write={usage1.get('cache_creation_input_tokens', 0)}, "
              f"read={usage1.get('cache_read_input_tokens', 0)}")

        # 等待 1 秒
        await asyncio.sleep(1)

        # 第二次请求（相同前缀 → 应命中缓存）
        messages2 = build_with_breakpoints(
            system="You are a math tutor.",       # 和上次一样
            tools="[tool: calculator, solver]",   # 和上次一样
            docs="Pi ≈ 3.14159, e ≈ 2.71828",    # 和上次一样
            history=[],
            user_msg="What is e?",                # 不同的问题
        )

        resp2 = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 200,
                "messages": messages2,
            },
        )
        d2 = resp2.json()
        usage2 = d2["usage"]
        print(f"请求 2 (读缓存): write={usage2.get('cache_creation_input_tokens', 0)}, "
              f"read={usage2.get('cache_read_input_tokens', 0)}")

        # 验证
        cache_read = usage2.get("cache_read_input_tokens", 0)
        if cache_read > 0:
            print(f"\n✅ 缓存生效！命中 {cache_read} tokens")
        else:
            print(f"\n❌ 缓存未命中，检查：前缀是否完全相同？")

# asyncio.run(verify_cache_behavior())
```

---

## 三、多轮对话中的缓存优化

### 3.1 对话历史的缓存困境

```
问题：对话历史每轮都在变，怎么缓存？

第 1 轮: [System-cached][Q1][A1]
第 2 轮: [System-cached][Q1][A1][Q2][A2]
第 3 轮: [System-cached][Q1][A1][Q2][A2][Q3][A3]
         ↑ 前缀匹配！Q1A1 可以缓存
第 4 轮: [System-cached][summary][Q3][A3][Q4]
         ↑ 如果做了摘要，前缀变了，缓存失效

策略：不要把历史直接放 system prompt 前面！
     System prompt → 永远在最前面（缓存锚点）
     History → system 之后（前缀仍然从 system 匹配）
```

### 3.2 滑动窗口 + 缓存

```python
class SlidingWindowWithCache:
    """滑动窗口 + 缓存的组合策略"""

    def __init__(self, system_prompt: str, tools: str, window_size: int = 10):
        self.system_messages = LayeredPromptBuilder() \
            .add_cached_layer("system", system_prompt) \
            .add_cached_layer("system", f"## Tools\n{tools}") \
            ._layers
        self.window_size = window_size
        self.full_history: list[dict] = []

    def add_turn(self, user_msg: str, assistant_msg: str):
        self.full_history.append({"role": "user", "content": user_msg})
        self.full_history.append({"role": "assistant", "content": assistant_msg})

    def build_for_next_request(self, new_user_msg: str) -> list[dict]:
        # 只取窗口内的历史
        recent = self.full_history[-(self.window_size * 2):]
        return self.system_messages + recent + [
            {"role": "user", "content": new_user_msg}
        ]

    def should_cache_recent(self) -> bool:
        """判断最近的历史是否稳定到值得缓存"""
        # 如果最近 4 条消息在下一轮还在窗口内，可以标记缓存
        return len(self.full_history) >= 8
```

---

## 四、缓存命中率实时监控

### 4.1 完整的缓存监控器

```python
"""实时缓存监控面板"""
from dataclasses import dataclass, field
from collections import deque
import time

@dataclass
class CacheMonitor:
    """实时缓存监控器 —— 在生产环境中使用"""

    pricing: CachePricing = field(default_factory=lambda: CachePricing(3, 3.75, 0.3, 15))

    # 统计
    requests: int = 0
    total_input: int = 0
    total_cache_write: int = 0
    total_cache_read: int = 0
    total_output: int = 0
    total_cost: float = 0.0
    estimated_no_cache_cost: float = 0.0

    # 滑动窗口（最近 20 次）
    recent_hit_rates: deque[float] = field(default_factory=lambda: deque(maxlen=20))

    def record(self, usage: dict):
        self.requests += 1
        input_t = usage.get("input_tokens", 0)
        write_t = usage.get("cache_creation_input_tokens", 0)
        read_t = usage.get("cache_read_input_tokens", 0)
        output_t = usage.get("output_tokens", 0)

        self.total_input += input_t
        self.total_cache_write += write_t
        self.total_cache_read += read_t
        self.total_output += output_t

        # 计算成本
        normal_input = input_t - write_t - read_t
        cost = (
            normal_input / 1_000_000 * self.pricing.input_per_1m +
            write_t / 1_000_000 * self.pricing.cache_write_per_1m +
            read_t / 1_000_000 * self.pricing.cache_read_per_1m +
            output_t / 1_000_000 * self.pricing.output_per_1m
        )
        no_cache_cost = input_t / 1_000_000 * self.pricing.input_per_1m + \
                        output_t / 1_000_000 * self.pricing.output_per_1m

        self.total_cost += cost
        self.estimated_no_cache_cost += no_cache_cost

        # 滑动命中率
        hit_rate = read_t / input_t if input_t > 0 else 0
        self.recent_hit_rates.append(hit_rate)

    @property
    def overall_hit_rate(self) -> float:
        return self.total_cache_read / self.total_input if self.total_input > 0 else 0

    @property
    def recent_avg_hit_rate(self) -> float:
        if not self.recent_hit_rates:
            return 0.0
        return sum(self.recent_hit_rates) / len(self.recent_hit_rates)

    @property
    def total_saved(self) -> float:
        return self.estimated_no_cache_cost - self.total_cost

    def health_check(self) -> dict:
        """返回缓存健康状态"""
        recent = self.recent_avg_hit_rate
        overall = self.overall_hit_rate

        if recent < 0.1:
            status = "critical"   # 缓存基本没命中
        elif recent < 0.3:
            status = "warning"    # 命中率偏低
        elif recent < 0.6:
            status = "ok"         # 可以接受
        else:
            status = "great"      # 缓存优化很好

        return {
            "status": status,
            "overall_hit_rate": overall,
            "recent_hit_rate": recent,
            "total_saved": self.total_saved,
            "saved_pct": (self.total_saved / self.estimated_no_cache_cost * 100)
                          if self.estimated_no_cache_cost > 0 else 0,
        }

    def print_report(self):
        h = self.health_check()
        print(f"""
╔══════════════════════════════════════╗
║        Cache Health Report          ║
╠══════════════════════════════════════╣
║ Status:        {h['status']:<10}          ║
║ Requests:      {self.requests:<10}          ║
║ Overall Hit:   {h['overall_hit_rate']:>8.1%}            ║
║ Recent Hit:    {h['recent_hit_rate']:>8.1%}            ║
║ Total Cost:    ${self.total_cost:<10.4f}         ║
║ Total Saved:   ${h['total_saved']:<10.4f}         ║
║ Saved %:       {h['saved_pct']:>8.1f}%           ║
╚══════════════════════════════════════╝
""")
```

### 4.2 在 FastAPI 中暴露监控端点

```python
from fastapi import FastAPI

app = FastAPI()
monitor = CacheMonitor()

@app.get("/api/v1/admin/cache-stats")
async def cache_stats():
    return monitor.health_check()

@app.get("/api/v1/admin/cache-report")
async def cache_report():
    return {
        "requests": monitor.requests,
        "overall_hit_rate": monitor.overall_hit_rate,
        "recent_hit_rates": list(monitor.recent_hit_rates),
        "total_cost": round(monitor.total_cost, 6),
        "total_saved": round(monitor.total_saved, 6),
    }
```

---

## 五、有缓存 vs 无缓存：完整对比实验

### 5.1 端到端对比

```python
"""完整对比：缓存 ON vs OFF"""
import asyncio
import httpx
import time
import os

async def compare_cache_vs_nocache(
    system_prompt: str,
    test_questions: list[str],
    model: str = "claude-sonnet-4-6",
):
    """用同一组问题测试缓存效果"""
    headers = {
        "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    # 方案 A：不带缓存（所有内容当普通 input）
    async def run_without_cache():
        results = []
        async with httpx.AsyncClient(timeout=60) as client:
            for q in test_questions:
                t0 = time.time()
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json={
                        "model": model,
                        "max_tokens": 200,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": q},
                        ],
                    },
                )
                elapsed = time.time() - t0
                data = resp.json()
                results.append({
                    "question": q[:30],
                    "elapsed": elapsed,
                    "input_tokens": data["usage"]["input_tokens"],
                    "output_tokens": data["usage"]["output_tokens"],
                })
        return results

    # 方案 B：带缓存（system prompt 标记 cache_control）
    async def run_with_cache():
        results = []
        async with httpx.AsyncClient(timeout=60) as client:
            for q in test_questions:
                t0 = time.time()
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json={
                        "model": model,
                        "max_tokens": 200,
                        "messages": [
                            {"role": "system", "content": [
                                {"type": "text", "text": system_prompt,
                                 "cache_control": {"type": "ephemeral"}}
                            ]},
                            {"role": "user", "content": q},
                        ],
                    },
                )
                elapsed = time.time() - t0
                data = resp.json()
                results.append({
                    "question": q[:30],
                    "elapsed": elapsed,
                    "input_tokens": data["usage"]["input_tokens"],
                    "cache_read": data["usage"].get("cache_read_input_tokens", 0),
                    "output_tokens": data["usage"]["output_tokens"],
                })
        return results

    print("=== 无缓存 ===")
    no_cache = await run_without_cache()
    for r in no_cache:
        print(f"  {r['question']}... → {r['elapsed']:.2f}s, {r['input_tokens']}t")

    # 等缓存过期
    await asyncio.sleep(1)

    print("\n=== 有缓存 ===")
    with_cache = await run_with_cache()
    for i, r in enumerate(with_cache):
        cache_tag = f", cache_read={r['cache_read']}t" if r['cache_read'] > 0 else ", 首次写入"
        print(f"  {r['question']}... → {r['elapsed']:.2f}s, {r['input_tokens']}t{cache_tag}")

    # 总结
    avg_no_cache = sum(r["elapsed"] for r in no_cache) / len(no_cache)
    avg_cache = sum(r["elapsed"] for r in with_cache) / len(with_cache)
    print(f"\n平均延迟: 无缓存 {avg_no_cache:.2f}s → 有缓存 {avg_cache:.2f}s")

# 运行实验
# system_prompt = "You are an expert Python programmer..." * 10  # 长 system prompt
# questions = ["What is a list?", "What is a dict?", "What is a set?", "What is a tuple?"]
# asyncio.run(compare_cache_vs_nocache(system_prompt, questions, "claude-haiku-4-5"))
```

---

## 六、今日练习（约 2.5 小时）

### 练习 1：实现多层缓存 Prompt 构建器（30 min）

完善 `LayeredPromptBuilder`：
1. 支持移除/更新某一层（如切换 tools）
2. 支持 `build_streaming()` 方法（返回 `messages` + 缓存元数据）
3. 写单元测试验证层的顺序正确

### 练习 2：缓存验证实验（25 min）

运行上面的 `compare_cache_vs_nocache` 实验，填表：

```
| 问题   | 无缓存延迟 | 有缓存延迟 | 缓存命中 token | 节省比例 |
|--------|-----------|-----------|---------------|---------|
| Q1     |           |           |               |         |
| Q2     |           |           |               |         |
| Q3     |           |           |               |         |
| Q4     |           |           |               |         |
```

### 练习 3：给 Agent 加缓存监控（40 min）

把 `CacheMonitor` 集成到你现有（或 Day 07 将要做的）的对话 API 中：
1. 每次 API 调用后调用 `monitor.record(usage)`
2. 添加 `/admin/cache-stats` 端点
3. 实现健康检查告警（命中率 < 10% 时打印 warning）

### 练习 4：缓存策略优化实验（30 min）

对比三种缓存策略的成本：
1. 无缓存
2. 只缓存 System Prompt
3. 缓存 System + Tools + Knowledge

用 100 次请求模拟，计算每种策略的总成本。

### 练习 5：缓存失效演练（25 min）

模拟 "System Prompt 更新导致缓存失效" 的场景：
1. 发送 10 次请求，建立缓存
2. 修改 System Prompt
3. 再发送 10 次请求
4. 对比缓存命中率的变化

---

## 七、踩坑记录

```
[ ] 坑 1：____________________
解决：____________________

[ ] 坑 2：____________________
解决：____________________
```

**常见坑预警：**

| 坑 | 表现 | 解决 |
|----|------|------|
| ❌ 动态变量放 system prompt 里 | 每次 system prompt 都不同，缓存全废 | system prompt 用模板，具体值通过 user message 传 |
| ❌ 以为缓存永不失效 | 测试间隔太久，缓存已过期 | 缓存 ~5 分钟，高频率请求时才明显 |
| ❌ 只关注缓存命中 token 数，不关注成本 | 写入溢价 25%，如果命中率低反而亏钱 | 用 CacheMonitor 追踪实际成本 |
| ❌ 开发和生产的缓存行为不同 | 开发时请求频率低，缓存总过期 | 生产环境才是验证缓存效果的真正场景 |
| ❌ 把 cache_control 放在非 content block 末尾 | 标记位置不对，缓存不生效 | cache_control 只能放在 text content block 里 |

---

## Day 06 检查清单

- [ ] 能实现多层缓存的 Prompt 结构
- [ ] 理解多个 cache_breakpoint 的独立缓存行为
- [ ] 能用验证脚本确认缓存是否命中
- [ ] 能在多轮对话中兼顾滑动窗口和缓存
- [ ] 能实现完整的 CacheMonitor 监控器
- [ ] 能在 FastAPI 中暴露缓存统计端点
- [ ] 能运行有/无缓存的端到端对比实验
- [ ] 知道缓存失效的触发条件和应对方式

---

## 副线：Claude Code 实战

### 今天的任务：分析 Claude Code 的缓存设计

回顾这 6 天的学习，思考 Claude Code 是怎么用缓存的：

1. CLAUDE.md 的内容放哪里？为什么放那个位置？
2. 对话变长后，Claude Code 的回复速度有变化吗？为什么？
3. 如果你给 Claude Code 设计缓存策略，你会怎么优化？

### CLI Agent 认知笔记

```
Claude Code 最可能的缓存结构（推测）：____________________
长对话中的速度变化观察：____________________
如果我来设计，会改进的地方：____________________
```

---

## 明天计划

- [ ] Day 07 — 综合产出：对话 API 封装（流式 + 缓存 + 重试），串联 Week 02 全部知识点
