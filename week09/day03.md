# Day 03 — RAGAS + Promptfoo 评估工具

## 学习目标

Day 01 我们搭了 Agent 评估指标体系——成功率、步数、工具准确率、成本，这些指标适用于任何 Agent。Day 02 我们用 Langfuse trace 把 Agent 的完整调用链可视化，能定位"哪一步慢了、哪一步错了"。但这两天的指标都是"通用指标"，对 RAG 系统来说还不够精准。

回忆 Week 04：你搭了一个完整的 RAG 流水线——Load → Split → Embed → Store → Retrieve → Generate。当时你怎么判断检索质量好不好？大概率是"人工看几个例子，感觉还行就上线"。这种"凭感觉"的评估方式有个致命问题：你改了 chunk_size、调了 top_k、换了 embedding 模型，根本不知道是改好了还是改坏了。今天我们就用 RAGAS 把这种"凭感觉"变成"看数据"。

学完今天你能：

1. 理解 RAGAS 的四维评估指标：faithfulness（忠实度）、answer_relevancy（答案相关性）、context_precision（上下文精度）、context_recall（上下文召回率）
2. 能用 RAGAS 评估 Week 04 的 RAG 系统，量化检索质量
3. 掌握 Promptfoo 的用途：Prompt 版本管理和 A/B 测试
4. 能对比"改 prompt 前"和"改 prompt 后"的 RAG 质量

---

## 一、RAGAS：RAG 系统的专用评估

### 1.1 回顾 Week 04 的 RAG 流水线

先回忆一下 Week 04 搭的 RAG 系统，它是这样跑的：

```
用户提问
   │
   ▼
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Chunk   │ →  │  Embed   │ →  │  Store   │ →  │ Retrieve │ →  │ Generate │
│ 文档切块  │    │ 向量化    │    │ 入向量库  │    │ 检索片段  │    │ 生成答案  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                    │
                                                    ▼
                                            contexts（检索到的片段）
                                                    │
                                                    ▼
                                            answer（最终答案）
```

这个流水线有两个核心环节可能出问题：

1. **检索环节（Retrieve）**：有没有把正确的片段找回来？找回来的是不是都是有用的？
2. **生成环节（Generate）**：答案是不是基于检索到的内容？有没有在编造（幻觉）？

Day 01 的通用指标（成功率、步数）回答不了这两个问题。成功率只告诉你"任务成没成"，但不告诉你"是检索坏了还是生成坏了"。你需要的是专门针对 RAG 的指标。

### 1.2 RAGAS 是什么

RAGAS（RAG Assessment）是专门为 RAG 系统设计的评估框架。它的核心思路是：把 RAG 系统的输出拆成四个维度，每个维度用一个 0-1 的分数量化。这样你就不再说"感觉检索质量还行"，而是说"context_precision 0.72，context_recall 0.45——召回率太低，漏了关键信息"。

RAGAS 的精妙之处在于：它不需要你手动标注"哪些片段是相关的"——它用 LLM 来做评判（LLM-as-a-judge），自动计算四个维度的分数。代价是评估本身也消耗 token，但比起人工标注的成本，这点 token 消耗完全值得。

### 1.3 RAGAS 四维指标详解

先看总览表，心里有个框架：

| 指标 | 中文名 | 测什么 | 范围 | 越高说明 |
|------|--------|--------|------|---------|
| **faithfulness** | 忠实度 | 答案是否基于检索到的内容（防幻觉） | 0-1 | 越不容易编造 |
| **answer_relevancy** | 答案相关性 | 答案和问题的相关程度 | 0-1 | 越切题 |
| **context_precision** | 上下文精度 | 检索的片段中有多少是真正有用的 | 0-1 | 检索越精准 |
| **context_recall** | 上下文召回率 | 需要的信息是否都被检索到了 | 0-1 | 漏的越少 |

这四个指标正好对应 RAG 的两个核心环节：

```
                    RAG 环节
                    ┌─────────────────────────────────┐
                    │                                 │
              检索环节（Retrieve）              生成环节（Generate）
                    │                                 │
        ┌───────────┴───────────┐                 ┌────┴────┐
        │                       │                 │         │
  context_precision      context_recall      faithfulness  answer_relevancy
  （检索准不准）         （检索全不全）       （有没有编造）  （答得切不切题）
```

### 1.4 每个指标的通俗解释

光看表格不够，逐个拆解：

**1. faithfulness（忠实度）——防幻觉的核心**

faithfulness 衡量的是：答案里的每一条陈述，是不是都能在检索到的 contexts 里找到依据。

