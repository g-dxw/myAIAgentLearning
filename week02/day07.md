# Day 07 — 产出：对话 API 封装（流式 + 缓存 + 重试）

## 产出目标

构建一个完整的 **LLM 对话 API 封装类**，串联 Week 02 全部知识点：Token 管理、Context Window、Thinking、Streaming、Prompt Caching。这个封装类将成为你所有 Agent 项目的 LLM 调用基础设施。

---

## 项目定位

```
一个生产级的 Claude API 封装，支持：
- 流式 + 非流式两种对话模式
- 自动 Prompt Caching（多层缓存标记）
- Token 预算管理和自动裁剪
- 指数退避重试（网络错误、限流）
- Thinking / Effort 参数控制
- 完整的 Token 和成本统计
- 可配置的系统提示和工具定义
```

**做完这个，你后续所有的 Agent 项目都可以直接 import 这个封装类来调 LLM。** 不需要每次都写一遍 `httpx.post + headers + json`。

---

## 项目结构

```
week02/
├── day01.md ~ day06.md     # 每日学习笔记
├── day07/
│   ├── llm_client.py       # 核心：LLM 对话 API 封装类
│   ├── cache_manager.py    # 缓存策略管理
│   ├── token_budget.py     # Token 预算管理
│   ├── stream_parser.py    # 流式事件解析器
│   ├── retry.py            # 重试策略
│   ├── cost_tracker.py     # 成本追踪
│   ├── example_basic.py    # 示例：基本对话
│   ├── example_stream.py   # 示例：流式对话
│   └── example_agent.py    # 示例：Agent 循环
```

---

## 第一阶段：核心 API 封装类（45 min）

### `llm_client.py` — 主类

