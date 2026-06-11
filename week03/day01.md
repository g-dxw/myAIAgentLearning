# Day 01 — API 实战调用：理解 LLM Message 格式

## 学习目标

真正理解 LLM API 的 Message 格式——这是所有 Agent 开发的基础。**不要只用 SDK，要亲手用 httpx 发一次 HTTP 请求。** 学完今天的内容，你能：

1. 说清楚 system/user/assistant/tool 四个角色的区别
2. 用 httpx 直接调 OpenAI 兼容 API（不用 openai Python 包）
3. 用 httpx 调 Anthropic API，说出两者的格式差异
4. 自己写流式（SSE）处理代码
5. 从响应中提取 token 用量

---

## 一、Message 格式总览——Agent 世界的"HTTP 协议"

LLM API 的消息格式可以类比 HTTP 协议：**各家的实现细节不同，但核心结构是统一的**。不管你是调 GPT、Claude、DeepSeek 还是通义千问，消息都是一条条带有 `role` 和 `content` 的 JSON 对象。

### 1.1 四角色的"灵魂拷问"

```
请求体 = {
  "model": "gpt-4o",
  "messages": [
    {"role": "system",    "content": "你是 AI 助手"},
    {"role": "user",      "content": "今天北京天气如何？"},
    {"role": "assistant", "content": "让我查一下..."},
    {"role": "tool",      "content": "{\"temp\": 28}"},
  ]
}
```

| Role | 谁发的 | 什么时候用 | JS/TS 对照 |
|------|--------|-----------|-----------|
| `system` | 开发者 | 设定 AI 的行为、人格、约束。**只出现一次，通常在开头** | 类似中间件的 `context` 初始化 |
| `user` | 用户/调用者 | 用户的输入。可以是文本、图片 URL、多模态数据 | 类似前端的 `request.body` |
| `assistant` | LLM 模型 | 模型的回复。**当 LLM 调用了工具时，`tool_calls` 字段也在 assistant 消息里** | 类似后端的 `response.data` |
| `tool` | 工具执行结果 | Function Calling 的结果，**必须对应上一条 assistant 消息里的 tool_call Id** | 类似 Promise `.then()` 的回调结果 |

> **💡 JS/TS 直觉：** 把 `messages` 想象成一个不可变的 `state[]`。每次 LLM 调用是这个数组的 `reduce` 操作——你喂给它历史的 messages，它 append 一条新的 assistant message。

### 1.2 为什么 Agent 开发必须先理解 Message 格式？

因为 Agent 循环本质上就是**不断地 append 消息到 messages 数组，然后重新调 LLM**：

```python
# Agent 循环伪代码——这就是未来几天你要手写的核心
messages = [
    {"role": "system", "content": "你是一个能调用工具的助手"},
    {"role": "user",   "content": user_input},
]

while True:
    response = call_llm(messages)          # 1. 调 LLM
    msg = response["choices"][0]["message"]
    messages.append(msg)                    # 2. 追加回复

    if "tool_calls" not in msg:             # 3. 没有工具调用 → 结束
        return msg["content"]

    for tool_call in msg["tool_calls"]:     # 4. 执行工具
        result = execute_tool(tool_call)
        messages.append({                   # 5. 追加 tool 结果
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": result,
        })
    # 6. 回到 while 开头，继续循环
```

看不懂这段？学完今天的内容你就全懂了。

---

## 二、用 httpx 直接调 OpenAI 兼容 API

不依赖 `openai` SDK，就是为了让你看清 HTTP 层到底发生了什么。

### 2.1 最简调用

```python
"""直接发 HTTP 请求调 LLM——零依赖演示"""
import httpx
import os

def call_openai(
    messages: list[dict],
    model: str = "gpt-4o",
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    temperature: float = 0.7,
) -> dict:
    """调 OpenAI 兼容 API，返回完整 JSON 响应"""
    api_key = api_key or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("需要 API Key，请设置 OPENAI_API_KEY 环境变量")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    messages = [
        {"role": "system", "content": "你是一个 Python 导师，用中文回答，简洁有力。"},
        {"role": "user", "content": "Python 的装饰器是什么？用一句话说清楚。"},
    ]
    result = call_openai(messages)
    
    # 看看完整的响应结构
    print("=== 完整响应结构 ===")
    for k, v in result.items():
        print(f"  {k}: {type(v).__name__}")

    # 提取回复
    reply = result["choices"][0]["message"]["content"]
    print(f"\n=== LLM 回复 ===\n{reply}")

    # 提取 token 用量
    if "usage" in result:
        u = result["usage"]
        print(f"\n=== Token 用量 ===")
        print(f"  输入: {u.get('prompt_tokens', 'N/A')} tokens")
        print(f"  输出: {u.get('completion_tokens', 'N/A')} tokens")
        print(f"  总计: {u.get('total_tokens', 'N/A')} tokens")
```