```
问题："四姑娘山的海拔是多少？"
contexts: "四姑娘山主峰海拔6250米"

答案 A："四姑娘山主峰海拔6250米"           → faithfulness = 1.0（完全基于上下文）
答案 B："四姑娘山海拔7556米"               → faithfulness = 0.0（编造了数字，幻觉）
答案 C："四姑娘山海拔6250米，适合夏季徒步"  → faithfulness = 0.5（前半有依据，后半编造）
```

faithfulness 低 = Agent 在编造（幻觉）。这是最危险的指标——用户信任你的 RAG 系统，结果它在胡说八道。

**2. answer_relevancy（答案相关性）——答得切不切题**

answer_relevancy 衡量的是：答案和问题的相关程度。有没有答非所问。

```
问题："川西有哪些进阶徒步路线？"

答案 A："长穿毕、四姑娘山二峰、贡嘎大环线等"   → answer_relevancy 高（切题）
答案 B："川西风景很美，值得一去"              → answer_relevancy 低（空话，没回答问题）
答案 C："北京有长城、故宫..."                 → answer_relevancy 很低（完全答非所问）
```

answer_relevancy 低 = 答非所问。检索到了正确信息，但生成环节跑偏了。

**3. context_precision（上下文精度）——检索准不准**

context_precision 衡量的是：检索回来的 top_k 个片段里，有多少是真正有用的。

```
问题："四姑娘山的海拔是多少？"

检索了 top_k=5 的片段：
  片段1: "四姑娘山主峰海拔6250米"           → 有用 ✅
  片段2: "四姑娘山位于四川省阿坝州"          → 无关 ❌
  片段3: "贡嘎山海拔7556米"               → 无关 ❌
  片段4: "长穿毕路线需要3天"              → 无关 ❌
  片段5: "四姑娘山有四座山峰"              → 有点用 ✅

context_precision = 2/5 = 0.4（5个片段里只有2个有用）
```

context_precision 低 = 检索了一堆没用的。用户问了海拔，你检索回来一堆路线信息，token 浪费了，还可能干扰生成。

**4. context_recall（上下文召回率）——检索全不全**

context_recall 衡量的是：回答这个问题需要的信息，是不是都被检索到了。

```
问题："长穿毕路线的难度和所需天数？"
标准答案（ground_truth）: "长穿毕通常需要3天，属于进阶路线，需翻越三个垭口"

检索了 top_k=5 的片段：
  片段1: "长穿毕通常需要3天"              → 覆盖了"天数" ✅
  片段2: "长穿毕需翻越三个垭口"           → 覆盖了"难度" ✅
  片段3: "长穿毕属于进阶路线"             → 覆盖了"难度" ✅

context_recall = 1.0（需要的信息都检索到了）
```

context_recall 低 = 漏了关键信息。问题是需要的，但你没检索到，导致答案不完整。

> **前端类比：** context_precision 就像 API 返回的数据——你是想要 5 条精确数据，还是 5 条里 3 条是垃圾？context_recall 就像分页查询——该返回的数据有没有漏掉？faithfulness 就像前端有没有篡改后端返回的数据（有没有自己编字段）。answer_relevancy 就像这个 API 的响应是不是对应这个请求的。

### 1.5 四维指标的诊断逻辑

这四个指标组合起来，能精准定位 RAG 的问题出在哪：

| 症状 | 可能原因 | 优化方向 |
|------|---------|---------|
| faithfulness 低 | 生成环节在编造 | 加强 prompt 约束（"只基于上下文回答"） |
| answer_relevancy 低 | 生成环节跑偏 | 优化 prompt，或者换更好的模型 |
| context_precision 低 | 检索了一堆没用的 | 加 Reranking（Week 10 会学）、调小 top_k |
| context_recall 低 | 漏了关键信息 | 调大 top_k、优化 chunk 策略、加 Multi-Query |
| precision 低 + recall 低 | 检索系统整体不行 | 检查 embedding 模型、chunk_size |

这就是 RAGAS 的价值——它不只是给个分数，而是告诉你"问题出在哪、该往哪个方向优化"。

---

## 二、用 RAGAS 评估 Week 04 的 RAG

### 2.1 安装 RAGAS

```bash
pip install ragas datasets
```

RAGAS 依赖 `datasets`（Hugging Face 的数据集库）来构造评估数据。装完确认一下版本：

```python
import ragas
print(ragas.__version__)  # RAGAS 更新快，版本不同 API 可能不同
```

### 2.2 RAGAS 需要什么数据

RAGAS 评估需要四个字段：