```python
"""
LLM 对话 API 封装 — 生产级
支持：流式/非流式、自动缓存、Token 管理、重试、成本追踪
"""
import asyncio
import httpx
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal, Callable, AsyncGenerator
from collections.abc import AsyncGenerator as AsyncGen

# ==========================================
# 数据模型
# ==========================================

@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

@dataclass
class LLMResponse:
    """LLM 调用的完整响应"""
    id: str
    model: str
    content: list[dict]
    text: str                     # 纯文本提取
    thinking: str = ""            # 思考内容（如有）
    tool_calls: list[dict] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    stop_reason: str = ""
    elapsed_ms: float = 0
    cost_usd: float = 0.0


# ==========================================
# 定价表
# ==========================================

MODEL_PRICING = {
    # model: (input, cache_write, cache_read, output)  per 1M tokens
    "claude-opus-4-7":   (15.0, 18.75, 1.50, 75.0),
    "claude-sonnet-4-6": (3.0,  3.75,  0.30, 15.0),
    "claude-haiku-4-5":  (1.0,  1.25,  0.10, 5.0),
}


# ==========================================
# 主类
# ==========================================

class LLMClient:
    """Claude API 封装客户端"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com/v1",
        default_model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        system_prompt: str = "",
        tools: list[dict] | None = None,
        thinking_budget: int = 0,    # 0 = 不开 thinking
        max_retries: int = 3,
        cache_enabled: bool = True,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.base_url = base_url
        self.default_model = default_model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.thinking_budget = thinking_budget
        self.max_retries = max_retries
        self.cache_enabled = cache_enabled
        self.timeout = timeout

        # 统计
        self.total_requests: int = 0
        self.total_cost: float = 0.0
        self.total_tokens: LLMUsage = field(default_factory=LLMUsage)

        # HTTP 客户端（延迟创建）
        self._client: httpx.AsyncClient | None = None

    # ==========================================
    # 构建请求
    # ==========================================

    def _build_messages(
        self,
        user_message: str,
        history: list[dict] | None = None,
    ) -> list[dict]:
        """构建带缓存标记的 messages"""
        messages = []

        # Layer 1: System Prompt（缓存锚点）
        if self.system_prompt:
            if self.cache_enabled:
                messages.append({
                    "role": "system",
                    "content": [{
                        "type": "text",
                        "text": self.system_prompt,
                        "cache_control": {"type": "ephemeral"}
                    }]
                })
            else:
                messages.append({"role": "system", "content": self.system_prompt})

        # Layer 2: Tool Definitions（缓存层）
        if self.tools:
            tools_text = json.dumps(self.tools, ensure_ascii=False)
            # tools 不在 messages 里，在顶层 tools 参数里传
            # 但如果你想把工具说明放在 prompt 里也可以

        # Layer 3: 对话历史（动态）
        if history:
            messages.extend(history)

        # Layer 4: 当前消息（动态）
        messages.append({"role": "user", "content": user_message})

        return messages

    def _build_body(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int,
        stream: bool,
    ) -> dict:
        """构建 API 请求体"""
        body: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        if stream:
            body["stream"] = True

        if self.tools:
            body["tools"] = self.tools

        if self.thinking_budget > 0:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget,
            }

        return body

    # ==========================================
    # HTTP 客户端管理
    # ==========================================

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ==========================================
    # 非流式调用
    # ==========================================

    async def chat(
        self,
        user_message: str,
        history: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """非流式对话"""
        messages = self._build_messages(user_message, history)
        body = self._build_body(
            messages,
            model or self.default_model,
            max_tokens or self.max_tokens,
            stream=False,
        )

        t0 = time.time()
        client = await self._get_client()

        # 带重试的请求
        resp_data = await self._request_with_retry(
            "POST", "/messages", json=body
        )

        elapsed = (time.time() - t0) * 1000
        return self._parse_response(resp_data, elapsed)

    # ==========================================
    # 流式调用
    # ==========================================

    async def chat_stream(
        self,
        user_message: str,
        history: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        on_text: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
        on_tool_call: Callable[[dict], None] | None = None,
    ) -> LLMResponse:
        """流式对话，支持回调"""
        from stream_parser import StreamParser  # Day 04 的实现

        messages = self._build_messages(user_message, history)
        body = self._build_body(
            messages,
            model or self.default_model,
            max_tokens or self.max_tokens,
            stream=True,
        )

        parser = StreamParser()
        t0 = time.time()
        client = await self._get_client()

        async with client.stream("POST", "/messages", json=body) as resp:
            if resp.status_code != 200:
                error_text = await resp.aread()
                raise LLMError(resp.status_code, error_text.decode()[:500])

            async for line in resp.aiter_lines():
                event = parser.feed(line)
                if event is None:
                    continue

                if event["type"] == "text" and on_text:
                    on_text(event["content"])
                elif event["type"] == "thinking" and on_thinking:
                    on_thinking(event["content"])
                elif event["type"] == "tool_use" and on_tool_call:
                    on_tool_call(event["tool"])

        elapsed = (time.time() - t0) * 1000

        return LLMResponse(
            id=str(uuid.uuid4()),
            model=model or self.default_model,
            content=[{"type": "text", "text": parser.text}],
            text=parser.text,
            thinking=parser.thinking,
            tool_calls=parser.tool_uses,
            usage=LLMUsage(
                input_tokens=parser.input_tokens,
                output_tokens=parser.output_tokens,
            ),
            stop_reason=parser.stop_reason,
            elapsed_ms=elapsed,
            cost_usd=self._estimate_cost(
                model or self.default_model,
                parser.input_tokens,
                parser.output_tokens,
            ),
        )

    # ==========================================
    # 重试机制
    # ==========================================

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> dict:
        """指数退避重试"""
        client = await self._get_client()
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = await client.request(method, path, **kwargs)

                if resp.status_code == 200:
                    self.total_requests += 1
                    return resp.json()

                # 可重试的错误
                if resp.status_code in (429, 503, 502):
                    if attempt < self.max_retries:
                        wait = 2 ** attempt  # 1s, 2s, 4s...
                        print(f"[Retry] {resp.status_code}, wait {wait}s (attempt {attempt+1}/{self.max_retries})")
                        await asyncio.sleep(wait)
                        continue

                error_body = ""
                try:
                    error_body = resp.text[:500]
                except Exception:
                    pass
                raise LLMError(resp.status_code, error_body)

            except httpx.TimeoutException as e:
                if attempt < self.max_retries:
                    wait = 2 ** attempt
                    print(f"[Retry] Timeout, wait {wait}s (attempt {attempt+1}/{self.max_retries})")
                    await asyncio.sleep(wait)
                    continue
                raise LLMError(408, str(e))

        raise LLMError(500, f"Max retries ({self.max_retries}) exceeded. Last error: {last_error}")

    # ==========================================
    # 响应解析
    # ==========================================

    def _parse_response(self, data: dict, elapsed_ms: float) -> LLMResponse:
        """解析非流式响应"""
        content = data.get("content", [])
        text = ""
        thinking = ""
        tool_calls = []

        for block in content:
            if block["type"] == "text":
                text += block["text"]
            elif block["type"] == "thinking":
                thinking += block["thinking"]
            elif block["type"] == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "name": block["name"],
                    "input": block["input"],
                })

        usage_raw = data.get("usage", {})
        usage = LLMUsage(
            input_tokens=usage_raw.get("input_tokens", 0),
            output_tokens=usage_raw.get("output_tokens", 0),
            cache_write_tokens=usage_raw.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage_raw.get("cache_read_input_tokens", 0),
        )

        model = data.get("model", "")
        cost = self._estimate_cost(
            model, usage.input_tokens, usage.output_tokens,
            usage.cache_write_tokens, usage.cache_read_tokens,
        )

        # 累计统计
        self.total_tokens.input_tokens += usage.input_tokens
        self.total_tokens.output_tokens += usage.output_tokens
        self.total_cost += cost

        return LLMResponse(
            id=data.get("id", ""),
            model=model,
            content=content,
            text=text.strip(),
            thinking=thinking,
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=data.get("stop_reason", ""),
            elapsed_ms=elapsed_ms,
            cost_usd=cost,
        )

    # ==========================================
    # 成本估算
    # ==========================================

    def _estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_write: int = 0,
        cache_read: int = 0,
    ) -> float:
        """估算本次调用成本"""
        pricing = MODEL_PRICING.get(model)
        if not pricing:
            # 尝试模糊匹配
            for key in MODEL_PRICING:
                if key in model or model in key:
                    pricing = MODEL_PRICING[key]
                    break
        if not pricing:
            # Unknown model, use sonnet pricing as default
            pricing = MODEL_PRICING["claude-sonnet-4-6"]

        input_price, write_price, read_price, output_price = pricing

        normal_input = input_tokens - cache_write - cache_read

        return (
            normal_input / 1_000_000 * input_price +
            cache_write / 1_000_000 * write_price +
            cache_read / 1_000_000 * read_price +
            output_tokens / 1_000_000 * output_price
        )

    # ==========================================
    # 统计
    # ==========================================

    def stats(self) -> dict:
        return {
            "requests": self.total_requests,
            "total_input_tokens": self.total_tokens.input_tokens,
            "total_output_tokens": self.total_tokens.output_tokens,
            "total_cost_usd": round(self.total_cost, 6),
        }

    def print_stats(self):
        s = self.stats()
        print(f"[LLM] {s['requests']} requests | "
              f"{s['total_input_tokens']:,}→{s['total_output_tokens']:,} tokens | "
              f"${s['total_cost_usd']:.4f}")


# ==========================================
# 异常
# ==========================================

class LLMError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"LLM Error {status_code}: {detail[:200]}")
```