**运行方法：**

```bash
# 先安装 httpx（pip 或 uv 都行）
pip install httpx

# 设置 API Key（三选一）
export OPENAI_API_KEY="sk-xxx"                    # Linux/Mac
set OPENAI_API_KEY="sk-xxx"                       # Windows cmd
$env:OPENAI_API_KEY = "sk-xxx"                    # PowerShell

# 运行
python day01_part1.py
```

### 2.2 JS/TS 对照版

如果你更熟悉 JS/TS，等价的代码是这样的：

```typescript
// 等价于上面的 Python 版本
import { createServer } from 'node:http';  // 只是类比，不是真要起 server

async function callOpenAI(
  messages: Array<{role: string; content: string}>,
  options?: {model?: string; baseUrl?: string; apiKey?: string}
) {
  const apiKey = options?.apiKey ?? process.env.OPENAI_API_KEY!;
  const baseUrl = options?.baseUrl ?? 'https://api.openai.com/v1';

  const resp = await fetch(`${baseUrl}/chat/completions`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: options?.model ?? 'gpt-4o',
      messages,
      temperature: 0.7,
    }),
  });

  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`API Error ${resp.status}: ${err}`);
  }

  return resp.json();
}

// 使用
const result = await callOpenAI([
  { role: 'system', content: '你是 Python 导师，用中文回答。' },
  { role: 'user', content: 'Python 的装饰器是什么？' },
]);

console.log(result.choices[0].message.content);
console.log('Token 用量:', result.usage);
```

> **对比要点：** Python 的 `httpx` ≈ JS 的 `fetch`。`httpx.Client(timeout=60)` 相当于 `AbortController` + timeout。`resp.json()` 两边一样。

---

## 三、用 httpx 调 Anthropic API（对比格式差异）

Anthropic 的 API 格式是"异类"——学它不是因为它在 Agent 领域市场份额大，而是因为**对比能帮你真正理解"通用格式"的本质**。

```python
"""调 Anthropic API——体会格式差异"""
import httpx
import os

def call_anthropic(
    messages: list[dict],
    model: str = "claude-sonnet-4-20250514",
    api_key: str = "",
    system_prompt: str = "",
    max_tokens: int = 4096,
) -> dict:
    """调 Anthropic API

    关键差异：
    1. system prompt 在顶层参数，不在 messages 里
    2. 响应结构是 content[0].text，不是 choices[0].message.content
    3. API endpoint 是 /v1/messages
    4. 认证用 x-api-key 头，不是 Bearer token
    """
    api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("需要 ANTHROPIC_API_KEY")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    # Anthropic 的 messages 里不能有 system 角色
    filtered_messages = [
        m for m in messages if m["role"] != "system"
    ]

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": filtered_messages,
    }
    if system_prompt:
        body["system"] = system_prompt

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    result = call_anthropic(
        messages=[{"role": "user", "content": "用一句话解释什么是 Agent 循环"}],
        system_prompt="你是 AI 专家，用中文回答，不超过 50 字。",
    )

    print("=== 完整响应结构 ===")
    for k, v in result.items():
        print(f"  {k}: {type(v).__name__}")
        if isinstance(v, list):
            for i, item in enumerate(v):
                print(f"    [{i}]: {json.dumps(item, ensure_ascii=False)[:100]}...")

    # Anthropic 的回复在 content[0].text
    reply = result["content"][0]["text"]
    print(f"\n=== LLM 回复 ===\n{reply}")

    # Anthropic 的 usage 结构
    if "usage" in result:
        u = result["usage"]
        print(f"\n=== Token 用量 ===")
        print(f"  输入: {u.get('input_tokens', 'N/A')} tokens")
        print(f"  输出: {u.get('output_tokens', 'N/A')} tokens")
```

### 3.1 格式差异对照表

| 维度 | OpenAI 兼容 | Anthropic |
|------|------------|-----------|
| **Endpoint** | `/v1/chat/completions` | `/v1/messages` |
| **认证方式** | `Authorization: Bearer <key>` | `x-api-key: <key>` + `anthropic-version` |
| **System prompt** | 在 `messages` 数组里，`role: "system"` | 顶层参数 `system`，messages 里不能有 system 角色 |
| **响应结构** | `choices[0].message.content` | `content[0].text` |
| **Tool calls 位置** | assistant message 的 `tool_calls` 字段 | assistant content block 的 `type: "tool_use"` |
| **Streaming** | SSE `data: {...}`，以 `data: [DONE]` 结束 | SSE `event: content_block_delta` + `event: message_stop` |
| **多模态** | content 可以是字符串或数组 | content 总是数组 |

