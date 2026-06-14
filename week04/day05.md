# Day 05 — 检索质量优化

## 学习目标

检索质量是 RAG 的瓶颈。今天掌握四种主流优化方法，知道什么时候用哪种。

学完今天你能：
1. 识别检索质量差的四类典型表现
2. 实现 Query Rewriting、Re-ranking、Multi-Query、HyDE 四种优化
3. 用 Recall@K 和 MRR 评估检索效果
4. 根据场景选择最优的优化组合

---

## 一、检索为什么会差？

### 1.1 四类典型问题

| 问题 | 表现 | 根本原因 |
|------|------|---------|
| **语义漂移** | 检索结果和问题不相关 | 向量模型对专业术语覆盖不足 |
| **漏检** | 关键信息没被检索到 | 用户问题和文档用词不同 |
| **不够精确** | 检索结果太泛 | 粗检索粒度不够 |
| **问题不完整** | 用户问题有指代 | 多轮对话中"它"、"那个"指代不明 |

### 1.2 优化方法 vs 问题映射

```
问题不完整  →  Query Rewriting（查询重写）
检索太泛    →  Re-ranking（重排序）
漏检        →  Multi-Query（多路查询）
用词差异大  →  HyDE（假设文档嵌入）
```

---

## 二、Query Rewriting（查询重写）

### 2.1 原理

用户往往不会按"最佳检索格式"提问。Query Rewriting 用 LLM 把自然语言问题改写成更适合检索的形式。

```
用户: "上次说的那个配置怎么改？"
重写: "如何修改 config.py 中的 RAG chunk_size 配置参数？"

用户: "有没有快一点的方法？"  
重写: "有哪些方法可以提升 RAG 检索速度？"
```

### 2.2 实现

```python
"""retrieval_optimizer.py — Query Rewriting"""

REWRITE_PROMPT = """你是一个查询优化助手。把用户的问题改写为更适合向量检索的形式。

改写规则：
1. 补全指代词（"它"、"那个"、"这个" → 具体名词）
2. 扩展缩写和专业术语的同义词
3. 拆解复杂问题为简洁的检索关键词
4. 保持原意，不改变问题的核心意图

## 用户原始问题
{question}

## 对话历史（如有）
{history}

## 改写后的问题（1-3个，每行一个）"""


async def rewrite_query(
    question: str,
    llm: "httpx.AsyncClient",
    history: list[dict] | None = None,
) -> list[str]:
    """
    用 LLM 改写用户问题，生成多个检索查询。

    返回: ["改写的问题1", "改写的问题2", ...]
    """
    history_str = ""
    if history:
        recent = history[-6:]
        history_str = "\n".join(
            f"{m['role']}: {m['content'][:100]}" for m in recent
        )

    prompt = REWRITE_PROMPT.format(question=question, history=history_str)

    resp = await llm.post("/api/chat", json={
        "model": "qwen2.5:1.5b",
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.3, "num_predict": 300},
        "stream": False,
    })
    data = resp.json()
    rewritten = data["message"]["content"].strip()

    # 按行拆分
    queries = [q.strip("- ").strip() for q in rewritten.split("\n") if q.strip()]
    return queries if queries else [question]
```

**Query Rewriting 的关键决策：**

| 场景 | 怎么做 |
|------|--------|
| 有对话历史 + 问题有指代 | 补全指代 |
| 专业术语 | 扩展同义词 |
| 复杂问题 | 拆成多个子查询 |
| 简单直白的问题 | 不需要重写，直接检索 |

---

## 三、Re-ranking（重排序）

### 3.1 为什么需要 Re-rank？

向量检索是"粗筛"——它只管语义相近，不管"到底有没有回答这个问题"。