| 字段 | 说明 | 来源 |
|------|------|------|
| `question` | 用户问题 | 你准备 |
| `ground_truth` | 标准答案 | 人工标注 |
| `answer` | RAG 系统生成的答案 | 运行 RAG 系统获取 |
| `contexts` | RAG 检索到的片段 | 运行 RAG 系统获取 |

其中 `ground_truth` 是最耗精力的——你需要人工写出"理想答案"。但这是值得的，没有标准答案就没法算 context_recall。

### 2.3 完整代码示例

```python
"""rag_eval.py — 用 RAGAS 评估 Week 04 的 RAG 系统

步骤：
1. 准备测试集（问题 + 标准答案 + 相关文档）
2. 运行 RAG 系统获取答案和检索片段
3. 用 RAGAS 计算四维指标
4. 输出评估报告
"""
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from datasets import Dataset

# 1. 准备测试集
test_data = {
    "question": [
        "川西有哪些进阶徒步路线？",
        "四姑娘山的海拔是多少？",
        "长穿毕路线需要几天？",
    ],
    "ground_truth": [
        "长穿毕、四姑娘山二峰、贡嘎大环线等",
        "四姑娘山主峰海拔6250米",
        "长穿毕通常需要3天",
    ],
    "answer": [],  # RAG 系统生成的答案
    "contexts": [],  # RAG 检索到的片段
}

# 2. 运行 RAG 系统收集答案
# 这里假设 rag_system 是 Week 04 的 RAGPipeline 实例
for q in test_data["question"]:
    result = rag_system.invoke(q)
    test_data["answer"].append(result["answer"])
    test_data["contexts"].append(result["contexts"])

# 3. 用 RAGAS 评估
dataset = Dataset.from_dict(test_data)
result = evaluate(
    dataset,
    metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
)

# 4. 输出报告
print(f"忠实度: {result['faithfulness']:.2f}")
print(f"答案相关性: {result['answer_relevancy']:.2f}")
print(f"上下文精度: {result['context_precision']:.2f}")
print(f"上下文召回率: {result['context_recall']:.2f}")
```

### 2.4 接入 Week 04 的 RAGPipeline

Week 04 的 `RAGPipeline` 已经有 `query` 方法，返回 `{answer, sources, usage}`。我们只需要把它适配成 RAGAS 需要的格式：

```python
"""适配 Week 04 的 RAGPipeline → RAGAS 格式"""
import asyncio
from week04.homework.rag.pipeline import RAGPipeline


async def collect_rag_results(rag: RAGPipeline, questions: list[str]):
    """运行 RAG 系统，收集 RAGAS 需要的 answer 和 contexts"""
    answers = []
    contexts_list = []

    for q in questions:
        # Week 04 的 query 方法返回 {answer, sources, usage}
        result = await rag.query(q)

        answers.append(result["answer"])

        # contexts 需要是 list[str]，每个元素是一个检索片段的文本
        # Week 04 的 sources 是 [{"text": "...", "metadata": {...}}, ...]
        contexts = [s["text"] for s in result.get("sources", [])]
        contexts_list.append(contexts)

    return answers, contexts_list


# 用法
rag = RAGPipeline()
questions = test_data["question"]
answers, contexts_list = await collect_rag_results(rag, questions)

test_data["answer"] = answers
test_data["contexts"] = contexts_list
```

### 2.5 评估报告解读

跑完 RAGAS 后，你会拿到四个分数。关键是怎么解读：

```
RAGAS 评估报告
┌──────────────────────────────────────────────┐
│  faithfulness      = 0.85  （不错，基本没编造）│
│  answer_relevancy  = 0.72  （还行，偶尔跑偏）  │
│  context_precision = 0.40  （差，检索一堆没用）│
│  context_recall    = 0.55  （差，漏了关键信息）│
└──────────────────────────────────────────────┘

诊断：检索环节是短板
  → context_precision 0.40 = 5个片段里只有2个有用
  → context_recall 0.55 = 接近一半的信息没检索到
  → 优化方向：加 Reranking 提升 precision，调大 top_k 提升 recall
```

如果四个分数都很高（>0.8），说明你的 RAG 系统质量已经不错了。如果某个分数特别低，那就是你的优化重点。

### 2.6 优化前后对比

RAGAS 的真正威力在于"量化优化效果"。你改了某个参数后，重新跑一遍 RAGAS，对比分数变化：