> **实际建议：** 如果你在 2026 年做 Agent 开发，**优先用 OpenAI 兼容的 API**（DeepSeek、通义千问、Groq、Together、OpenRouter 都兼容）。Anthropic 的格式需要额外适配层。但在 Claude 模型本身效果极好的场景（如长上下文推理、代码生成），值得单独适配。

---

## 四、流式响应处理（SSE）

流式（Streaming）是 Agent 开发中**必须掌握**的技能——你的 Agent 在调用工具时，用户不想干等几秒看转圈圈，他们要看到逐字输出。

### 4.1 SSE 协议速览

SSE（Server-Sent Events）是一种简单的文本协议：

```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"你好"}}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"，今"}}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"天"}}]}

data: [DONE]
```

**关键规则：**
- 每行以 `data: ` 开头（注意末尾有空格）
- 去掉 `data: ` 前缀后的内容是 JSON
- 遇到 `data: [DONE]` 表示流结束
- 空行是分隔符，忽略即可

### 4.2 流式调用实现

```python
"""流式调用 LLM API——逐 token 输出，用户可见"""
import httpx
import json
import os

def call_stream(
    messages: list[dict],
    model: str = "gpt-4o",
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
) -> str:
    """流式调用，返回完整文本"""
    api_key = api_key or os.getenv("OPENAI_API_KEY", "")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "stream": True,  # 🔑 关键：开启流式
        "stream_options": {"include_usage": True},  # 可选：在最后一条 chunk 包含 token 用量
    }

    full_text = ""
    token_count = 0

    with httpx.Client(timeout=120) as client:
        # 使用 client.stream 而不是 client.post
        with client.stream("POST", f"{base_url}/chat/completions",
                           headers=headers, json=body) as resp:
            resp.raise_for_status()

            for line in resp.iter_lines():
                if not line:  # 跳过空行
                    continue
                if not line.startswith("data: "):
                    # 有些代理会发注释行（: keep-alive），忽略
                    continue

                # 去掉 "data: " 前缀（6 个字符）
                data_str = line[6:]

                # 检查结束标记
                if data_str.strip() == "[DONE]":
                    break

                # 解析 JSON chunk
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # 有些 chunk 只有 usage 信息没有 choices
                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                if delta.get("content"):
                    text = delta["content"]
                    full_text += text
                    token_count += 1
                    print(text, end="", flush=True)  # 实时打印，flush=True 确保立即显示

                # 如果 stream_options 里传了 include_usage，最后一条 chunk 会有 usage
                if "usage" in chunk and choices[0].get("finish_reason") == "stop":
                    print(f"\n\n=== Token 用量（来自流） ===")
                    u = chunk["usage"]
                    print(f"  输入: {u.get('prompt_tokens', 'N/A')} tokens")
                    print(f"  输出: {u.get('completion_tokens', 'N/A')} tokens")
                    print(f"  总计: {u.get('total_tokens', 'N/A')} tokens")

    print()  # 最后换行
    return full_text


if __name__ == "__main__":
    print("=== 流式输出开始 ===\n")
    text = call_stream([
        {"role": "system", "content": "你是个诗人，用中文写现代诗。"},
        {"role": "user", "content": "写一首关于 AI Agent 的短诗，4 行。"},
    ])
    print(f"\n=== 完整文本（共 {len(text)} 字）===")
```

### 4.3 JS/TS 流式对照