```
Query: "Python 3.12 新增了什么语法？"

粗检索 top 5:
  1. "Python 3.11 的新特性..."     ← 相近但不精确
  2. "Python 3.12 release notes"   ← 对！
  3. "如何升级 Python 版本..."     ← 无关
  4. "Python 3.12 PEP 701..."      ← 对！
  5. "Python 的历史发展..."        ← 太泛

Re-rank 后 top 3:
  1. "Python 3.12 PEP 701..."
  2. "Python 3.12 release notes"
  3. "Python 3.11 的新特性..."
```

Re-ranker 做的是"精排"——把 query 和每个 chunk 成对输入，输出精确的相关性分数。

### 3.2 Re-rank 方案对比

| 方案 | 精度 | 延迟 | 费用 |
|------|------|------|------|
| BGE-Reranker (本地) | 高 | 50-200ms/chunk | 免费 |
| Cohere Rerank API | 极高 | ~100ms | $0.001/次 |
| LLM 打分 | 中 | 500ms+ | 按 token 计费 |

### 3.3 用 LLM 做简易 Re-rank

不引入额外依赖，用 LLM 对每条结果打分：

```python
RERANK_PROMPT = """判断以下文档片段与问题的相关性，只输出一个 0-100 的分数。

## 问题
{question}

## 文档片段
{text}

## 相关性分数（0-100，0=完全无关，100=完美匹配）"""


async def rerank_with_llm(
    question: str,
    chunks: list[dict],
    llm: "httpx.AsyncClient",
    top_k: int = 5,
) -> list[dict]:
    """用 LLM 对粗检索结果逐条打分，排序后返回 top_k"""
    scored = []

    for chunk in chunks:
        prompt = RERANK_PROMPT.format(question=question, text=chunk["text"][:500])
        resp = await llm.post("/api/chat", json={
            "model": "qwen2.5:1.5b",
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0, "num_predict": 10},
            "stream": False,
        })
        data = resp.json()
        score_str = data["message"]["content"].strip()

        # 提取数字
        try:
            score = float(score_str) / 100
        except ValueError:
            score = chunk["similarity"]  # 兜底：用原始相似度

        scored.append({**chunk, "rerank_score": round(score, 4)})

    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    return scored[:top_k]
```

**Re-rank 的成本权衡：**
```
粗检索 20 条 → Re-rank 打分 → 取 top 5
额外成本: 20 次 LLM 调用（简易方案）或 1 次 API 调用（专用 Re-ranker）
收益: 检索精准度提升 20-40%
```

---

## 四、Multi-Query（多路查询）

### 4.1 原理

一个问题拆成多个子查询，并行检索，合并去重。

```
用户: "RAG 有哪些优化方法？"

拆成:
  查询1: "RAG 检索优化方法"
  查询2: "RAG 重排序技术"  
  查询3: "RAG 查询增强策略"
  查询4: "RAG 分块优化"

每个查询独立检索 → 各自返回 top 5 → RRF 合并 → 取 top 5
```

### 4.2 实现

```python
MULTI_QUERY_PROMPT = """为以下问题生成 3-5 个不同角度的检索查询，每行一个。
每个查询应从不同角度覆盖问题的各个方面。

## 问题
{question}

## 不同角度的查询"""


async def multi_query_retrieve(
    question: str,
    vector_store: "VectorStore",
    embed_client: "httpx.AsyncClient",
    llm: "httpx.AsyncClient",
    queries_per_variant: int = 3,
    final_top_k: int = 5,
) -> list[dict]:
    """Multi-Query: 多路查询 + RRF 合并"""
    # Step 1: 生成多路查询
    prompt = MULTI_QUERY_PROMPT.format(question=question)
    resp = await llm.post("/api/chat", json={
        "model": "qwen2.5:1.5b",
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.7, "num_predict": 200},
        "stream": False,
    })
    data = resp.json()
    variants = [
        q.strip("- ").strip()
        for q in data["message"]["content"].strip().split("\n")
        if q.strip()
    ]
    variants = variants[:5]  # 最多 5 个变体

    # Step 2: 每个变体独立检索
    from core.embedding import embed_text

    all_results: list[list[dict]] = []
    for variant in variants:
        vec = await embed_text(embed_client, variant)
        results = vector_store.query(vec, top_k=queries_per_variant)
        all_results.append(results)

    # Step 3: RRF 合并
    from hybrid_search import reciprocal_rank_fusion

    merged = reciprocal_rank_fusion(*all_results)
    return merged[:final_top_k]
```