---

## 第二阶段：辅助模块（30 min）

### `stream_parser.py`

```python
"""流式事件解析器（来自 Day 04，集成到客户端）"""
import json
from dataclasses import dataclass, field

@dataclass
class StreamParser:
    text: str = ""
    thinking: str = ""
    tool_uses: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    _blocks: dict[int, dict] = field(default_factory=dict)

    def feed(self, line: str) -> dict | None:
        if not line.startswith("data: "):
            return None
        event = json.loads(line[6:])
        event_type = event.get("type")

        if event_type == "message_start":
            self.input_tokens = event["message"]["usage"]["input_tokens"]

        elif event_type == "content_block_start":
            idx = event["index"]
            block = event["content_block"]
            self._blocks[idx] = {
                "type": block["type"],
                "text": block.get("text", ""),
                "thinking": block.get("thinking", ""),
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "input_json": "",
            }

        elif event_type == "content_block_delta":
            idx = event["index"]
            delta = event["delta"]
            block = self._blocks.get(idx, {})

            if delta["type"] == "text_delta":
                new_text = delta["text"]
                block["text"] = block.get("text", "") + new_text
                self.text += new_text
                return {"type": "text", "content": new_text}

            elif delta["type"] == "thinking_delta":
                new_think = delta["thinking"]
                block["thinking"] = block.get("thinking", "") + new_think
                self.thinking += new_think
                return {"type": "thinking", "content": new_think}

            elif delta["type"] == "input_json_delta":
                block["input_json"] = block.get("input_json", "") + delta["partial_json"]

        elif event_type == "content_block_stop":
            idx = event["index"]
            block = self._blocks.get(idx, {})
            if block.get("type") == "tool_use":
                try:
                    tool = {
                        "id": block["id"],
                        "name": block["name"],
                        "input": json.loads(block["input_json"]) if block["input_json"] else {},
                    }
                except json.JSONDecodeError:
                    tool = {"id": block["id"], "name": block["name"], "input": {}}
                self.tool_uses.append(tool)
                return {"type": "tool_use", "tool": tool}

        elif event_type == "message_delta":
            self.output_tokens = event.get("usage", {}).get("output_tokens", 0)
            self.stop_reason = event["delta"].get("stop_reason", "")

        elif event_type == "message_stop":
            return {"type": "done"}

        return None
```

