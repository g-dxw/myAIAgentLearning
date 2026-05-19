# Day 04 — Streaming 深入 & 事件类型完整解析

## 学习目标

深入理解 Claude API 的流式（Streaming）机制，完整掌握所有 SSE 事件类型及其处理方式，能实现流式环境下正确处理 text、thinking、tool_use 的完整解析器。

---

## 一、流式 vs 非流式 —— 延迟差异

### 1.1 用户体验对比

```
非流式（等全部生成完）：
  用户发消息 ──────────────────────────────── 看到完整回复
              ↑                               ↑
             0s                            ~8s（500 字回复）
             用户盯着白屏/转圈，体验极差

流式（逐字返回）：
  用户发消息 ─── 看到"今"──"天"──"天"──...── 看到完整回复
              ↑    ↑        ↑                 ↑
             0s  ~0.5s    ~0.6s            ~8s
             用户立刻看到内容在"打字"，体验流畅
```

### 1.2 首字延迟（TTFT）

```
TTFT = Time To First Token

非流式 TTFT = 全部生成完的时间
流式 TTFT   = 第一个 token 的时间（通常 < 500ms）

对于 Agent 交互，TTFT 是用户感知延迟的唯一指标。
首字 500ms 内出现 = "很快"
首字 2s+ 出现    = "有点慢"
首字 5s+ 出现    = "是不是卡了？"
```

### 1.3 流式调用的基本代码

```python
"""Claude Streaming API 最简示例"""
import httpx
import json
import os

async def stream_chat(prompt: str):
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,   # ← 关键
            },
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                print(f"[事件] {event.get('type')}")

# asyncio.run(stream_chat("Hello!"))
```

---

## 二、SSE 事件类型完整解析

### 2.1 事件全景图

```
一次完整的流式响应由以下事件组成：

1. message_start     → 响应开始，含 usage 信息
2. ping              → 心跳包（保持连接）
3. content_block_start → 一个内容块开始（text/thinking/tool_use）
4. content_block_delta  → 内容块增量数据（可能有多个）
5. content_block_stop   → 内容块结束
   ... 重复 3-5 多次（每个 content block 一套）
6. message_delta     → 消息级增量（usage 更新、stop_reason）
7. message_stop      → 响应结束
```

### 2.2 每种事件的 JSON 结构

```python
# 1. message_start
{
    "type": "message_start",
    "message": {
        "id": "msg_xxx",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "usage": {"input_tokens": 25, "output_tokens": 0}
    }
}

# 2. content_block_start — text block
{
    "type": "content_block_start",
    "index": 0,
    "content_block": {
        "type": "text",
        "text": ""            # 初始为空，内容在 delta 中
    }
}

# 2b. content_block_start — thinking block
{
    "type": "content_block_start",
    "index": 0,
    "content_block": {
        "type": "thinking",
        "thinking": ""        # 初始为空
    }
}

# 2c. content_block_start — tool_use block
{
    "type": "content_block_start",
    "index": 0,
    "content_block": {
        "type": "tool_use",
        "id": "toolu_xxx",
        "name": "get_weather",
        "input": {}           # 初始为空，增量填充
    }
}

# 3. content_block_delta — text delta
{
    "type": "content_block_delta",
    "index": 0,
    "delta": {
        "type": "text_delta",
        "text": "今天"        # 增量文本
    }
}

# 3b. content_block_delta — thinking delta
{
    "type": "content_block_delta",
    "index": 0,
    "delta": {
        "type": "thinking_delta",
        "thinking": "我需要分析..."
    }
}

# 3c. content_block_delta — input_json_delta（tool_use）
{
    "type": "content_block_delta",
    "index": 0,
    "delta": {
        "type": "input_json_delta",
        "partial_json": "{\"city\": \"北京\"}"  # 增量 JSON
    }
}

# 4. content_block_stop
{
    "type": "content_block_stop",
    "index": 0
}

# 5. message_delta
{
    "type": "message_delta",
    "delta": {
        "stop_reason": "end_turn",
        "stop_sequence": None
    },
    "usage": {
        "output_tokens": 156   # 最终输出 token 数
    }
}

# 6. message_stop
{
    "type": "message_stop"
}

# 心跳
{
    "type": "ping"
}
```