---

## 五、HyDE（假设文档嵌入）

### 5.1 原理

一篇论文在 2022 年提出的方法，思路非常巧妙：

```
传统: 用户问题 → 向量 → 检索文档
       问题向量       ≠  文档向量（一个在"问题空间"，一个在"答案空间"）

HyDE: 用户问题 → LLM 生成假设答案 → 假设答案向量 → 检索文档
       假设答案向量   ≈  真实文档向量（都在"答案空间"！）
```

**为什么有效？** 假设答案的用词、句式、结构更像文档原文，所以检索更准。

### 5.2 实现

```python
HYDE_PROMPT = """请为以下问题写一个简短的假设答案（50-100字）。
即使你不知道确切答案，也请根据常识写一个合理的推测。

## 问题
{question}

## 假设答案"""


async def hyde_retrieve(
    question: str,
    vector_store: "VectorStore",
    embed_client: "httpx.AsyncClient",
    llm: "httpx.AsyncClient",
    top_k: int = 5,
) -> list[dict]:
    """HyDE: 生成假设答案 → 用假设答案的向量去检索"""
    # Step 1: 生成假设答案
    prompt = HYDE_PROMPT.format(question=question)
    resp = await llm.post("/api/chat", json={
        "model": "qwen2.5:1.5b",
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.5, "num_predict": 200},
        "stream": False,
    })
    data = resp.json()
    hypothetical_answer = data["message"]["content"].strip()

    # Step 2: 用假设答案的向量检索
    from core.embedding import embed_text

    hyde_vec = await embed_text(embed_client, hypothetical_answer)
    results = vector_store.query(hyde_vec, top_k=top_k)

    return results
```

**HyDE 的成本：**
```
正常检索: 1 次 Embedding API + 1 次 VectorStore.query
HyDE:     +1 次 LLM 调用（生成假设答案）
延迟增加: +500ms ~ 2s
适用场景: 用户问题和文档用词差异大时
```

---

## 六、检索评估指标

有了优化方法，需要能量化效果：

### 6.1 Recall@K

前 K 个检索结果中，有多少包含了正确答案？

```python
def recall_at_k(
    retrieved: list[str],
    ground_truth: list[str],
    k: int = 5,
) -> float:
    """
    Recall@K: 前 K 个检索结果中包含正确答案的比例。

    参数:
        retrieved: 检索到的文本块列表
        ground_truth: 标注的正确答案（可以部分匹配）
        k: 只看前 K 个结果

    返回: Recall 值 [0, 1]
    """
    if not ground_truth:
        return 0.0

    top_k = retrieved[:k]
    found = 0
    for gt in ground_truth:
        for result in top_k:
            if gt.lower() in result.lower():
                found += 1
                break

    return found / len(ground_truth)
```

### 6.2 MRR（Mean Reciprocal Rank）

第一个正确答案排在第几位？排名越靠前越好。

```python
def mean_reciprocal_rank(
    retrieved: list[str],
    ground_truth: list[str],
) -> float:
    """
    MRR: 第一个正确答案的排名的倒数。

    例: 第一个正确答案排在第 2 位 → MRR = 1/2 = 0.5
        第一个正确答案排在第 1 位 → MRR = 1/1 = 1.0
        不在结果中 → MRR = 0
    """
    for i, result in enumerate(retrieved, start=1):
        for gt in ground_truth:
            if gt.lower() in result.lower():
                return 1.0 / i
    return 0.0
```

### 6.3 评估脚本