```python
"""对比优化前后的 RAGAS 分数"""
import json


def run_evaluation(rag, test_data, label="优化前"):
    """跑一轮 RAGAS 评估，返回结果字典"""
    answers, contexts_list = collect_rag_results_sync(rag, test_data["question"])

    dataset = Dataset.from_dict({
        "question": test_data["question"],
        "ground_truth": test_data["ground_truth"],
        "answer": answers,
        "contexts": contexts_list,
    })

    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    )

    print(f"\n=== {label} ===")
    for metric in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
        print(f"  {metric}: {result[metric]:.2f}")

    return dict(result)


# 优化前：top_k=5，无 Reranking
rag_v1 = RAGPipeline(config_top_k=5, use_re_rank=False)
before = run_evaluation(rag_v1, test_data, "优化前")

# 优化后：top_k=8，加 Reranking
rag_v2 = RAGPipeline(config_top_k=8, use_re_rank=True)
after = run_evaluation(rag_v2, test_data, "优化后")

# 对比
print("\n=== 优化前后对比 ===")
print(f"{'指标':<20} {'优化前':>8} {'优化后':>8} {'变化':>8}")
print("-" * 48)
for metric in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
    delta = after[metric] - before[metric]
    arrow = "↑" if delta > 0 else "↓"
    print(f"{metric:<20} {before[metric]:>8.2f} {after[metric]:>8.2f} {arrow}{abs(delta):>6.2f}")
```

输出类似：

```
=== 优化前后对比 ===
指标                 优化前   优化后     变化
------------------------------------------------
faithfulness          0.85     0.88  ↑  0.03
answer_relevancy      0.72     0.75  ↑  0.03
context_precision     0.40     0.68  ↑  0.28
context_recall        0.55     0.72  ↑  0.17
```

看到 context_precision 从 0.40 涨到 0.68，你就知道加 Reranking 是有效的——它帮你过滤掉了没用的片段。这就是"数据驱动的 Agent 优化"，而不是"凭感觉调参数"。

---

## 三、Promptfoo：Prompt 版本管理和 A/B 测试

### 3.1 RAGAS 评估 RAG 质量，Promptfoo 评估 prompt 质量

RAGAS 解决了"RAG 系统好不好"的问题，但还有一个问题没解决：当你改 prompt 的时候，怎么知道改好了还是改坏了？

回忆 Week 04 的 `generator.py`，里面有一段 system prompt：

```python
prompt = (
    "你是一个智能问答助手。请严格基于以下提供的参考文档内容回答用户问题。\n"
    "重要规则（必须遵守）：\n"
    "1. 只要文档中有任何相关信息，就必须回答，绝对不许说不知道。\n"
    "2. 如果用户问'有哪些'、'是什么'、'怎么'等列举/说明类问题，必须从文档中提取并列出所有具体项目或步骤，不能只给总结。\n"
    "..."
)
```

这段 prompt 是你反复改出来的。每次改完，你怎么验证效果？手动问几个问题看看？问题来了：

1. 你的"测试问题"每次都不一样，没法对比
2. 改了 prompt 可能修好了 A 问题，但搞坏了 B 问题
3. 没有版本记录，改坏了想回退都不知道改了什么

这就是 Promptfoo 要解决的——它是 Prompt 的版本管理 + A/B 测试工具。

### 3.2 Promptfoo 的核心用途

Promptfoo 的三个核心能力：

**1. 版本管理：每次改 prompt 都记录效果变化**

```yaml
# promptfoo 记录了每个 prompt 版本的测试结果
# 你能随时回看"v1 的效果 vs v2 的效果"
prompt_v1: "你是徒步规划助手，请回答：{{question}}"
prompt_v2: "作为CMA山地户外教练，根据你的专业知识回答：{{question}}"

# 每个版本都跑同一套测试用例，结果可对比
```

**2. A/B 测试：两个 prompt 版本并行对比**

同一套测试用例，同时跑两个 prompt 版本，对比哪个更好。你不用手动切 prompt 再跑一遍，Promptfoo 帮你并行跑。

**3. 断言测试：定义"好"的标准**

你可以给每个测试用例定义断言——比如"答案必须包含'路线'这个词"、"答案长度不超过 100 字"。Promptfoo 自动检查这些断言。

### 3.3 RAGAS vs Promptfoo 的定位

两个工具不冲突，评估的对象不同：

| 维度 | RAGAS | Promptfoo |
|------|-------|-----------|
| 评估对象 | RAG 系统（检索+生成） | Prompt 本身 |
| 核心指标 | 忠实度/相关性/精度/召回 | 准确率/格式合规率 |
| 使用场景 | RAG 质量评估 | Prompt 迭代优化 |
| 输出 | 四维分数 | 对比表格 |
| 评估方式 | LLM-as-a-judge | 断言 + 人工 review |
| 耗时 | 慢（LLM 评判） | 快（断言检查） |

一句话：**RAGAS 评估"RAG 系统整体好不好"，Promptfoo 评估"prompt 改得对不对"**。两个工具配合使用——先用 Promptfoo 快速迭代 prompt，再用 RAGAS 量化整体 RAG 质量。