```typescript
// JS/TS 流式调用的等价实现
async function callStream(messages: Array<{role: string; content: string}>) {
  const resp = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'gpt-4o',
      messages,
      stream: true,
    }),
  });

  if (!resp.ok || !resp.body) {
    throw new Error(`Stream error: ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let fullText = '';
  let buffer = '';  // 处理跨 chunk 的行边界

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop()!;  // 最后一段可能不完整，留到下次

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6);
      if (data.trim() === '[DONE]') break;

      try {
        const chunk = JSON.parse(data);
        const content = chunk.choices?.[0]?.delta?.content;
        if (content) {
          fullText += content;
          process.stdout.write(content);  // Node.js 实时打印
        }
      } catch { /* 跳过解析失败的 chunk */ }
    }
  }

  return fullText;
}
```

> **Python `resp.iter_lines()` vs JS `getReader()`**：Python httpx 帮你做了行分割，你只管逐行处理即可。JS 的 `ReadableStream` 是字节流，需要自己维护缓冲区处理跨 chunk 的行边界——这是 JS 流式处理最容易踩坑的地方。

### 4.4 流式中的"坑"：中文字符被切分

```python
# 这是真实发生的——中文字符可能被切成两半
chunk 1:  data: {"delta": {"content": "你好"}}
chunk 2:  data: {"delta": {"content": "世界，今"}}
chunk 3:  data: {"delta": {"content": "天天气很"}}   # ← "很" 可能被拆成 "很" 或者部分字节
chunk 4:  data: {"delta": {"content": "好"}}
```

**不用担心**：现代 LLM API（GPT-4o、Claude 3.5+）的 Tokenizer 是子词级别的，不会出现半个 UTF-8 字符的情况。你直接拼接字符串即可。**不要自作聪明做"字符缓冲对齐"**——那是解决一个不存在的问题。

---

## 五、从响应中提取 Token 用量

Token 用量的提取看起来简单，但各家 API 的字段名**完全不一样**：

```python
"""统一提取 token 用量——兼容 OpenAI / Anthropic"""
import json

def extract_usage(response: dict) -> dict:
    """从 API 响应中提取 token 用量

    支持 OpenAI 兼容格式和 Anthropic 格式
    返回统一的: {"input_tokens": int, "output_tokens": int}
    """
    usage = response.get("usage")
    if not usage:
        return {}

    # OpenAI 格式: { "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30 }
    if "prompt_tokens" in usage:
        return {
            "input_tokens": usage["prompt_tokens"],
            "output_tokens": usage["completion_tokens"],
            "total_tokens": usage.get("total_tokens", 0),
            "raw": usage,
        }

    # Anthropic 格式: { "input_tokens": 10, "output_tokens": 20 }
    if "input_tokens" in usage:
        return {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["input_tokens"] + usage["output_tokens"],
            "raw": usage,
        }

    # 兜底
    return {"raw": usage}


if __name__ == "__main__":
    # 模拟 OpenAI 响应
    openai_resp = {
        "usage": {"prompt_tokens": 50, "completion_tokens": 100, "total_tokens": 150}
    }
    print("OpenAI:", extract_usage(openai_resp))

    # 模拟 Anthropic 响应
    anthropic_resp = {
        "usage": {"input_tokens": 50, "output_tokens": 100}
    }
    print("Anthropic:", extract_usage(anthropic_resp))
```

> **🤔 思考题：为什么 token 用量很重要？**
>
> 1. **成本追踪**：每个 Agent 循环可能调 3~5 次 LLM，一次对话成本很快到几分钱甚至几毛钱
> 2. **调试工具**：如果某个 Agent 分支的 token 消耗异常高，说明你的 prompt 设计有问题
> 3. **预算封顶**：生产环境必须有 token 用量监控，避免无限循环烧光预算

---

## 六、动手实验

现在轮到你了。今天的动手任务分为三个级别，**选一个你当前能完成的**：

### 🟢 青铜级（有 OpenAI 兼容 API Key）

```python
"""动手实验：你的第一个直接 API 调用"""
import httpx
import json
import os

# 1. 先写一个函数，调任意 OpenAI 兼容 API
def chat_once(prompt: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "demo-key")
    # ... 你的代码在这里 ...

# 2. 再加一个流式版本
def chat_stream(prompt: str) -> str:
    # ... 你的代码在这里 ...
    pass

# 3. 测试：问它一个问题，打印 token 用量
if __name__ == "__main__":
    pass
```

### 🟡 白银级（只有 Anthropic API Key）

用上面给的 `call_anthropic()` 函数，加一个流式版本。Anthropic 的 SSE 格式不同：

```
event: content_block_delta
data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "你"}}

event: content_block_delta
data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "好"}}

event: message_stop
data: {"type": "message_stop"}
```

**和 OpenAI 格式的差异：**
- 前缀不是 `data: `，而是 `event: xxx\n data: xxx`
- 没有 `[DONE]` 标记，以 `event: message_stop` 结束
- 需要维护一个状态机来匹配 event name 和 data

### 🔴 王者级（没有 API Key）

用公有的 Mock API 做练习：

```python
"""没有 API Key 也能练——用 httpx mock 或免费 API"""

