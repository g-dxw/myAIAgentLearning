# Day 01 — RAG 基础概念 + Embedding 入门

## 学习目标

理解 RAG 是什么、解决什么问题。亲手调 Embedding API，手写余弦相似度，直观感受"语义相近 → 向量相近"。

学完今天你能：
1. 说清楚 RAG 五步流程每步在做什么
2. 用 httpx 直接调 Ollama Embedding API
3. 手写余弦相似度函数，验证语义相近的文本向量也更相近
4. 理解 Embedding 维度对检索精度和速度的影响

---

## 一、RAG 是什么？

### 1.1 三个关键词拆开看

```
Retrieval   Augmented   Generation
  检索         增强         生成
   ↓           ↓           ↓
从知识库    用检索结果    LLM 基于
找相关资料  增强 Prompt   增强后的 Prompt 生成答案
```

**一句话：** RAG = 先从外部知识库检索相关资料，再把资料拼进 Prompt，让 LLM 基于资料回答问题。

### 1.2 RAG 解决三个问题

| 问题 | 不用 RAG | 用了 RAG |
|------|---------|---------|
| **知识截止** | LLM 训练数据截止于某个日期，不知道之后的事 | 把最新文档放进知识库，实时检索 |
| **幻觉** | LLM 被问不知道的东西时会瞎编 | 约束"只能基于资料回答"，资料没写的就说不知道 |
| **私有知识** | LLM 没见过你公司的内部文档 | 把内部文档索引起来，LLM 就能回答 |

> **💡 直觉类比：** RAG 相当于考试时的"开卷考试"——LLM 是你的大脑，向量数据库是你的课本。你不会只凭记忆答题，而是先去课本里翻到相关章节，再组织答案。

### 1.3 RAG 五步流程

```
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌──────────┐    ┌──────────┐
│  Load   │ →  │  Split  │ →  │ Embed   │ →  │  Store   │ →  │ Retrieve │
│  加载   │    │  分割   │    │ 向量化  │    │  存储    │    │  检索    │
└─────────┘    └─────────┘    └─────────┘    └──────────┘    └──────────┘
                                                                   ↓
                                                          ┌──────────┐
                                                          │ Generate │
                                                          │  生成    │
                                                          └──────────┘
```

| 步骤 | 英文 | 输入 | 输出 | 类比 |
|------|------|------|------|------|
| 1. 加载 | Load | PDF/MD/TXT 文件 | 原始文本 | 把书翻开 |
| 2. 分割 | Split | 长文本 | 短文本块（chunks） | 把书拆成一页一页 |
| 3. 向量化 | Embed | 文本块 | 向量（浮点数数组） | 把每页内容"翻译"成数字 |
| 4. 存储 | Store | 向量 + 原文 | 向量数据库索引 | 把数字索引存进书架 |
| 5. 检索 | Retrieve | 用户问题 | 最相关的 K 个文本块 | 从书架找到相关页 |
| 6. 生成 | Generate | 问题 + 检索结果 | 自然语言答案 | 基于找到的页作答 |

**本周每天对应一个或两个步骤**，Day 07 把所有串起来。

---

## 二、Embedding 本质：把文本映射到向量空间

### 2.1 什么是 Embedding？

Embedding 就是**把一段文本转换成一个固定长度的浮点数数组**：

```python
text = "今天天气真好"
embedding = [0.023, -0.451, 0.872, ..., 0.134]  # 768 个浮点数
```

这个数组不是随机的——**语义相近的文本，向量也相近**。

### 2.2 为什么向量相近 = 语义相近？

想象一个三维空间（实际是 768 维）：

```
         "狗" ●
                \
                 \  距离近 = 语义相近
                  \
              "猫"  ●
                     
                     
        "汽车" ●     距离远 = 语义无关
```

Embedding 模型训练时，让语义相近的文本向量靠得更近。 所以：
- `cosine("猫", "狗")` → 0.85（高相似度，都是宠物）
- `cosine("猫", "汽车")` → 0.12（低相似度，无关概念）
- `cosine("今天天气真好", "今天是个晴天")` → 0.92（高相似度，语义等价）

### 2.3 余弦相似度

RAG 中最常用的相似度算法：

```
余弦相似度 = cos(θ) = (A · B) / (|A| × |B|)

A · B = a₁b₁ + a₂b₂ + ... + aₙbₙ  （点积）
|A| = √(a₁² + a₂² + ... + aₙ²)   （向量长度）
```

值域：[ -1, 1 ]，越接近 1 越相似，0 表示无关，-1 表示完全相反。

```python
import math


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    计算两个向量的余弦相似度。

    >>> cosine_similarity([1, 0], [1, 0])
    1.0
    >>> cosine_similarity([1, 0], [0, 1])
    0.0
    >>> cosine_similarity([1, 0], [-1, 0])
    -1.0
    """
    # 点积
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    # 向量长度
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0  # 零向量兜底

    return dot / (norm_a * norm_b)
```

### 2.4 为什么不用欧氏距离？