### 3.4 Promptfoo 示例

Promptfoo 用 YAML 配置文件定义测试。来看一个完整的配置：

```yaml
# promptfooconfig.yaml — Promptfoo 配置文件

# 定义要对比的多个 prompt 版本
prompts:
  - "你是徒步规划助手，请回答：{{question}}"
  - "作为CMA山地户外教练，根据你的专业知识回答：{{question}}"

# 指定用哪个模型跑
providers:
  - openai:gpt-4o-mini

# 定义测试用例
tests:
  - vars:
      question: "川西3天路线推荐"
    assert:
      - type: contains
        value: "路线"

  - vars:
      question: "四姑娘山海拔"
    assert:
      - type: contains
        value: "6250"

  - vars:
      question: "长穿毕需要几天"
    assert:
      - type: contains
        value: "3"

  - vars:
      question: "贡嘎大环线难度"
    assert:
      - type: llm-rubric
        value: "答案应该提到高海拔和长距离"
```

跑一下：

```bash
npx promptfoo eval
```

Promptfoo 会生成一个对比表格，类似：

```
┌────────────────┬──────────────────┬──────────────────┬────────┐
│ 测试用例        │ Prompt v1        │ Prompt v2        │ 结果    │
├────────────────┼──────────────────┼──────────────────┼────────┤
│ 川西3天路线推荐  │ 长穿毕、四姑娘山  │ 作为CMA教练推荐   │ v1 通过 │
│                │ 二峰等路线        │ 长穿毕            │ v2 通过 │
├────────────────┼──────────────────┼──────────────────┼────────┤
│ 四姑娘山海拔    │ 6250米           │ 海拔6250米        │ 都通过  │
├────────────────┼──────────────────┼──────────────────┼────────┤
│ 长穿毕需要几天   │ 通常3天           │ 3天左右           │ 都通过  │
├────────────────┼──────────────────┼──────────────────┼────────┤
│ 贡嘎大环线难度   │ （没提到高海拔）   │ 高海拔长距离进阶   │ v2 通过│
│                │                  │ 路线              │ v1 失败│
└────────────────┴──────────────────┴──────────────────┴────────┘
```

看这个表格你就知道：v2（CMA 教练人设）在"贡嘎大环线难度"这个问题上表现更好，因为它会主动提到高海拔和长距离。这就是 Promptfoo 的价值——用同一套测试用例，客观对比两个 prompt 版本。

### 3.5 Promptfoo 的工作流

```
写 prompt v1 → 定义测试用例 → 跑 Promptfoo → 看结果
                                              │
改 prompt v2 ←─────────────────────────────────┘
    │
    ▼
跑 Promptfoo → 对比 v1 vs v2 → v2 更好？ → 用 v2 替换 v1
                │                 │
                └─── v2 更差？ ───┘
                         │
                         ▼
                    保留 v1，继续改
```

这个工作流和前端的"改代码 → 跑测试 → 看是否通过"完全一样。Promptfoo 就是 prompt 的单元测试框架。

> **前端类比：** Promptfoo 之于 prompt，就像 Jest 之于代码。你不会"改完代码不跑测试就上线"，同样你也不该"改完 prompt 不跑测试就换上去"。Promptfoo 帮你把 prompt 的测试自动化了。

---

## 四、RAG 质量优化闭环

### 4.1 评估驱动的优化闭环

把 RAGAS 和 Promptfoo 串起来，就形成了一个完整的"评估驱动的优化闭环"：

```
    ┌─────────────────────────────────────────────────┐
    │                                                 │
    ▼                                                 │
 RAGAS 评估                                           │
 （四维指标）                                          │
    │                                                 │
    ▼                                                 │
 发现问题                                              │
 （哪个指标低？）                                       │
    │                                                 │
    ├─ context_precision 低 → 检索了一堆没用的          │
    │     → 优化：加 Reranking（Week 10 会学）         │
    │                                                 │
    ├─ context_recall 低 → 漏了关键信息               │
    │     → 优化：调大 top_k、加 Multi-Query           │
    │                                                 │
    ├─ faithfulness 低 → 在编造                        │
    │     → 优化：加强 prompt 约束                      │
    │     → 用 Promptfoo 对比 prompt 版本              │
    │                                                 │
    └─ answer_relevancy 低 → 答非所问                  │
          → 优化：换更好的模型、调 prompt                │
          → 用 Promptfoo 做 A/B 测试                   │
    │                                                 │
    ▼                                                 │
 优化后 → 再跑 RAGAS → 对比分数变化 ─────────────────┘
```

