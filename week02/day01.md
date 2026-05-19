# Day 01 — Token 机制

## 学习目标

理解 Token 是什么、LLM 如何把文本切分成 Token、Token 如何影响成本和延迟。能使用 tiktoken 计算 Token 数，为后续的缓存和预算管理打基础。

---

## 一、Token 是什么

### 1.1 一张图说清楚

```
原始文本：  "你好，世界！"
              ↓ Tokenizer（分词器）
Token IDs:  [57668, 53901, 3922, 6447, 11625]
              ↓ 查词汇表
Token 文本: ["你好", "，", "世界", "！", "<|endoftext|>"]
              ↓ 每个 Token 在模型内部是一个向量
Embedding:  [[0.12, -0.34, ...], [...], ...]
```

**Token 是 LLM 理解文本的最小单位。** 模型不是逐字读文本，而是逐 Token 读。一个 Token ≈ 0.75 个英文单词 ≈ 0.5 个中文字。

### 1.2 常见 Token 数量参考

| 文本 | 字符数 | Token 数 | 比例 |
|------|--------|----------|------|
| `"Hello"` | 5 | 1 | 5:1 |
| `"Hello World"` | 11 | 2 | ~5:1 |
| `"你好"` | 2 | 2-3 | ~1:1 |
| `"人工智能"` | 4 | 3-4 | ~1:1 |
| 一页 A4 英文 (~500 words) | ~3000 | ~700 | ~4:1 |
| 一页中文 (~800 字) | ~800 | ~1500 | ~0.5:1 |
| Claude 的系统提示 | — | — | — |

### 1.3 中英文 Token 差异为什么这么大

```python
# 英文：一个常见单词 = 1 个 token
"Hello"       → 1 token     # 高频词，词汇表里有
"World"       → 1 token     # 同上
"unhappy"     → 2 tokens    # "un" + "happy"（子词拆分）

# 中文：一个汉字 = 1~2 个 token
"你好"        → 2 tokens    # 每个汉字占 1 token
"人工智能"    → 4 tokens    # 同上
"tokenization" → ? tokens   # 英文专有名词也会被拆分
```

**核心原因：** Tokenizer 的词汇表里，英文常用词是整词收录的，而中文字符只能逐个编码。所以**同样语义的内容，中文的 token 消耗大约是英文的 1.5~2 倍。**

---

## 二、Tokenizer 原理（BPE）

### 2.1 BPE（Byte Pair Encoding）—— 主流 LLM 都用它

```
BPE 训练过程（简化版）：
1. 把训练文本全部拆成单个字符
2. 统计所有相邻字符对的出现频率
3. 把最高频的字符对合并成一个新 token
4. 重复 2-3，直到词汇表达目标大小

示例：
训练文本: "low low low low lower"
步骤0: l o w _ l o w _ l o w _ l o w _ l o w e r
步骤1: 合并 "lo" → lo w _ lo w _ lo w _ lo w _ lo w e r
步骤2: 合并 "low" → low _ low _ low _ low _ low e r
步骤3: 合并 "er" → low _ low _ low _ low _ low er
```

### 2.2 用 tiktoken 观察 Token 拆分

```python
# pip install tiktoken
import tiktoken

# Claude 用的 tokenizer（近似，实际用的是 Anthropic 私有 tokenizer）
# OpenAI 的 cl100k_base 与 Claude 的 tokenizer 行为类似
enc = tiktoken.get_encoding("cl100k_base")

# 观察英文拆分
print(enc.encode("Hello World"))       # [9906, 1917]
print(enc.encode("unhappy"))           # [3416, 2931] → "un" + "happy"
print(enc.encode("tokenization"))      # [6842, 290, 449] → 被拆成 3 部分

# 观察中文拆分
print(enc.encode("你好"))              # [57668, 53901]
print(enc.encode("人工智能"))          # [43029, 122083, 117, 114278]

# 每个 token 对应的文本
tokens = [enc.decode_single_token_bytes(t).decode("utf-8", errors="replace") for t in enc.encode("tokenization")]
print(tokens)  # ['token', 'iz', 'ation']

# 混合中英文
text = "AI Agent 开发实战"
tokens = enc.encode(text)
print(f"原文: {text}")
print(f"Token 数: {len(tokens)}")
print(f"Token IDs: {tokens}")
for t in tokens:
    decoded = enc.decode_single_token_bytes(t).decode("utf-8", errors="replace")
    print(f"  {t:>6} → '{decoded}'")
```