### 2.3 完整的事件处理器

```python
"""流式事件完整处理器"""
import json
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class StreamContent:
    """流式响应收集器"""
    role: str = "assistant"
    text: str = ""
    thinking: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""

    # 内部状态
    _current_block_type: str = ""
    _current_tool_json: str = ""

    def feed_event(self, event: dict) -> None:
        """喂一个 SSE 事件进来"""
        event_type = event.get("type")

        if event_type == "message_start":
            usage = event.get("message", {}).get("usage", {})
            self.input_tokens = usage.get("input_tokens", 0)

        elif event_type == "content_block_start":
            block = event["content_block"]
            self._current_block_type = block["type"]
            if block["type"] == "tool_use":
                self._current_tool_json = ""

        elif event_type == "content_block_delta":
            delta = event["delta"]
            delta_type = delta.get("type")

            if delta_type == "text_delta":
                self.text += delta["text"]
            elif delta_type == "thinking_delta":
                self.thinking += delta["thinking"]
            elif delta_type == "input_json_delta":
                self._current_tool_json += delta["partial_json"]

        elif event_type == "content_block_stop":
            if self._current_block_type == "tool_use":
                # tool_use 的 JSON 收齐了，解析
                # 注意：完整的 tool_use 信息在 content_block_start 里有
                self._current_block_type = ""

        elif event_type == "message_delta":
            usage = event.get("usage", {})
            self.output_tokens = usage.get("output_tokens", 0)
            self.stop_reason = event.get("delta", {}).get("stop_reason", "")

        elif event_type == "message_stop":
            pass  # 流结束

    @property
    def has_thinking(self) -> bool:
        return len(self.thinking) > 0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    def summary(self) -> str:
        return (
            f"text={len(self.text)}chars, thinking={len(self.thinking)}chars, "
            f"tools={len(self.tool_calls)}, tokens={self.input_tokens}→{self.output_tokens}, "
            f"stop={self.stop_reason}"
        )
```

---

## 三、流式环境下的 Tool Use 处理

### 3.1 流式 Tool Use 的特殊性

```
非流式的 tool_use：
  响应一来就是完整的：{"name": "get_weather", "input": {"city": "北京"}}

流式的 tool_use：
  增量到达，需要拼 JSON：
  delta 1: {"city"
  delta 2: ": "
  delta 3: "北京"
  delta 4: "}

  问题：你只有收到 content_block_stop 才知道 input JSON 收齐了
  但你可能想在收到 "name" 后就提前准备...
```

### 3.2 增强版流式解析器

```python
@dataclass
class StreamParser:
    """完整的流式响应解析器 —— 支持 text + thinking + tool_use"""

    text: str = ""
    thinking: str = ""
    tool_uses: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""

    # 内部状态
    _blocks: dict[int, dict] = field(default_factory=dict)

    def feed(self, line: str) -> dict | None:
        """
        喂一行 SSE 文本。
        返回 dict = 给前端的展示事件（如果有的话）
        返回 None = 内部事件，不需展示
        """
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
                tool = {
                    "id": block["id"],
                    "name": block["name"],
                    "input": json.loads(block["input_json"]) if block["input_json"] else {},
                }
                self.tool_uses.append(tool)
                return {"type": "tool_use", "tool": tool}

        elif event_type == "message_delta":
            self.output_tokens = event.get("usage", {}).get("output_tokens", 0)
            self.stop_reason = event["delta"].get("stop_reason", "")

        elif event_type == "message_stop":
            return {"type": "done", "usage": {
                "input": self.input_tokens,
                "output": self.output_tokens,
            }}

        return None
```

---

## 四、在 Agent 中集成流式输出

### 4.1 Agent 流式循环