### 4.2 闭环的核心逻辑

这个闭环的核心是"数据驱动"——每一步优化都有数据支撑：

1. **评估**：用 RAGAS 跑出四维分数，量化当前 RAG 质量
2. **诊断**：根据分数定位问题——是检索坏了还是生成坏了
3. **优化**：针对性地改——调参数、加 Reranking、改 prompt
4. **验证**：再跑 RAGAS，对比分数有没有提升
5. **迭代**：回到第 1 步，持续优化

这个闭环就是"数据驱动的 Agent 优化"。Week 04 的时候你"凭感觉调参数"——改了 chunk_size 看看答案好不好。现在你有了 RAGAS，每改一个参数都能看到四维分数的变化，知道这个改动是好是坏。

### 4.3 和 Day 01-02 的衔接

把今天的 RAGAS 放到 Day 01-02 的评估体系里看：

| 工具 | 评估什么 | 用在哪 |
|------|---------|--------|
| Day 01 通用指标 | 成功率/步数/成本 | 任何 Agent |
| Day 02 Langfuse trace | 调用链可视化 | 定位故障在哪一步 |
| **Day 03 RAGAS** | **RAG 四维指标** | **RAG 系统专项** |
| **Day 03 Promptfoo** | **Prompt 版本对比** | **Prompt 迭代优化** |

Day 01 给你"整体分数"，Day 02 给你"调用链可视化"，Day 03 给你"RAG 专项诊断"。三个工具配合，你的 Agent 评估体系就完整了。

### 4.4 副线：量化 Week 04 的参数影响

Week 04 你调过这些参数：`chunk_size`、`chunk_overlap`、`top_k`。当时只能"凭感觉"判断效果。现在用 RAGAS 可以量化了：

```python
"""对比不同参数对 RAGAS 四维指标的影响"""
# 测试矩阵
configs = [
    {"chunk_size": 300, "top_k": 3, "label": "小chunk+少检索"},
    {"chunk_size": 500, "top_k": 5, "label": "中chunk+中检索"},
    {"chunk_size": 800, "top_k": 8, "label": "大chunk+多检索"},
]

for cfg in configs:
    rag = RAGPipeline(chunk_size=cfg["chunk_size"], top_k=cfg["top_k"])
    result = run_evaluation(rag, test_data, cfg["label"])
    # 记录每个配置的四维分数
    cfg["scores"] = result

# 输出对比表
print(f"{'配置':<20} {'faith':>8} {'relv':>8} {'prec':>8} {'recall':>8}")
print("-" * 56)
for cfg in configs:
    s = cfg["scores"]
    print(f"{cfg['label']:<20} {s['faithfulness']:>8.2f} {s['answer_relevancy']:>8.2f} "
          f"{s['context_precision']:>8.2f} {s['context_recall']:>8.2f}")
```

输出类似：

```
配置                 faith    relv     prec  recall
--------------------------------------------------------
小chunk+少检索        0.82    0.68     0.65    0.45
中chunk+中检索        0.88    0.75     0.55    0.70
大chunk+多检索        0.85    0.78     0.42    0.85
```

看这个表你能得出结论：

- 小 chunk + 少检索：precision 高（检索准）但 recall 低（漏信息）
- 大 chunk + 多检索：recall 高（不漏）但 precision 低（检索一堆没用的）
- 中 chunk + 中检索：比较平衡

这就是"数据驱动的参数调优"——比 Week 04 的"凭感觉"科学得多。

---

## 动手实验

### 🟢 青铜：安装 RAGAS，用 3 个测试问题评估 Week 04 的 RAG

1. `pip install ragas datasets`
2. 准备 3 个测试问题 + 标准答案
3. 运行 Week 04 的 RAG 系统获取答案和检索片段
4. 用 RAGAS 计算四维指标
5. 打印评估报告

```python
# 最小可运行示例
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
from datasets import Dataset

test_data = {
    "question": ["四姑娘山的海拔是多少？"],
    "ground_truth": ["四姑娘山主峰海拔6250米"],
    "answer": ["四姑娘山主峰海拔6250米"],  # 先手动填，后面再接 RAG 系统
    "contexts": [["四姑娘山主峰海拔6250米，位于四川省阿坝州"]],
}

dataset = Dataset.from_dict(test_data)
result = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_precision, context_recall])
print(result)
```

### 🟡 白银：完成 rag_eval.py — 10 个测试问题 + 四维指标 + 优化前后对比