### 2.3 不同模型的 Tokenizer 差异

| 模型 | Tokenizer | 词汇表大小 | 特点 |
|------|-----------|-----------|------|
| Claude (Anthropic) | 私有 BPE | ~100K | 对代码和结构化数据友好 |
| GPT-4 (OpenAI) | cl100k_base | 100K | tiktoken 可直接用 |
| GPT-3.5 | p50k_base | 50K | 旧版 |
| DeepSeek | 私有 BPE | ~100K | 中文优化更好 |
| Llama 3 | 私有 BPE | 128K | 多语言优化 |

**重要：** 不同模型的 tokenizer 不通用。同样的文本，Claude 和 GPT-4 算出来的 token 数可能差 5~10%。

---

## 三、Token 与成本 —— 真金白银

### 3.1 按 Token 计费模型

```
每次 API 调用成本 = (input_tokens × 输入单价) + (output_tokens × 输出单价)

以 Claude Opus 4 为例（2025 年价格参考）：
  input:  $15 / 1M tokens
  output: $75 / 1M tokens    ← 输出比输入贵 5 倍！

一次典型对话：
  input:  2000 tokens  → $0.03
  output: 500 tokens   → $0.0375
  总成本: $0.0675
```

### 3.2 成本快速估算

```python
# 成本计算工具
from dataclasses import dataclass

@dataclass
class ModelPricing:
    name: str
    input_price_per_1m: float   # 每百万 token 美元价格
    output_price_per_1m: float

# 2025 年 Claude 模型参考定价
models = {
    "claude-opus-4-7":    ModelPricing("Opus 4.7",    15, 75),
    "claude-sonnet-4-6":  ModelPricing("Sonnet 4.6",   3, 15),
    "claude-haiku-4-5":   ModelPricing("Haiku 4.5",    1,  5),
}

def estimate_cost(model_key: str, input_tokens: int, output_tokens: int) -> float:
    p = models[model_key]
    cost = (input_tokens / 1_000_000) * p.input_price_per_1m + \
           (output_tokens / 1_000_000) * p.output_price_per_1m
    return cost

# 示例：一次 Opus 调用
cost = estimate_cost("claude-opus-4-7", input_tokens=2000, output_tokens=500)
print(f"单次调用成本: ${cost:.6f}")  # $0.067500

# 一天 1000 次调用的成本
print(f"日成本 (1000次): ${cost * 1000:.2f}")  # $67.50
```

### 3.3 什么时候 Token 数会暴涨

```python
# 场景 1：长对话历史
# 第 1 轮：200 tokens
# 第 10 轮：2000 tokens（前面 9 轮全部带回去）
# 第 50 轮：10000 tokens（成本涨了 50 倍）

# 场景 2：大段上下文注入
# 把整个 API 文档塞进 system prompt → 5000+ tokens
# RAG 检索了 10 个文档片段 → 3000+ tokens

# 场景 3：Tool Use 来回
# 用户消息 → LLM 回复 tool_use → 你的 tool 结果 → LLM 再回复
# 每一轮都把前面的东西带回去，token 指数增长
```

---

## 四、输入 Token vs 输出 Token

### 4.1 区别不只是价格

```
                    Input Tokens              Output Tokens
────────────────────────────────────────────────────────────
计费              $15/M（Opus）              $75/M（Opus）
Cache 支持        可缓存（降价 90%）          不可缓存
计数时机          请求发出前已知？            生成完才知道
对延迟的影响      大（影响预填充时间）        大（生成时间是逐 token 的）
优化方向          精简 prompt、用 cache       控制 max_tokens、尽早 stop
```