```python
"""Agent 主循环 —— 流式版"""
async def agent_loop_stream(
    user_message: str,
    history: list[dict],
    tools: list[dict],
    api_key: str,
    on_text: callable = print,        # 文本回调
    on_thinking: callable = None,      # 思考回调
    on_tool: callable = None,          # 工具调用回调
) -> dict:
    """
    Agent 主循环，流式处理。
    返回最终结果。
    """
    parser = StreamParser()
    current_messages = history + [{"role": "user", "content": user_message}]

    async with httpx.AsyncClient(timeout=120) as client:
        while True:
            parser = StreamParser()  # 每轮重置

            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 4096,
                    "messages": current_messages,
                    "tools": tools,
                    "stream": True,
                },
            ) as response:
                async for line in response.aiter_lines():
                    display = parser.feed(line)
                    if display is None:
                        continue

                    if display["type"] == "text":
                        on_text(display["content"])
                    elif display["type"] == "thinking" and on_thinking:
                        on_thinking(display["content"])
                    elif display["type"] == "tool_use" and on_tool:
                        on_tool(display["tool"])
                    elif display["type"] == "done":
                        break

            # 检查是否需要工具调用
            if parser.tool_uses:
                # 添加 assistant 的 tool_use 到历史
                current_messages.append({
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": t["id"],
                                 "name": t["name"], "input": t["input"]}
                                for t in parser.tool_uses],
                })

                # 执行工具并添加结果
                for tool in parser.tool_uses:
                    result = await execute_tool(tool["name"], tool["input"])
                    current_messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool["id"],
                            "content": str(result),
                        }],
                    })

                continue  # 继续循环，让 LLM 处理工具结果

            # 没有工具调用，对话结束
            current_messages.append({
                "role": "assistant",
                "content": parser.text,
            })
            break

    return {
        "messages": current_messages,
        "final_text": parser.text,
        "total_tokens": parser.input_tokens + parser.output_tokens,
    }
```

### 4.2 前端适配层

```python
"""FastAPI SSE 端点 —— 把 Agent 流式输出转发给前端"""
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json

app = FastAPI()

@app.post("/api/v1/chat/stream")
async def chat_stream(request: ChatRequest):
    async def event_generator():
        async def send_text(text: str):
            yield f"data: {json.dumps({'type': 'text', 'content': text}, ensure_ascii=False)}\n\n"

        async def send_thinking(thinking: str):
            yield f"data: {json.dumps({'type': 'thinking', 'content': thinking}, ensure_ascii=False)}\n\n"

        async def send_tool(tool: dict):
            yield f"data: {json.dumps({'type': 'tool_call', 'name': tool['name'], 'input': tool['input']}, ensure_ascii=False)}\n\n"

        # 这里用回调不好配合 StreamingResponse 的生成器模式
        # 实际项目中需要做适配（见 Day 07 产出）
        result = await agent_loop_stream(
            request.message,
            request.history,
            request.tools,
            os.getenv("ANTHROPIC_API_KEY"),
            on_text=lambda t: ...,  # 需要适配
        )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

---

## 五、流式 vs 非流式的延迟对比

### 5.1 基准测试

```python
"""对比流式和非流式的延迟"""
import asyncio
import httpx
import time
import os

async def benchmark_stream_vs_normal(prompt: str, model: str = "claude-haiku-4-5"):
    """用 Haiku 测试（更便宜）"""
    headers = {
        "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        # 非流式
        t0 = time.time()
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={**body, "stream": False},
        )
        normal_elapsed = time.time() - t0
        normal_data = resp.json()
        normal_ttft = normal_elapsed  # 非流式 TTFT = 总时间

        # 流式
        t0 = time.time()
        first_token_time = None
        async with client.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={**body, "stream": True},
        ) as resp:
            async for line in resp.aiter_lines():
                if first_token_time is None and line.startswith("data: "):
                    event = json.loads(line[6:])
                    if event.get("type") == "content_block_delta":
                        first_token_time = time.time()
            stream_elapsed = time.time() - t0
            stream_ttft = first_token_time - t0 if first_token_time else stream_elapsed

        print(f"模型: {model}")
        print(f"非流式 — 总耗时: {normal_elapsed:.2f}s, TTFT: {normal_ttft:.2f}s")
        print(f"流式   — 总耗时: {stream_elapsed:.2f}s, TTFT: {stream_ttft:.2f}s")
        print(f"TTFT 改善: {(1 - stream_ttft/normal_ttft)*100:.0f}%")