```python
"""retrieval_eval.py — 检索效果评估"""

TEST_CASES = [
    {
        "question": "RAG 是什么？",
        "ground_truth": ["检索增强生成", "Retrieval Augmented Generation"],
    },
    {
        "question": "chunk_size 应该设多大？",
        "ground_truth": ["500", "800", "分块大小"],
    },
    # ... 更多测试用例
]


async def evaluate_retrieval(
    pipeline: "RAGPipeline",
    test_cases: list[dict],
    k: int = 5,
) -> dict:
    """完整评估"""
    total_recall = 0
    total_mrr = 0

    for case in test_cases:
        results = await pipeline.retrieve(case["question"], top_k=k)
        texts = [r["text"] for r in results]

        recall = recall_at_k(texts, case["ground_truth"], k)
        mrr = mean_reciprocal_rank(texts, case["ground_truth"])

        total_recall += recall
        total_mrr += mrr

        print(f"Q: {case['question'][:40]}...")
        print(f"  Recall@{k}: {recall:.2f}  MRR: {mrr:.3f}")

    n = len(test_cases)
    print(f"\n{'='*50}")
    print(f"平均 Recall@{k}: {total_recall / n:.3f}")
    print(f"平均 MRR: {total_mrr / n:.3f}")
    print(f"{'='*50}")

    return {"avg_recall": total_recall / n, "avg_mrr": total_mrr / n}
```

---

## 七、优化决策树

```
检索质量差？
  │
  ├─ 用户问题不完整/有指代 → Query Rewriting
  │
  ├─ 检索结果太多（top_k 大）→ Re-ranking（精排）
  │
  ├─ 问题涉及多个方面 → Multi-Query（多路查询）
  │
  ├─ 问题和文档用词差异大 → HyDE
  │
  └─ 以上都用了还不够 → 换更强的 Embedding 模型
```

**不要一上来就用所有优化。** 先验证基础 RAG 效果，哪里不行补哪里。过度优化会增加延迟和成本。

---

## 八、动手实验

### 🟢 青铜级：实现 Query Rewriting

在 Day 04 的 Pipeline 的 `query()` 前面加一步 `rewrite_query()`，对比改写前后的检索结果差异。

### 🟡 白银级：实现 LLM Re-rank

用 `rerank_with_llm` 对粗检索结果重排，对比重排前后的 top 5 变化。

### 🔴 王者级：跑完整的检索评估

准备 5 个测试问题 + ground truth，对比"无优化 / +Rewriting / +Re-rank / +Multi-Query / +HyDE"五种配置下的 Recall@5 和 MRR。

---

## 九、踩坑记录 🕳️

### 坑 1：Query Rewriting 改太多

```python
# 原问题: "怎么调 chunk_size？"
# 改写: "如何在 Python 中使用 DocumentSplitter 类配置 chunk_size 参数..."
# → 改写过度，可能引入原文没有的术语，反而搜不到了
```

**解决：** 改写时 temperature 设低（0.3），限制输出长度，保留原文中的关键实体。

### 坑 2：Re-rank 成本爆炸

20 条结果 × 500ms/条 = 10 秒延迟。用户等不了。**解决：** 粗检索只取 5-10 条，Re-rank 评分后再取 top 3。

### 坑 3：HyDE 生成幻觉答案

如果 LLM 生成的假设答案完全是错的，检索结果也会跑偏。**HyDE 不适合"需要精确事实"的场景。**

### 坑 4：评估数据没标注

没有 ground truth 就评估不了。一开始至少手写 10 条 Q&A 作为评估集。

---

## 今日产出检查清单

- [ ] 实现了至少一种优化方法（推荐先做 Query Rewriting）
- [ ] 能对比优化前后的检索结果差异
- [ ] 理解四种优化方法的适用场景
- [ ] (可选) 跑通 Recall@K 和 MRR 评估脚本
- [ ] (可选) 对比两种以上的优化组合

---

> **下一课预告：Day 06 — 高级 RAG 模式 + 自定义 Slash Command**。让 Agent 自己判断是否需要检索，以及创建你的第一个 `/rag-ask` 命令。