### 4.2 用 API 响应反查 Token 用量

```python
# Claude API 响应的 usage 字段
response = {
    "id": "msg_xxx",
    "model": "claude-sonnet-4-6",
    "usage": {
        "input_tokens": 350,              # 输入 token
        "output_tokens": 120,             # 输出 token
        "cache_creation_input_tokens": 0, # 缓存写入（如果要写缓存）
        "cache_read_input_tokens": 0,     # 缓存命中（如果命中缓存）
    }
}

# 计算实际计费 token
billed_input = response["usage"]["input_tokens"]
if response["usage"]["cache_read_input_tokens"] > 0:
    billed_input = response["usage"]["input_tokens"]  # 已含缓存折扣
```

---

## 五、tiktoken 实战

### 5.1 基本用法

```python
import tiktoken

enc = tiktoken.get_encoding("cl100k_base")

# 计算 token 数
text = "Hello, how are you?"
count = len(enc.encode(text))
print(f"'{text}' → {count} tokens")  # 6 tokens

# 截断文本到指定 token 数
def truncate_to_tokens(text: str, max_tokens: int) -> str:
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return enc.decode(tokens[:max_tokens])

long_text = "This is a very long text " * 100
truncated = truncate_to_tokens(long_text, 50)
print(f"原文 token: {len(enc.encode(long_text))}, 截断后: {len(enc.encode(truncated))}")
```

### 5.2 封装一个 TokenCounter

```python
"""LLM Token 计数器"""
import tiktoken
from dataclasses import dataclass, field

@dataclass
class TokenCounter:
    encoding_name: str = "cl100k_base"
    _encoder: tiktoken.Encoding = field(init=False)

    def __post_init__(self):
        self._encoder = tiktoken.get_encoding(self.encoding_name)

    def count(self, text: str) -> int:
        return len(self._encoder.encode(text))

    def count_messages(self, messages: list[dict]) -> int:
        """估算 messages 格式的 token 数（近似）"""
        total = 0
        for msg in messages:
            total += self.count(msg.get("content", ""))
            total += self.count(msg.get("role", ""))
            total += 4  # 每条消息的格式开销（近似）
        total += 2  # 整体格式开销
        return total

    def truncate(self, text: str, max_tokens: int) -> str:
        tokens = self._encoder.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return self._encoder.decode(tokens[:max_tokens])

# 使用
counter = TokenCounter()
print(counter.count("Hello, world!"))  # 4

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is AI?"},
]
print(f"消息 token 估算: {counter.count_messages(messages)}")
```

---

## 六、今日练习（约 2 小时）

### 练习 1：Token 可视化（20 min）

```python
"""观察不同文本类型的 token 拆分"""
import tiktoken

enc = tiktoken.get_encoding("cl100k_base")

test_texts = [
    "Hello World",
    "你好世界",
    "print('hello')",
    '{"name": "Alice", "age": 30}',
    "The quick brown fox jumps over the lazy dog.",
    "人工智能正在改变世界",
]

for text in test_texts:
    tokens = enc.encode(text)
    print(f"\n原文: {text}")
    print(f"Token 数: {len(tokens)}, 字符数: {len(text)}, 比例: {len(text)/len(tokens):.1f} 字符/token")
    for t in tokens:
        decoded = enc.decode_single_token_bytes(t).decode("utf-8", errors="replace")
        print(f"  [{t:>6}] '{decoded}'")
```

### 练习 2：TokenCounter 完善（25 min）

完善上面的 `TokenCounter` 类：
1. 添加 `count_file(filepath)` 方法，统计一个文件的 token 数
2. 添加 `estimate_cost(model_key, input_tokens, output_tokens)` 方法
3. 添加 `split_by_tokens(text, chunk_size)` 方法，按 token 数切分文本

### 练习 3：对话 Token 增长模拟（30 min）