# asyncio.run(benchmark_stream_vs_normal("写一首关于编程的五言绝句"))
```

---

## 六、今日练习（约 2 小时）

### 练习 1：StreamParser 单元测试（30 min）

给上面的 `StreamParser` 写测试，模拟完整的 SSE 事件流：
1. 纯文本回复（无 thinking，无 tool）
2. Thinking + 文本
3. Tool use + 文本
4. 多个 tool_use

### 练习 2：TTFT 对比工具（20 min）

完善上面的 benchmark 代码，测试 3 种不同长度的 prompt，记录每次的 TTFT 和总耗时，画一张对比表。

### 练习 3：流式 Agent 回调适配（40 min）

把 "在 Agent 中集成流式输出" 部分的回调适配为 `asyncio.Queue` 模式：

```python
# 用 asyncio.Queue 替代回调函数
queue = asyncio.Queue()  # Agent 往里 put，FastAPI 往外 get

async def agent_producer(messages, tools, queue):
    """Agent 生产者：解析流式事件，放入队列"""
    ...

async def sse_consumer(queue):
    """SSE 消费者：从队列取事件，yield 给 StreamingResponse"""
    while True:
        event = await queue.get()
        if event is None:  # 结束信号
            break
        yield f"data: {json.dumps(event)}\n\n"
```

### 练习 4：错误处理（30 min）

在流式处理中添加错误处理：
1. 网络断开 → 重试
2. API 返回非 200 → 读取错误体并返回给前端
3. JSON 解析失败 → 跳过并记录日志

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
| ❌ SSE 事件不完整就解析 JSON | 收到 `"input_json": "{\"cit` 就尝试 `json.loads` | 只在 `content_block_stop` 后才 `json.loads` |
| ❌ 忘记处理 ping 事件 | 流式连接超时断开 | 收到 ping 直接忽略即可 |
| ❌ Nginx 反向代理缓冲了 SSE | 前端等全部生成完才收到数据 | 配置 `proxy_buffering off;` + 加 `X-Accel-Buffering: no` 头 |
| ❌ 前端 EventSource 不支持 POST | `EventSource` 只支持 GET | 用 `fetch` + `ReadableStream` 替代 EventSource |

---

## Day 04 检查清单

- [ ] 理解流式 vs 非流式的延迟差异（TTFT）
- [ ] 知道 Claude SSE 的 7 种事件类型
- [ ] 能解析 text_delta / thinking_delta / input_json_delta
- [ ] 能在流式环境下正确拼接 tool_use 的 JSON
- [ ] 能实现完整的 StreamParser
- [ ] 理解 Netty/网关对 SSE 的影响及配置方法
- [ ] 能写 Agent 流式主循环
- [ ] 能处理流式错误

---

## 副线：Claude Code 实战

### 今天的任务：对比 Claude Code 的流式输出

Claude Code 本身就是流式输出的。观察：

1. Claude Code 的文字是逐字出现的吗？还是在缓冲？
2. tool call（读文件、写代码）出现时，流式文字怎么变化？
3. 对比 Claude Code 的流式体验和你写的 SSE 端点，有什么可以借鉴的？

### CLI Agent 认知笔记

```
Claude Code 的流式体验打分（1-5）：____________________
它处理 Tool Call 时的流式表现：____________________
我可以借鉴的地方：____________________
```

---

## 明天计划

- [ ] Day 05 — Prompt Caching 原理：缓存命中规则、cache read/write tokens 计费、cache-friendly prompt 设计