### `retry.py`

```python
"""指数退避重试装饰器"""
import asyncio
import functools
from typing import TypeVar, Callable

T = TypeVar("T")

class RetryConfig:
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        retryable_statuses: tuple[int, ...] = (429, 502, 503, 504),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.retryable_statuses = retryable_statuses

def async_retry(config: RetryConfig | None = None):
    """指数退避重试装饰器"""
    cfg = config or RetryConfig()

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(cfg.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except LLMError as e:
                    if e.status_code in cfg.retryable_statuses and attempt < cfg.max_retries:
                        delay = min(cfg.base_delay * (cfg.backoff_factor ** attempt), cfg.max_delay)
                        print(f"[Retry] {e.status_code}, waiting {delay:.1f}s (attempt {attempt+1})")
                        await asyncio.sleep(delay)
                        continue
                    raise
                except httpx.TimeoutException as e:
                    if attempt < cfg.max_retries:
                        delay = min(cfg.base_delay * (cfg.backoff_factor ** attempt), cfg.max_delay)
                        print(f"[Retry] Timeout, waiting {delay:.1f}s (attempt {attempt+1})")
                        await asyncio.sleep(delay)
                        continue
                    raise
            raise last_error  # type: ignore
        return wrapper
    return decorator
```

---

## 第三阶段：使用示例（20 min）

### `example_basic.py`

```python
"""示例：基本对话"""
import asyncio
from llm_client import LLMClient

async def main():
    client = LLMClient(
        system_prompt="You are a helpful Python assistant. Answer in Chinese.",
        default_model="claude-haiku-4-5",
        max_tokens=500,
    )

    # 非流式对话
    resp = await client.chat("什么是 Python 装饰器？用简单的话解释")

    print(f"回复: {resp.text}")
    print(f"Token: {resp.usage.input_tokens}→{resp.usage.output_tokens}")
    print(f"耗时: {resp.elapsed_ms:.0f}ms")
    print(f"成本: ${resp.cost_usd:.6f}")

    client.print_stats()
    await client.close()

# asyncio.run(main())
```

### `example_stream.py`

```python
"""示例：流式对话"""
import asyncio
from llm_client import LLMClient

async def main():
    client = LLMClient(
        system_prompt="You are a creative writing assistant.",
        default_model="claude-haiku-4-5",
        max_tokens=300,
        thinking_budget=500,  # 开启 thinking
    )

    print("流式回复: ", end="", flush=True)

    resp = await client.chat_stream(
        "写一首关于编程的短诗",
        on_text=lambda t: print(t, end="", flush=True),
    )

    print(f"\n\n--- 统计 ---")
    print(f"总 Token: {resp.usage.input_tokens}→{resp.usage.output_tokens}")
    print(f"Thinking: {len(resp.thinking)} 字符")
    print(f"耗时: {resp.elapsed_ms:.0f}ms")
    print(f"成本: ${resp.cost_usd:.6f}")

    await client.close()

# asyncio.run(main())
```

### `example_agent.py`

```python
"""示例：Agent 主循环"""
import asyncio
from llm_client import LLMClient, LLMResponse

# 模拟工具
async def get_weather(city: str) -> str:
    return f"{city}今天晴，22°C，湿度 45%"

async def get_time(timezone: str) -> str:
    return f"{timezone}当前时间: 2026-05-19 14:30:00"

TOOLS_MAP = {
    "get_weather": get_weather,
    "get_time": get_time,
}

async def agent_loop(client: LLMClient, user_message: str, history: list[dict]):
    """简单的 Agent 循环：调用 LLM → 执行工具 → 继续循环"""
    resp = await client.chat(user_message, history=history)

    if resp.tool_calls:
        # 执行工具
        tool_results = []
        for tc in resp.tool_calls:
            fn = TOOLS_MAP.get(tc["name"])
            if fn:
                result = await fn(**tc["input"])
                tool_results.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": result,
                    }]
                })

        # 递归：把工具结果发给 LLM 继续
        new_history = history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": resp.content},
        ] + tool_results

        return await agent_loop(client, "", new_history)

    return resp


async def main():
    client = LLMClient(
        system_prompt="You are a helpful assistant with access to weather and time tools.",
        tools=[
            {
                "name": "get_weather",
                "description": "Get weather for a city",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
            {
                "name": "get_time",
                "description": "Get current time for a timezone",
                "input_schema": {
                    "type": "object",
                    "properties": {"timezone": {"type": "string"}},
                    "required": ["timezone"],
                },
            },
        ],
        thinking_budget=1000,
    )

    resp = await agent_loop(client, "北京今天天气怎么样？现在几点了？", [])

    print(f"最终回复: {resp.text}")
    print(f"工具调用: {resp.tool_calls}")
    client.print_stats()

    await client.close()

# asyncio.run(main())
```