```python
"""模拟多轮对话中 token 消耗的增长"""
import tiktoken

enc = tiktoken.get_encoding("cl100k_base")

system_prompt = "You are a helpful AI assistant with expertise in Python programming."
user_messages = [
    "What is a decorator in Python?",
    "Can you show me an example?",
    "How about a decorator with arguments?",
    "What's the difference between @staticmethod and @classmethod?",
    "Can you write a decorator that measures function execution time?",
]

total_tokens = len(enc.encode(system_prompt))
print(f"System prompt: {total_tokens} tokens\n")

conversation = []
for i, msg in enumerate(user_messages, 1):
    msg_tokens = len(enc.encode(msg))
    total_tokens += msg_tokens
    # 模拟 assistant 回复（假设回复长度 = 问题的 3 倍 token）
    reply_tokens = msg_tokens * 3
    total_tokens += reply_tokens

    print(f"第 {i} 轮: +{msg_tokens} (问) +{reply_tokens} (答) → 累计 {total_tokens} tokens")

print(f"\n5 轮对话后 token 消耗: {total_tokens}")
print(f"如果每轮都带着完整历史，第 6 轮输入将包含 ~{total_tokens} tokens")
```

### 练习 4：成本计算器（45 min）

写一个完整的 `CostTracker` 上下文管理器，追踪一次 LLM 调用的 token 消耗和预估成本：

```python
@contextmanager
def cost_tracker(model: str, label: str = ""):
    """追踪单次 LLM 调用的 cost"""
    # TODO: 记录开始时间
    # TODO: yield stats dict 给调用方填充
    # TODO: 在 finally 中计算并打印成本
    pass

# 期望用法：
with cost_tracker("claude-sonnet-4-6", "代码生成") as stats:
    # 调用 LLM...
    stats["input_tokens"] = response.usage.input_tokens
    stats["output_tokens"] = response.usage.output_tokens
    stats["cache_read"] = response.usage.cache_read_input_tokens
# 离开 with 块时自动打印：[代码生成] 350→120 tokens | 💰 $0.00285
```

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
| ❌ 以为 tiktoken 和 Claude tokenizer 完全一致 | 用 tiktoken 算了 1000 token，实际 Claude 报 1050 | tiktoken 只做近似估算，精确计数以 API 返回的 usage 为准 |
| ❌ 忽略消息格式的 token 开销 | 只算 content 的 token，忘了 role 和结构也有开销 | 用 `count_messages()` 方法加 4~6 token/条的格式开销 |
| ❌ 在循环里反复创建 tiktoken encoder | 每次 count 都 `tiktoken.get_encoding()`，性能很差 | 创建一次，复用 |

---

## Day 01 检查清单

- [ ] 理解 Token 是 LLM 的最小处理单位，不是字符
- [ ] 能用 tiktoken 计算文本的 token 数
- [ ] 知道中英文的 token 消耗差异（中文约 1.5~2 倍）
- [ ] 理解 BPE tokenizer 的基本原理
- [ ] 清楚 input token 和 output token 的计费差异（输出贵 5 倍）
- [ ] 能估算一次 LLM 调用的成本
- [ ] 能写 TokenCounter 和 CostTracker 工具类

---

## 副线：Claude Code 实战

### 今天的任务：观察 Claude Code 的 Token 消耗

在 Claude Code 对话中按 `Ctrl+T` 或者查看对话底部，观察当前对话消耗了多少 token。然后：

1. 打开一段比较长的代码文件，让 Claude Code 帮你分析
2. 观察 token 消耗增加了多少
3. 对比 "只贴关键代码" vs "贴整个文件" 的 token 消耗差异
4. 思考：什么样的提问方式更省 token？

### CLI Agent 认知笔记

```
当前对话消耗了多少 token：____________________
贴整个文件 vs 贴关键代码的 token 差异：____________________
下次怎么提问更省 token：____________________
```

---

## 明天计划

- [ ] Day 02 — Context Window：理解上下文窗口限制、长对话管理策略、Token 预算管理