# 方案 A：用 httpbin 回显测试
import httpx
resp = httpx.post("https://httpbin.org/post", json={"messages": [{"role": "user", "content": "hi"}]})
print(resp.json())  # 能看清请求结构就行

# 方案 B：用 DeepSeek 免费 API（注册即送 500 万 token）
# base_url = "https://api.deepseek.com/v1"
# model = "deepseek-chat"

# 方案 C：用 OpenRouter 的免费模型
# base_url = "https://openrouter.ai/api/v1"
# model = "google/gemini-2.0-flash-lite"
```

---

## 七、踩坑记录

### 🕳️ 坑 1：`data: [DONE]` 不是所有 API 都发
- OpenAI 兼容 API 在流结束时发 `data: [DONE]`——但 **某些第三方代理（如 One API、New API）可能不发**
- Anthropic 根本没有 `[DONE]`，流结束会发 `event: message_stop`
- **安全做法**：不管有没有 `[DONE]`，当 `choices[0].finish_reason` 为 `"stop"` 或 `choices` 为空时都应视为流结束

### 🕳️ 坑 2：HTTPS 证书/代理问题
在中国大陆访问 OpenAI API 可能需要代理：

```python
# httpx 设置代理
proxies = {
    "http://": "http://127.0.0.1:7890",
    "https://": "http://127.0.0.1:7890",
}
with httpx.Client(timeout=60, proxies=proxies) as client:
    ...
```

如果代理连不上，换成 **DeepSeek**（国内直连）或 **火山引擎** 的 OpenAI 兼容 API。

### 🕳️ 坑 3：SSE 行分割的跨平台问题
- Linux/Mac：`resp.iter_lines()` 能正确处理 `\n` 分隔
- **Windows 上 httpx 的 `iter_lines()` 可能有问题**——有些版本的 httpx 在 Windows 下不会正确处理 SSE 流
- **备用方案**：自己按 `\n` 分割：

```python
buffer = ""
for chunk in resp.iter_raw():
    buffer += chunk.decode("utf-8", errors="replace")
    while "\n" in buffer:
        line, buffer = buffer.split("\n", 1)
        if line.startswith("data: "):
            # 处理这一行
            ...
```

### 🕳️ 坑 4：中文 token 消耗比英文多 1.5~2 倍
- 一条中文 prompt 的 token 数是同样内容英文的 1.5~2 倍
- 这意味着**同样的预算，中文对话的成本更高**
- 如果你在做省钱优化，考虑：英文 system prompt + 中文 user query

### 🕳️ 坑 5：httpx 的 timeout 默认只有 5 秒
- 流式调用至少要设 `timeout=120` 或更高
- 不设 timeout 的话，LLM 生成长文本时中间可能断掉
- 更稳健的做法：`httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0))`

---

## 副线笔记

### 今天的盲区（记录你的问题）

```
Q: OpenAI 的 stream_options.include_usage 返回的 usage 是准确的还是估算的？
A: _________________________________

Q: Anthropic 的 SSE 格式中，event: ping 是什么作用？
A: _________________________________

Q: 为什么不能用 requests 库调 LLM API？
A: _________________________________（提示：requests 不支持 streaming response）
```

### 对比笔记：Claude Code 用的是什么 API 格式？

如果今天你用了 Claude Code（或 Cursor、Windsurf），可以观察：

- 打开开发者工具（DevTools）看 Network 面板
- 看请求的 URL 和 messages 格式——是 OpenAI 兼容还是 Anthropic 原生？
- Claude Code 用了哪些 `tool_use` block？
- 对比你自己写的 `call_openai`——有什么不同？

### 外延阅读

- [OpenAI Chat Completions API 文档](https://platform.openai.com/docs/api-reference/chat)
- [Anthropic Messages API 文档](https://docs.anthropic.com/en/api/messages)
- [SSE（Server-Sent Events）协议规范](https://html.spec.whatwg.org/multipage/server-sent-events.html)

---

## 今日产出检查清单

- [ ] 能说出 system/user/assistant/tool 四角色区别
- [ ] 用 httpx 成功调了一次 OpenAI 兼容 API
- [ ] 用 httpx 成功调了一次 Anthropic API
- [ ] 完成了流式调用的代码并运行通过
- [ ] 能从响应中提取 token 用量
- [ ] 知道 SSE 协议的基本格式（`data: ... \n\n`）
- [ ] 知道 `[DONE]` 标记的作用和局限性

---

> **下一课预告：Day 02 — Function Calling 完整流程**。你将亲手让 LLM 调用天气查询函数、计算器函数，并理解 LLM 是如何"决定"调用哪个工具的。