1. 准备 10 个测试问题 + 标准答案（覆盖不同类型：事实型、列举型、推理型）
2. 接入 Week 04 的 RAGPipeline，自动收集 answer 和 contexts
3. 跑 RAGAS 评估，输出四维指标
4. 改一个参数（如 top_k 从 5 改成 8），重新跑评估
5. 输出优化前后对比表
6. 把结果保存到 `rag_eval_result.json`

```python
# 白银实验的测试集示例
test_data = {
    "question": [
        "川西有哪些进阶徒步路线？",
        "四姑娘山的海拔是多少？",
        "长穿毕路线需要几天？",
        "贡嘎大环线的难度如何？",
        "什么季节适合去川西徒步？",
        "川西徒步需要什么装备？",
        "四姑娘山有几座山峰？",
        "长穿毕路线要翻几个垭口？",
        "川西徒步的高反风险大吗？",
        "贡嘎山的海拔是多少？",
    ],
    "ground_truth": [
        # 对应的标准答案
        "长穿毕、四姑娘山二峰、贡嘎大环线等",
        "四姑娘山主峰海拔6250米",
        "长穿毕通常需要3天",
        "贡嘎大环线属于高难度路线",
        "5-10月适合川西徒步",
        "冲锋衣、登山杖、睡袋等",
        "四姑娘山有四座山峰",
        "长穿毕要翻越三个垭口",
        "海拔3000以上有高反风险",
        "贡嘎山海拔7556米",
    ],
}
```

### 🔴 王者：用 Promptfoo 对比两个 system_prompt 版本的效果

1. 安装 Promptfoo：`npm install -g promptfoo`
2. 写 `promptfooconfig.yaml`，定义两个 prompt 版本（比如"普通助手"vs"CMA 教练人设"）
3. 定义 10 个测试用例 + 断言规则
4. 跑 `npx promptfoo eval`，生成对比报告
5. 跑 `npx promptfoo view`，在浏览器里看可视化结果
6. 写一份 A/B 测试报告，包含：
   - 两个 prompt 版本的完整文本
   - 每个测试用例的通过/失败情况
   - 哪个版本更好，为什么
   - 如果 v2 更好，把 v2 应用到 Week 04 的 generator.py 里

```yaml
# promptfooconfig.yaml 示例
prompts:
  - "你是徒步规划助手，请回答：{{question}}"
  - "作为CMA山地户外教练，根据你的专业知识回答：{{question}}"

providers:
  - openai:gpt-4o-mini

tests:
  - vars:
      question: "川西3天路线推荐"
    assert:
      - type: contains
        value: "路线"
  - vars:
      question: "四姑娘山海拔"
    assert:
      - type: contains
        value: "6250"
  # ... 更多测试用例
```

---

## 踩坑记录 🕳️

### 坑 1：RAGAS 评估本身消耗 token

RAGAS 用 LLM-as-a-judge 来计算指标——它会让 LLM 判断"答案是不是基于上下文""检索的片段有没有用"。这意味着每评估一条数据，RAGAS 都会调用多次 LLM。

**问题：** 10 条测试数据，四维指标全开，可能消耗几万 token。如果你用 GPT-4 这种贵的模型当 judge，费用不低。

**解决：**
- 评估时用便宜的模型（如 gpt-4o-mini）当 judge，不用 GPT-4
- 测试集不要太大，10-20 条够用
- 开发阶段可以先只跑 2 个指标（faithfulness + context_precision），上线前再全跑

### 坑 2：context_recall 需要标准答案

context_recall 的计算依赖 `ground_truth`（标准答案）——它需要对比"标准答案里的信息"和"检索到的 contexts"的重合度。没有标准答案，这个指标算不出来。

**问题：** 标注标准答案的成本很高。10 个问题还好，100 个问题就得花一天标注。

**解决：**
- 先标注 10-20 个核心问题，覆盖主要场景
- 用 LLM 辅助生成 ground_truth 初稿，人工审核修正
- 如果实在没条件标注，可以先只看 faithfulness 和 context_precision——这两个不需要 ground_truth

### 坑 3：RAGAS 的版本更新快，API 可能变化

RAGAS 是一个活跃的项目，版本更新很快。0.1.x 和 0.2.x 的 API 可能不一样——import 路径变了、参数名变了、甚至指标的计算方式都变了。

**问题：** 你按教程写的代码，装了新版本就跑不通。

**解决：**
- `pip install ragas==0.1.x` 锁定版本
- 看 RAGAS 官方文档对应你安装的版本：https://docs.ragas.io
- 遇到 import 报错，先查是不是版本问题

### 坑 4：Promptfoo 的 YAML 配置格式有学习成本

Promptfoo 用 YAML 配置，支持的功能很多（断言、变量、provider、多 prompt 对比），初学者容易写错。

**常见错误：**