| 指标 | 余弦相似度 | 欧氏距离 |
|------|-----------|---------|
| 关注什么 | **方向**（语义取向） | **绝对位置** |
| 受文本长度影响 | 小（归一化了方向） | 大（长文本向量值更大） |
| 适用场景 | 语义搜索、推荐 | 图像匹配、异常检测 |
| RAG 中谁更常用 | ✅ **余弦相似度** | ❌ 基本不用 |

简记：**余弦看方向，欧氏看距离。** 语义搜索关心"意思像不像"，不关心"长度一不一样"。

---

## 三、用 httpx 调 Embedding API

### 3.1 Ollama Embedding API

Ollama 提供本地 Embedding 服务，免费、零配置、数据不出本机。

```python
"""embedding_demo.py — 调 Ollama Embedding API + 手算相似度"""
import httpx
import math
import time


# ===== 1. 调 Ollama Embedding API =====

def embed_text(
    text: str,
    model: str = "nomic-embed-text:latest",
    base_url: str = "http://localhost:11434",
) -> list[float]:
    """
    将单段文本转为 Embedding 向量。

    Ollama 的 Embedding endpoint 是 POST /api/embeddings，
    请求体: {"model": "...", "prompt": "..."}
    响应体: {"embedding": [0.1, 0.2, ...]}
    """
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{base_url}/api/embeddings",
            json={"model": model, "prompt": text},
        )
        resp.raise_for_status()
        data = resp.json()

    if "embedding" in data:
        return data["embedding"]

    # 兜底：某些代理可能返回 OpenAI 格式
    return data["data"][0]["embedding"]


# ===== 2. 余弦相似度 =====

def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ===== 3. 验证实验 =====

if __name__ == "__main__":
    # 先确认 Ollama 在运行，且已拉取 embedding 模型
    # ollama pull nomic-embed-text:latest

    print("=" * 60)
    print("Embedding 语义相似度验证实验")
    print("模型: nomic-embed-text:latest (768 维)")
    print("=" * 60)

    # 测试组
    tests = [
        # (文本A, 文本B, 预期)
        ("猫", "狗", "高 — 都是宠物"),
        ("猫", "汽车", "低 — 无关概念"),
        ("Python 是一门编程语言", "JavaScript 也是一门编程语言", "高 — 语义相近"),
        ("Python 是一门编程语言", "今天天气真好", "低 — 语义无关"),
        ("我喜欢吃苹果", "苹果是一种水果", "中等 — 共享'苹果'概念"),
    ]

    for text_a, text_b, expected in tests:
        # 调用 API 获取向量
        vec_a = embed_text(text_a)
        vec_b = embed_text(text_b)

        # 计算相似度
        sim = cosine_similarity(vec_a, vec_b)

        # 可视化
        bar_len = int(sim * 20)  # 最多 20 个字符
        bar = "█" * bar_len + "░" * (20 - bar_len)

        print(f"\nA: {text_a}")
        print(f"B: {text_b}")
        print(f"相似度: {sim:.4f}  [{bar}]")
        print(f"预期: {expected}")
        print(f"维度: {len(vec_a)}")

    # ===== 4. 维度信息 =====
    print(f"\n{'=' * 60}")
    print("模型信息")
    print(f"  模型: nomic-embed-text:latest")
    vec = embed_text("test")
    print(f"  输出维度: {len(vec)}")
    print(f"  单次耗时: ~{0.1:.0f}s (本地)")
    print(f"  费用: 免费 ✨")
    print(f"{'=' * 60}")
```

### 3.2 OpenAI 兼容 Embedding API

如果你用的是 OpenAI / DeepSeek / 通义千问等云端 API：

```python
def embed_text_openai(
    text: str,
    model: str = "text-embedding-3-small",
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
) -> list[float]:
    """调 OpenAI 兼容 Embedding API"""
    import os
    api_key = api_key or os.getenv("OPENAI_API_KEY", "")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "input": text,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{base_url}/embeddings",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

    return data["data"][0]["embedding"]
```

### 3.3 Ollama vs OpenAI Embedding 对照

| 维度 | Ollama | OpenAI |
|------|--------|--------|
| **Endpoint** | `POST /api/embeddings` | `POST /v1/embeddings` |
| **请求字段** | `prompt`（单数） | `input` |
| **响应结构** | `{"embedding": [...]}` | `{"data": [{"embedding": [...]}]}` |
| **维度** | nomic-embed-text: 768 | text-embedding-3-small: 1536（可调） |
| **费用** | 免费（本地） | ~$0.02 / 1M tokens |
| **延迟** | <100ms（本地 GPU） | ~200-500ms（网络） |
| **数据隐私** | 数据不出本机 | 发到云端 |

---

## 四、Embedding 维度详解

### 4.1 常见模型的维度

| 模型 | 维度 | 特点 |
|------|------|------|
| nomic-embed-text (Ollama) | 768 | 本地免费，适合原型 |
| bge-m3 (Ollama) | 1024 | 多语言，中文效果好 |
| text-embedding-3-small (OpenAI) | 512/1536 | 可调维度，省成本 |
| text-embedding-3-large (OpenAI) | 256/1024/3072 | 精度高，贵 |
| Cohere embed-v3 | 1024 | 搜索场景优化 |