---

## 第四阶段：测试验证（20 min）

### 检查清单

```bash
# 1. 基本对话
python example_basic.py
# 预期：正常返回中文回复，打印 token 和成本

# 2. 流式对话
python example_stream.py
# 预期：逐字输出，最后打印统计（含 thinking）

# 3. Agent 循环
python example_agent.py
# 预期：自动调用工具，最终回复包含天气和时间

# 4. 缓存验证
# 连续调 example_basic.py 两次，第一次有 cache_write，第二次有 cache_read

# 5. 重试验证
# 设置 max_retries=3，断开网络后运行，观察重试日志

# 6. 成本验证
# 查看 stats 输出，对比 Anthropic Console 的 usage
```

---

## 本周总结

### Week 02 知识地图

```
LLM 原理
├── Token 机制（Day 01）
│   ├── Token 的定义和切分原理
│   ├── tiktoken 计算 token 数
│   ├── 中英文 token 差异
│   └── Token 与成本的关系
│
├── Context Window（Day 02）
│   ├── 上下文窗口限制
│   ├── 滑动窗口策略
│   ├── 摘要压缩策略
│   └── Token 预算管理
│
├── Thinking & Effort（Day 03）
│   ├── Thinking 机制原理
│   ├── Budget Tokens 参数
│   ├── Effort 级别选择
│   └── 成本权衡决策
│
├── Streaming（Day 04）
│   ├── SSE 协议原理
│   ├── 7 种事件类型解析
│   ├── 流式 Tool Use 处理
│   └── TTFT 优化
│
├── Prompt Caching（Day 05-06）
│   ├── 前缀匹配机制
│   ├── cache_breakpoint 标记
│   ├── 多层级缓存策略
│   └── 命中率监控
│
└── 产出（Day 07）
    └── LLMClient：流式 + 缓存 + 重试的完整封装
```

### 本周产出物

| 产出 | 位置 | 用途 |
|------|------|------|
| `LLMClient` | `day07/llm_client.py` | 所有 Agent 项目的 LLM 调用基础设施 |
| `StreamParser` | `day07/stream_parser.py` | 流式事件解析，可复用于任意 Claude API 项目 |
| `RetryConfig` | `day07/retry.py` | 指数退避重试，可复用于任意 HTTP API |
| `CacheMonitor` | Day 06 | 缓存监控，可用于生产环境调优 |
| `TokenBudget` | Day 02 | Token 预算管理，长对话必备 |

### 核心收获

- [ ] 理解了 Token 的本质和成本模型
- [ ] 掌握了 Context Window 的管理策略
- [ ] 能根据任务选择 Thinking/Effort 参数
- [ ] 能实现完整的流式事件解析
- [ ] 能设计 cache-friendly 的 prompt 结构
- [ ] 能封装生产级的 LLM 对话 API（流式 + 缓存 + 重试）

### 持续改进

这个 `LLMClient` 是你后续 Agent 项目的起点。之后每周你都会回来改进它：
- Week 03：添加 Tool Use 的自动化处理
- Week 04：添加 RAG 上下文注入
- Week 06：添加 LangGraph 状态管理
- Week 09：添加评测和回归测试

---

## 打卡模板

```markdown
## Day 07 打卡

### 完成了什么
- [ ] LLMClient 核心类
- [ ] StreamParser 集成
- [ ] 重试机制
- [ ] 缓存策略
- [ ] 示例代码

### 遇到了什么问题
（记录今天写代码遇到的具体问题）

### 代码位置
- `week02/day07/llm_client.py`
- `week02/day07/stream_parser.py`
- `week02/day07/retry.py`
- `week02/day07/example_*.py`

### 本周总结
（这周学 LLM 原理最大的收获是什么？哪个概念之前理解错了？）
```