```yaml
# 错误：indent 不对
tests:
- vars:
    question: "xxx"

# 正确：tests 下面的元素要缩进
tests:
  - vars:
      question: "xxx"
```

**解决：**
- 从官方示例复制改，不要从零写
- 用 `npx promptfoo eval --help` 看可用参数
- 配置写错时 Promptfoo 会报错提示行号，按提示修

### 坑 5：contexts 格式不匹配

RAGAS 要求 `contexts` 是 `list[list[str]]`——每个问题对应一个片段列表，每个片段是一个字符串。但 Week 04 的 RAGPipeline 返回的 sources 是 `list[dict]`（每个 dict 有 text、metadata 等字段）。

**问题：** 直接把 sources 传给 RAGAS 会报格式错误。

**解决：** 做一层转换：

```python
# Week 04 的格式: [{"text": "...", "metadata": {...}}, ...]
# RAGAS 需要的格式: ["...", "...", ...]
contexts = [s["text"] for s in result["sources"]]
```

---

## 副线笔记

### 对比 Week 04 基础 RAG 的检索质量

Week 04 的时候，你调过 `chunk_size`、`top_k` 这些参数。当时怎么判断效果？大概是"问几个问题看看答案好不好"。这种方式的问题在于：

1. **主观性强**：你觉得"还行"的答案，别人可能觉得"漏了关键信息"
2. **不可复现**：你这次问了 3 个问题，下次问了另外 3 个，没法对比
3. **看不到细节**：你只看到最终答案，不知道是检索坏了还是生成坏了

现在用 RAGAS 量化 Week 04 的 RAG 表现，看看 `chunk_size`、`top_k` 等参数对四维指标的影响：

| 参数变化 | context_precision | context_recall | 原因 |
|---------|-------------------|----------------|------|
| chunk_size 小 → 大 | 先升后降 | 持续升 | 太小信息碎片化，太大精度降 |
| top_k 小 → 大 | 持续降 | 持续升 | 检索多了不漏但垃圾也多了 |
| 加 Reranking | 升 | 不变 | 重排过滤了没用的，但不增加新信息 |

这比 Week 04 "凭感觉调参数"科学得多。你甚至可以画一张参数-指标的折线图，找到"精度和召回的最佳平衡点"——这就像机器学习里的 Precision-Recall 曲线。

### RAGAS 和 Langfuse 的配合

Day 02 学的 Langfuse 是 trace 工具，RAGAS 是评估工具。两者可以配合：

- **Langfuse**：记录 RAG 系统的完整调用链（embedding → retrieve → generate），定位"哪一步慢了"
- **RAGAS**：计算 RAG 系统的四维指标，定位"哪个环节质量差"

一个管"性能和故障"，一个管"质量"。Langfuse 告诉你"检索花了 2 秒"，RAGAS 告诉你"检索回来的东西只有 40% 有用"。

### Promptfoo 和 Git 的关系

Promptfoo 的版本管理不是替代 Git——它管的是"prompt 的效果版本"，不是"代码的版本"。你的 prompt 放在代码里（如 generator.py），代码用 Git 管。但 Git 只能告诉你"改了什么"，不能告诉你"改了之后效果怎么样"。Promptfoo 补的就是这一环——每次改 prompt，用同一套测试用例跑一遍，量化效果变化。

---

## 检查清单

- [ ] 理解 RAGAS 四维指标（faithfulness / answer_relevancy / context_precision / context_recall）各自测什么
- [ ] 能根据四维分数诊断 RAG 问题出在检索还是生成
- [ ] 用 RAGAS 评估了 Week 04 的 RAG 系统，拿到了四维分数
- [ ] 理解 Promptfoo 的用途——prompt 版本管理和 A/B 测试
- [ ] 理解 RAGAS 评估 RAG 系统、Promptfoo 评估 prompt 本身的定位差异
- [ ] 完成了 rag_eval.py（青铜或白银实验）
- [ ] 理解"评估 → 诊断 → 优化 → 再评估"的闭环

---

## 下课预告

> **Day 04 — Shadow Testing + 回归测试 + CI 集成。** 今天我们用 RAGAS 量化了 RAG 质量，用 Promptfoo 对比了 prompt 版本。但还有一个问题：你在本地改好了 Agent，上线后怎么保证不退化？明天学 Shadow Testing——新旧 Agent 并行跑生产流量，对比输出差异。还有回归测试——每次改 Agent 都跑一套固定测试，防止"修好 A 搞坏 B"。最终目标是把 Agent 测试接入 CI，每次提交代码自动跑评估。这比 Day 03 的"手动跑 RAGAS"更进一步——让评估自动化。