### 4.2 维度怎么选？

```
维度越高 → 向量越"精细" → 检索更准 → 但存储更大、计算更慢

经验值：
- 768 维 → 本地原型开发，够用了
- 1024 维 → 生产环境常规选择
- 1536+ 维 → 高精度场景（法律/医疗文档）
```

**一个 768 维向量的存储开销：** `768 × 4 bytes = 3KB`。10 万个 chunk = 300MB。

---

## 五、动手实验

### 🟢 青铜级：跑通 Embedding API

```bash
# 1. 装 Ollama + 拉 embedding 模型
ollama pull nomic-embed-text:latest

# 2. 验证模型可用
curl http://localhost:11434/api/embeddings \
  -d '{"model": "nomic-embed-text:latest", "prompt": "Hello"}'

# 3. 运行上面的 embedding_demo.py
python week04/day01/embedding_demo.py
```

### 🟡 白银级：对比不同模型的相似度

用相同的文本对，分别测 Ollama (nomic-embed-text) 和 OpenAI (text-embedding-3-small)，看相似度差异大不大。

### 🔴 王者级：手写一个简单的最近邻搜索

不用向量库，只用 Python list + 余弦相似度，从 100 条文本中找出与查询最相似的 5 条。

```python
def simple_search(query: str, documents: list[str]) -> list[tuple[str, float]]:
    """纯 Python 最近邻搜索（不用任何向量库）"""
    query_vec = embed_text(query)
    scored = []
    for doc in documents:
        doc_vec = embed_text(doc)
        sim = cosine_similarity(query_vec, doc_vec)
        scored.append((doc, sim))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:5]
```

---

## 六、踩坑记录 🕳️

### 坑 1：Ollama 没拉模型就调 API

```
httpx.HTTPStatusError: 404 — model 'nomic-embed-text:latest' not found
```

**解决：** 先 `ollama pull nomic-embed-text:latest`。如果 Ollama 没启动，先 `ollama serve`。

### 坑 2：Ollama Embedding 请求体用 `input` 而不是 `prompt`

```python
# ❌ 错误：用了 OpenAI 格式
resp = client.post("/api/embeddings", json={"model": "...", "input": text})

# ✅ 正确：Ollama 用 prompt
resp = client.post("/api/embeddings", json={"model": "...", "prompt": text})
```

Ollama 的 Embedding API 请求体字段叫 `prompt`（单数），不是 `input`。

### 坑 3：向量维度不一致

```python
# 用 nomic-embed-text (768维) 生成向量存库
# 用 text-embedding-3-small (1536维) 查询
# → 维度不匹配，计算余弦相似度时报错或得到错结果
```

**解决：** 入库和查询必须用**同一个模型**。模型名记在 metadata 里。

### 坑 4：中文字符在 httpx 中的编码问题

Ollama 本地 API 默认用 UTF-8，基本没问题。但如果遇到乱码：
```python
resp = client.post(url, json={"prompt": text})  # httpx 自动处理编码
```

### 坑 5：Embedding 不是免费的

- Ollama 本地：免费但消耗 GPU/CPU
- OpenAI text-embedding-3-small：$0.02/1M tokens ≈ 1 本书 $0.0002
- **虽然单价极低，但大规模索引（百万级文档）会有成本，注意预算**

---

## 七、副线笔记

### Claude Code 的 CLAUDE.md 是 RAG 吗？

```
RAG Pipeline:
  Query: 用户这次对话的上下文
  Documents: 项目里的 .md / .py / .ts 文件
  Retrieval: Claude Code 读取 CLAUDE.md + 相关代码文件
  Generation: Claude Code 基于这些文件回答/写代码
```

想一想：Claude Code 每次对话开始时读取 CLAUDE.md 和代码文件——这个过程是不是和 RAG 的 Retrieve → Generate 阶段一模一样？

**区别在于：**
- RAG：用向量相似度找"相关"内容
- Claude Code：用人写的 CLAUDE.md 指明"重要"内容 + grep/语义搜索找相关代码
- 你写的 CLAUDE.md 就是「人工指定的检索优先级」

### 今天的观察任务

- 打开 Claude Code 的对话，看它每次回答前读了哪些文件
- 它是不是先读 CLAUDE.md，再根据任务决定读哪些代码文件？
- 这个"先读索引，再按需读详情"的模式，和 RAG 有异曲同工之妙

---

## 今日产出检查清单

- [ ] 能说出 RAG 五步流程每步的输入和输出
- [ ] 手写了余弦相似度函数并验证
- [ ] 用 httpx 成功调了一次 Embedding API
- [ ] 验证了"猫 vs 狗"相似度高、"猫 vs 汽车"相似度低
- [ ] 知道自己的 Embedding 模型是多少维
- [ ] 知道 Ollama Embedding API 的请求体和响应体结构

---

> **下一课预告：Day 02 — 文档加载 + 文本分割**。你将亲手把 PDF 拆成可检索的小块，理解 chunk_size 和 overlap 怎么影响检索质量。
