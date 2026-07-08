# Day 04 — Agentic RAG 深度：冲突处理 + Reranking

## 学习目标

Day 02-03 我们搭好了提取 Agent + Reflection——护工录一段语音，系统就能转成一份经过质检的结构化 `CareRecord`。但养老场景还有个刚需：护工记录今天状况时，系统得会"翻旧账"。比如护工说"王奶奶今天血压 138/85，和上次差不多"，系统得知道"上次"是多少；家属问"王奶奶最近一周血压趋势如何"，系统得检索出这一周的记录做对比；今天体温 37.8 算不算异常，得和最近几天的体温曲线对照才说得清。这就是 Agentic RAG 的用武之地——Week 04 我们学的 2-Step RAG 是"检索→生成"一条固定流水线，而 Agentic RAG 让 Agent 自己决定什么时候检索、检索什么、检索回来冲突了怎么办。

但 Agentic RAG 不是银弹，它带来三个新难题：检索回来的历史记录可能互相打架（昨天记的血压是 135/85，前天记的是 150/95，到底信哪个？）；向量检索 top-K 召回回来一堆语义相似但实际无关的记录（"王奶奶头晕"和"王奶奶头有点晕，但量了血压正常"哪个更该排前面？）；有些问题根本不该查向量库（"今天天气怎么样"该调天气 API）。今天就把这三个难题一次性解决——冲突处理、Cross-Encoder Reranking、动态路由。这三个分别对应面试 Q13（检索冲突）、Q16（提升检索准确度）、Q15（动态路由），全是高频题。

学完今天你能：

1. 说清 2026 年三种 RAG 架构（2-Step RAG / Agentic RAG / Hybrid RAG）的差异和选型，知道为什么养老场景该用 Hybrid RAG
2. 掌握冲突处理（面试 Q13）的两大策略：元数据加权（时间越近权重越高）+ 多源验证，能写出 `conflict_resolver` 解决"同一老人两条历史记录血压不一致"的问题
3. 理解 Cross-Encoder Reranking（面试 Q16），能说清 Bi-Encoder（粗筛）和 Cross-Encoder（精排）的区别，用 `BAAI/bge-reranker-v2-m3` + `ContextualCompressionRetriever` 给 Qdrant 检索结果做精排
4. 实现动态路由（面试 Q15）：实时问题调 API、历史问题查向量库，跑通整合三大能力的 `agentic_rag.py`

---

## 一、三种 RAG 架构（2026 最新）

### 1.1 从 Week 04 的 2-Step RAG 说起

Week 04 我们学的 RAG 是最经典的"两步走"——把用户问题 embed 一下，去向量库捞 top-K，把这堆文档拼进 prompt 让 LLM 生成答案：

```
用户问题 → [Embedding] → 向量库检索 top-K → [拼 prompt] → LLM 生成答案
```

这条流水线的好处是**高可控、低延迟**——流程固定，没有 LLM 参与决策，跑一遍就出结果。但它的短板在养老场景暴露得很明显：

- 护工问"王奶奶最近血压怎么样"——检索回来一堆"王奶奶"相关记录，但可能混进"王奶奶今天吃饭挺好"这种和血压无关的
- 护工问"今天该提醒李爷爷吃药吗"——这根本不需要检索历史，该查的是"今天的服药排程表"（结构化数据/API）
- 检索回来昨天血压 135/85、前天 150/95 两条冲突记录，2-Step RAG 直接全塞给 LLM，LLM 可能瞎编一个"平均 142/90"

2-Step RAG 把检索当成"必经的一步"，不管该不该查、查回来对不对、冲突了怎么办，统统不管。这就是 Agentic RAG 要解决的核心矛盾。

### 1.2 Agentic RAG：把检索变成 tool

Agentic RAG 的核心转变是——**检索不再是固定流水线的一环，而是 Agent 工具箱里的一把工具**。Agent 自己判断：这个问题需不需要检索？检索什么关键词？检索回来够不够？冲突了怎么办？

```
用户问题 → Agent 思考
              ├─ 需要历史记录？→ 调 search_history 工具（向量库检索）
              ├─ 需要实时信息？→ 调 query_weather 工具（外部 API）
              ├─ 检索结果冲突？→ 调 resolve_conflicts 工具
              ├─ 够了 → 综合生成答案
              └─ 不够 → 换个关键词再检索
```

> **前端类比：** 2-Step RAG 就像前端的"固定中间件链"——每个请求必须依次过 A→B→C，不管需不需要。Agentic RAG 就像 Express 的 `app.use` 按需调用——路由处理器自己决定要不要查数据库、要不要调缓存、要不要请求下游服务。把"检索"从"必经之路"降级成"可选工具"，灵活度立刻上来。

### 1.3 Hybrid RAG：二者混合 + 中间校验

2026 年工业界的主流其实是 Hybrid RAG——2-Step 的高效 + Agentic 的灵活，中间插入三个校验步骤兜底：

| 校验环节 | 在哪一步 | 干什么 | 养老场景例子 |
|---------|---------|--------|-------------|
| Query Enhancement | 检索前 | 改写/扩展用户问题 | "上次记录"→扩展成"王奶奶最近 7 天的护理记录" |
| Retrieval Validation | 检索后 | 检查召回质量，不够就重查 | 检索回来全是"吃饭"记录，和"血压"无关→换个 query 重查 |
| Answer Validation | 生成后 | 检查答案有没有幻觉、有没有引用冲突 | LLM 说"血压正常"但检索结果里有 150/95→打回重生成 |

### 1.4 三种架构对比

| 维度 | 2-Step RAG | Agentic RAG | Hybrid RAG |
|------|-----------|-------------|------------|
| **检索方式** | 固定检索 top-K | Agent 自主决定是否/如何检索 | 固定检索 + Agent 兜底校验 |
| **控制流** | 直线流水线 | Agent 循环决策（可多轮检索） | 流水线 + 中间校验拦截 |
| **延迟** | 低（一次检索） | 高（多轮 LLM 决策） | 中（多数走快路径，少数兜底） |
| **可控性** | 高（流程固定） | 低（Agent 行为不确定） | 中（校验步骤兜底） |
| **冲突处理** | 无（全塞给 LLM） | Agent 自行判断 | 显式 conflict_resolver |
| **准确度** | 一般 | 较高（但可能跑偏） | 高（检索+校验双重把关） |
| **适用场景** | 简单问答、低延迟 | 复杂多跳推理 | 生产级、对准确度敏感 |
| **养老场景** | 不够用（冲突无解） | 灵活但成本高 | ✅ 本周选它 |

> **选型结论：** 养老场景对准确度要求极高（一个错误的血压判断可能误导用药），但又不能让 Agent 无限循环（护工等不了）。所以本周用 **Hybrid RAG**——主路径走 2-Step 的快速检索 + Reranking，冲突时显式调 `conflict_resolver`，实时问题走动态路由。既保证速度，又兜住准确度。

---

## 二、冲突处理（面试 Q13）

### 2.1 场景：历史记录会打架

养老系统跑久了，向量库里同一个老人会攒下一堆历史记录。检索"王奶奶最近血压"时，可能捞回来这几条：

```
记录 A（3 天前）：血压 150/95，护工小李记录，备注"老人有点激动"
记录 B（1 天前）：血压 135/85，护工小张记录，备注"刚量完，老人平静"
记录 C（今天）：  血压 138/88，护工小李记录
```

A 和 B 差了 15/10，到底信哪个？直接把三条塞给 LLM，它可能"取平均"输出 141/89——这是错的，血压不是这么算的。这就是面试 Q13 的核心：**检索到多条冲突信息时，怎么保证答案的可靠性？**

### 2.2 解决方案：元数据加权 + 多源验证

养老场景有个朴素的先验：**越近的记录越可信，越多人交叉验证的越可信**。我们把这两条做成显式策略：

**策略一：元数据加权（时间衰减）。** 每条记录存进向量库时，metadata 里带上 `recorded_at`（记录时间）和 `source`（护工）。检索回来后，按时间算权重——越近权重越高，可以用指数衰减 `w = exp(-Δt/τ)`，其中 Δt 是距今天数，τ 是时间常数（比如 7 天，意味着一周前的记录权重衰减到 e^-1≈37%）。

**策略二：多源验证。** 如果两条记录数值相近且来自不同护工，置信度更高（交叉验证）；如果只有一条记录或都来自同一护工，置信度打折扣。冲突时优先采信"多源 + 近期"的记录。

> **前端类比：** 这就像前端做"数据融合"——多个 API 返回了同一资源的不同版本，你按"最新更新时间"和"来源可信度"加权合并，而不是简单取平均或取最后一条。养老记录的"时间"就是"更新时间"，"护工"就是"来源"。

### 2.3 conflict_resolver 代码

```python
"""conflict_resolver.py — 历史记录冲突处理（面试 Q13）
策略：元数据加权（时间衰减）+ 多源验证"""
import math
from datetime import datetime, timedelta
from typing import Any


# 时间常数：7 天前的记录权重衰减到约 37%
TIME_DECAY_TAU_DAYS = 7.0


def time_weight(recorded_at: str, now: datetime, tau_days: float = TIME_DECAY_TAU_DAYS) -> float:
    """计算时间衰减权重。越近权重越高，指数衰减。
    recorded_at: ISO 格式时间字符串，如 '2026-07-05T10:30:00'"""
    recorded = datetime.fromisoformat(recorded_at)
    delta_days = max((now - recorded).total_seconds() / 86400, 0.0)
    return math.exp(-delta_days / tau_days)  # 指数衰减


def source_weight(records: list[dict]) -> dict:
    """多源验证：统计每条记录被多少个不同来源交叉验证。
    数值相近（容差内）且来源不同的记录互相增强置信度。"""
    # 按数值相近性分组（这里以血压为例，容差 ±5mmHg 算相近）
    groups: list[list[int]] = []  # 每组存记录的下标
    for i, r in enumerate(records):
        bp = r.get("blood_pressure")  # 形如 "150/95"
        if not bp:
            continue
        sys_val = int(bp.split("/")[0])
        placed = False
        for g in groups:
            ref_bp = records[g[0]].get("blood_pressure")
            if ref_bp and abs(int(ref_bp.split("/")[0]) - sys_val) <= 5:
                g.append(i)            # 数值相近，归入同组（交叉验证）
                placed = True
                break
        if not placed:
            groups.append([i])
    # 同组里来源（护工）越多，每条记录置信度越高
    weights = {i: 1.0 for i in range(len(records))}
    for g in groups:
        unique_sources = {records[i].get("worker", "unknown") for i in g}
        boost = 1.0 + 0.2 * (len(unique_sources) - 1)  # 每多一个独立来源 +0.2
        for i in g:
            weights[i] *= boost
    return weights


def resolve_conflicts(records: list[dict], now: datetime | None = None) -> dict:
    """解决历史记录冲突，返回最可信的记录 + 冲突分析。
    records: 检索回来的历史记录列表，每条含 blood_pressure/recorded_at/worker 等字段"""
    if not records:
        return {"resolved": None, "conflict": False, "reason": "无历史记录"}
    now = now or datetime.now()

    scored = []
    tw = [time_weight(r["recorded_at"], now) for r in records]
    sw = source_weight(records)
    for i, r in enumerate(records):
        final_score = tw[i] * sw[i]              # 时间权重 × 来源权重
        scored.append((i, r, final_score, tw[i], sw[i]))

    scored.sort(key=lambda x: x[2], reverse=True)  # 按综合得分降序
    best_idx, best_rec, best_score, *_ = scored[0]

    # 判定是否冲突：数值极差超过阈值就算冲突
    bps = [r.get("blood_pressure") for r in records if r.get("blood_pressure")]
    conflict = False
    if len(bps) >= 2:
        systolics = [int(bp.split("/")[0]) for bp in bps]
        if max(systolics) - min(systolics) > 10:   # 收缩压极差 >10 视为冲突
            conflict = True

    return {
        "resolved": best_rec,         # 最可信记录
        "score": round(best_score, 3),
        "conflict": conflict,         # 是否检测到冲突
        "all_ranked": [               # 全部记录的排序与得分（供 Agent 解释）
            {"record": r, "score": round(s, 3), "time_w": round(tw_i, 3), "source_w": round(sw_i, 3)}
            for (i, r, s, tw_i, sw_i) in scored
        ],
        "reason": (
            f"采用最近且多源验证的记录（综合得分 {best_score:.3f}）。"
            + ("检测到历史血压存在 >10mmHg 波动，已按时间衰减+来源验证排序。"
               if conflict else "历史记录一致性良好。")
        ),
    }


if __name__ == "__main__":
    demo_records = [
        {"blood_pressure": "150/95", "recorded_at": "2026-07-05T10:00:00", "worker": "小李"},
        {"blood_pressure": "135/85", "recorded_at": "2026-07-07T09:00:00", "worker": "小张"},
        {"blood_pressure": "138/88", "recorded_at": "2026-07-08T08:00:00", "worker": "小李"},
    ]
    result = resolve_conflicts(demo_records, now=datetime(2026, 7, 8, 9, 0))
    print(f"是否冲突: {result['conflict']}")
    print(f"最可信记录: {result['resolved']}")
    print(f"原因: {result['reason']}")
```

关键设计：`resolve_conflicts` 不只是返回一个"答案"，还返回 `all_ranked`（全部记录的排序与得分）和 `reason`（解释）。这很重要——Agentic RAG 里 Agent 拿到冲突分析后，能向护工解释"为什么我采信今天的 138/88 而不是前天的 150/95"，而不是黑盒地丢一个数字出来。养老场景的可解释性和准确性同等重要。

> **面试加分项：** 面试官问 Q13 时，主动提一句"冲突不只是'选哪个'，还要让 Agent 能解释'为什么选这个'"。可解释性在医疗/养老这类高风险场景是硬需求，不是可选项。

---

## 三、Cross-Encoder Reranking（面试 Q16）

### 3.1 为什么要 Reranking

向量检索（Qdrant）用 Bi-Encoder——把 query 和 document 各自独立编码成向量，算余弦相似度召回 top-K。它快，能在百万级库里毫秒返回。但它"粗"：query 和 document 是**独立编码**的，二者之间的细粒度交互关系（某个词在特定上下文的重要程度）捕捉不到。结果就是 top-K 里混进一堆"语义沾边但实际不答所问"的记录。

养老场景的典型翻车：护工问"王奶奶今天血压正常吗"，向量检索 top-5 召回——

```
1. 王奶奶今天吃饭挺好（语义沾"王奶奶今天"，但和血压无关）❌
2. 王奶奶昨天血压 135/85（沾"王奶奶血压"，但不是今天）⚠️
3. 王奶奶今天血压 138/88（正解）✅
4. 王奶奶上周说头晕（沾"王奶奶"，无关）❌
5. 王奶奶今天情绪平静（沾"王奶奶今天"，无关）❌
```

Bi-Encoder 把正解排到了第 3。如果只取 top-3 喂给 LLM，第 1 条"吃饭挺好"会严重干扰生成质量。Reranking 就是在 Bi-Encoder 粗排之后，加一道 Cross-Encoder 精排，把正解顶到第 1。

### 3.2 Bi-Encoder vs Cross-Encoder

| 维度 | Bi-Encoder（向量检索） | Cross-Encoder（Reranking） |
|------|----------------------|--------------------------|
| **编码方式** | query 和 doc **独立**编码成向量 | query 和 doc **拼接在一起**送入模型 |
| **交互层级** | 浅（只算两个向量的相似度） | 深（每个 token 层级 cross-attention） |
| **准确度** | 中（粗筛） | 高（精排） |
| **速度** | 极快（向量可预计算，毫秒级） | 慢（每对都要前向传播） |
| **用途** | 从百万级库里召回 top-K | 从 top-K 里精排出 top-N |
| **前端类比** | 关键词初筛（filter） | 人工逐条审核（map + sort） |
| **养老场景角色** | Qdrant 粗排 top-20 | BGE-Reranker 精排 top-3 |

> **前端类比：** 这就像电商搜索——Bi-Encoder 是搜索引擎的"粗筛"（按关键词和商品标签先捞几百个候选），Cross-Encoder 是"精排"（对这几百个候选逐个算和搜索词的真实相关度，把最该排前面的顶上去）。两段式是因为粗筛必须快（百万级），精排必须准（只对几十个算），各取所长。

### 3.3 BGE-Reranker-v2-m3 介绍

Reranking 模型首选 **`BAAI/bge-reranker-v2-m3`**——智源研究院（BAAI）开源的多语言重排模型。选它三个理由：一是多语言，中文养老场景表现好；二是开源免费，本地部署零成本；三是和 BGE 系列的 embedding（`bge-m3`）配套，检索+重排一条龙生态完整。它的本质是个 Cross-Encoder——把 `(query, document)` 拼成 `[CLS] query [SEP] document [SEP]` 喂给模型，输出一个相关度分数，分数越高越相关。

### 3.4 完整代码：Qdrant + Cross-Encoder Reranking

```python
"""reranking.py — Cross-Encoder Reranking（面试 Q16）
流程：Qdrant 向量召回 top-K（粗排）→ CrossEncoderReranker 重排 top-N（精排）→ 生成"""
from langchain_qdrant import QdrantVectorStore
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain.retrievers import ContextualCompressionRetriever
from langchain_huggingface import HuggingFaceEmbeddings
from qdrant_client import QdrantClient


# 1. Embedding 模型（和入库时保持一致，用 BGE-m3）
embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")

# 2. Qdrant 向量库（base retriever，做粗排 top-K）
client = QdrantClient(path="./qdrant_data")  # 本地嵌入式；生产用 host=..., port=...
base_retriever = QdrantVectorStore(
    client=client,
    collection_name="care_records",
    embedding=embeddings,
).as_retriever(search_kwargs={"k": 20})  # 粗排：先召回 top-20

# 3. Cross-Encoder Reranker（做精排 top-N）
model = HuggingFaceCrossEncoder(model_name="BAAI/bge-reranker-v2-m3")
compressor = CrossEncoderReranker(model=model, top_n=3)  # 精排：只留最相关的 3 条

# 4. 组装：粗排 → 精排
compression_retriever = ContextualCompressionRetriever(
    base_compressor=compressor,
    base_retriever=base_retriever,
)

# 使用：一行调用，返回精排后的 top-3
docs = compression_retriever.invoke("王奶奶今天血压正常吗")
for i, doc in enumerate(docs, 1):
    print(f"{i}. (score={doc.metadata.get('relevance_score', '?')}) {doc.page_content[:60]}")
```

注意 2026 年的 import 路径：Qdrant 用 `langchain_qdrant` 包里的 `QdrantVectorStore` 类（不是旧版 `langchain_community.vectorstores.Qdrant`，那个已废弃）；Cross-Encoder 用 `langchain_community.cross_encoders.HuggingFaceCrossEncoder` + `langchain.retrievers.document_compressors.CrossEncoderReranker` + `langchain.retrievers.ContextualCompressionRetriever` 三件套。`ContextualCompressionRetriever` 的作用是"把 base_retriever 召回的文档，用 compressor 压缩/重排"——Reranker 就是一种 compressor。

### 3.5 粗排→精排流程图

```
用户问题："王奶奶今天血压正常吗"
   │
   ▼
┌──────────────────────────────────────────────┐
│  Qdrant 向量召回（Bi-Encoder 粗排）            │
│  bge-m3 把 query 编码 → 余弦相似度 → top-20    │
│  快但粗：可能混进"吃饭挺好""上周头晕"等无关项   │
└──────────────────────────────────────────────┘
   │  top-20 候选
   ▼
┌──────────────────────────────────────────────┐
│  CrossEncoderReranker 精排                    │
│  bge-reranker-v2-m3 把 (query, doc) 逐对前向   │
│  算每条候选和 query 的真实相关度分数            │
│  慢但准：能识别"今天血压"和"昨天血压"的区别      │
└──────────────────────────────────────────────┘
   │  按 score 降序，只留 top-3
   ▼
┌──────────────────────────────────────────────┐
│  1. 王奶奶今天血压 138/88（正解，被顶到第1）✅  │
│  2. 王奶奶昨天血压 135/85（沾边，排第2）⚠️     │
│  3. 王奶奶上周血压记录（参考，排第3）            │
└──────────────────────────────────────────────┘
   │  top-3 精排结果
   ▼
交给 LLM 生成答案（或交给 conflict_resolver 处理冲突）
```

---

## 四、动态路由（面试 Q15）

### 4.1 不是所有问题都该查向量库

护工和家属会问两类截然不同的问题：

- **历史类**："王奶奶最近一周血压趋势""上次她头晕是什么时候"——这些该查向量库（历史 CareRecord）
- **实时类**："今天天气怎么样""现在几点了""今天的排班是谁"——这些查向量库纯属浪费，该调对应 API

如果无脑把所有问题都走 RAG，实时问题会检索出一堆语义沾边的历史记录，LLM 基于这些"过期信息"硬答，必然幻觉。动态路由（Q15）就是让 Agent 在检索前先判断"这个问题该走哪条路"。

### 4.2 动态路由的实现思路

两种实现方式：

1. **LLM 路由**：让一个轻量 LLM 判断问题类型，输出 `route: "history" | "realtime" | "chitchat"`。灵活但慢（多一次 LLM 调用）。
2. **关键词/规则路由**：用关键词匹配快速分流。快但死板，覆盖不全。

养老场景的问题类型其实有限（历史记录 / 实时天气 / 排班 / 闲聊），用 LLM 路由更稳，且可以复用主 Agent 的判断能力。今天用 `@tool` 把"路由判断"也做成 Agent 工具箱的一员——Agent 自己决定调哪个工具，路由就隐式完成了。

> **前端类比：** 动态路由就像前端的请求拦截器——每个请求进来先判断"是走 CDN 缓存、走后端 API、还是走 BFF 聚合层"。你不会把所有请求都打到一个后端，而是按请求类型分流。Agentic RAG 里 Agent 就是这个拦截器，按问题类型分流到不同工具。

### 4.3 dynamic_router 代码

```python
"""dynamic_router.py — 动态路由（面试 Q15）
把检索和 API 都封装成 tool，让 Agent 自主决定调哪个"""
from langchain.tools import tool


@tool
def query_weather_api(city: str) -> str:
    """查询实时天气。当问题涉及"今天天气""现在几度""下雨吗"等实时信息时使用。
    city 为城市名。"""
    # 模拟天气 API（生产接和风天气/OpenWeather）
    mock = {"北京": "晴 28℃", "上海": "多云 26℃", "广州": "雷阵雨 30℃"}
    return mock.get(city, f"{city} 暂无天气数据")


@tool
def query_schedule_api(date: str) -> str:
    """查询护工排班。当问题涉及"今天谁值班""排班""谁来看护"等实时排班信息时使用。
    date 为日期，格式 YYYY-MM-DD。"""
    mock = {
        "2026-07-08": "白班：小李、小张；夜班：老王",
        "2026-07-09": "白班：小李、老王；夜班：小张",
    }
    return mock.get(date, f"{date} 暂无排班数据")


@tool
def search_history(query: str) -> str:
    """检索历史护理记录。当问题涉及老人历史状况、体征趋势、过往异常、
    "上次""最近""之前"等历史信息时使用。query 为检索关键词。"""
    # 实际接 compression_retriever（见第三节），这里返回占位
    docs = compression_retriever.invoke(query) if globals().get("compression_retriever") else []
    if not docs:
        return "未检索到相关历史记录"
    return "\n".join(f"- {d.page_content}" for d in docs)


# 把三类工具都挂给 Agent，路由判断由 Agent 内部的 LLM 完成
ROUTING_TOOLS = [query_weather_api, query_schedule_api, search_history]
```

关键设计：动态路由**不是单独写一个 `if/else` 分流函数**，而是把每条数据源都封装成 `@tool`，挂进 Agent 工具箱。Agent 看到"今天天气"会自己选 `query_weather_api`，看到"上次血压"会自己选 `search_history`——路由决策隐式发生在 Agent 的工具选择环节。这就是 Agentic RAG "把检索降级成 tool" 的精髓：**路由不再是硬编码的 if/else，而是 Agent 基于语义自主选择的工具调用**。

---

## 五、完整 agentic_rag.py

把前三节的冲突处理、Reranking、动态路由整合成一个完整可运行的文件。这个文件接在 Day 02-03 之后——输入是用户的自然语言问题（护工/家属提问），输出是基于历史记录 + 实时信息 + 冲突分析生成的可信答案。

```python
"""agentic_rag.py — 养老护工智能记录系统 Day 04 产出

整合三大能力：
  1. 冲突处理（conflict_resolver）：元数据加权 + 多源验证
  2. Cross-Encoder Reranking（BGE-Reranker-v2-m3）：粗排→精排
  3. 动态路由：实时问题调 API，历史问题查向量库

依赖（2026 版本）：
  pip install langchain langgraph langchain-qdrant langchain-huggingface \
              langchain-community qdrant-client sentence-transformers pydantic

运行：
  python agentic_rag.py
"""
from __future__ import annotations

import json
import math
import operator
from datetime import datetime, timedelta
from typing import Annotated, Optional

from pydantic import BaseModel, Field

from langchain.agents import create_agent
from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langgraph.checkpoint.memory import InMemorySaver

# ---------- 向量库与重排 ----------
from langchain_qdrant import QdrantVectorStore
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain.retrievers import ContextualCompressionRetriever
from langchain_huggingface import HuggingFaceEmbeddings

# ---------- Qdrant 客户端与过滤 ----------
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)


# ============================================================
# 一、配置与常量
# ============================================================

COLLECTION_NAME = "care_records"
EMBEDDING_MODEL = "BAAI/bge-m3"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
QDRANT_PATH = "./qdrant_data"
VECTOR_SIZE = 1024  # bge-m3 输出维度
RECALL_K = 20      # 粗排召回数
RERANK_TOP_N = 3   # 精排保留数
TIME_DECAY_TAU = 7.0  # 时间衰减常数（天）


# ============================================================
# 二、数据模型
# ============================================================

class CareRecordDoc(BaseModel):
    """存进向量库的护理记录（含元数据，供冲突处理加权用）"""
    patient_name: str = Field(description="老人姓名")
    content: str = Field(description="记录正文")
    blood_pressure: Optional[str] = Field(default=None, description="血压，如 '135/85'")
    temperature: Optional[float] = Field(default=None, description="体温℃")
    recorded_at: str = Field(description="记录时间 ISO 格式")
    worker: str = Field(description="护工姓名")
    symptoms: list[str] = Field(default_factory=list, description="症状列表")


class RankedRecord(BaseModel):
    """带得分的历史记录，供冲突排序"""
    record: dict
    score: float
    time_weight: float
    source_weight: float


class ConflictResult(BaseModel):
    """冲突处理结果"""
    resolved: Optional[dict] = Field(default=None, description="最可信记录")
    conflict: bool = Field(default=False, description="是否检测到冲突")
    reason: str = Field(default="", description="采信原因（供 Agent 解释）")
    all_ranked: list[dict] = Field(default_factory=list, description="全部记录排序")


# ============================================================
# 三、Qdrant 向量库初始化与写入
# ============================================================

def init_qdrant_store(embeddings: Embeddings) -> QdrantVectorStore:
    """初始化 Qdrant 向量库（本地嵌入式），返回 QdrantVectorStore。"""
    client = QdrantClient(path=QDRANT_PATH)
    # 若 collection 不存在则创建
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
    return QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embeddings,
    )


def add_care_records(store: QdrantVectorStore, records: list[CareRecordDoc]) -> None:
    """把护理记录写入向量库（content 做 embedding，元数据存 metadata）。"""
    texts = [r.content for r in records]
    metadatas = [
        {
            "patient_name": r.patient_name,
            "blood_pressure": r.blood_pressure,
            "temperature": r.temperature,
            "recorded_at": r.recorded_at,
            "worker": r.worker,
            "symptoms": json.dumps(r.symptoms, ensure_ascii=False),
        }
        for r in records
    ]
    store.add_texts(texts=texts, metadatas=metadatas)


def build_metadata_filter(patient_name: str) -> Filter:
    """构建 Qdrant 元数据过滤器——按老人姓名过滤。
    用 qdrant_client.models.Filter/FieldCondition/MatchValue（2026 API）。"""
    return Filter(
        must=[
            FieldCondition(
                key="metadata.patient_name",
                match=MatchValue(value=patient_name),
            )
        ]
    )


# ============================================================
# 四、冲突处理（面试 Q13）：元数据加权 + 多源验证
# ============================================================

def _time_weight(recorded_at: str, now: datetime, tau: float = TIME_DECAY_TAU) -> float:
    """时间衰减权重：越近权重越高，指数衰减 exp(-Δt/τ)。"""
    recorded = datetime.fromisoformat(recorded_at)
    delta_days = max((now - recorded).total_seconds() / 86400, 0.0)
    return math.exp(-delta_days / tau)


def _source_weight(records: list[dict]) -> dict[int, float]:
    """多源验证：数值相近（容差±5）且来源不同的记录互相增强置信度。"""
    groups: list[list[int]] = []
    for i, r in enumerate(records):
        bp = r.get("blood_pressure")
        if not bp:
            groups.append([i])
            continue
        sys_val = int(bp.split("/")[0])
        placed = False
        for g in groups:
            ref = records[g[0]].get("blood_pressure")
            if ref and abs(int(ref.split("/")[0]) - sys_val) <= 5:
                g.append(i)
                placed = True
                break
        if not placed:
            groups.append([i])
    weights = {i: 1.0 for i in range(len(records))}
    for g in groups:
        sources = {records[i].get("worker", "?") for i in g}
        boost = 1.0 + 0.2 * (len(sources) - 1)  # 每多一个独立来源 +0.2
        for i in g:
            weights[i] *= boost
    return weights


def resolve_conflicts(records: list[dict], now: datetime | None = None) -> ConflictResult:
    """解决历史记录冲突，返回最可信记录 + 冲突分析。"""
    if not records:
        return ConflictResult(reason="无历史记录可分析")
    now = now or datetime.now()

    tw = [_time_weight(r["recorded_at"], now) for r in records]
    sw = _source_weight(records)
    scored = []
    for i, r in enumerate(records):
        score = tw[i] * sw[i]
        scored.append((i, r, score, tw[i], sw[i]))
    scored.sort(key=lambda x: x[2], reverse=True)

    best_idx, best_rec, best_score, _, _ = scored[0]

    bps = [r.get("blood_pressure") for r in records if r.get("blood_pressure")]
    conflict = False
    if len(bps) >= 2:
        systolics = [int(bp.split("/")[0]) for bp in bps]
        if max(systolics) - min(systolics) > 10:
            conflict = True

    reason = (
        f"采用综合得分 {best_score:.3f} 的记录（{best_rec['recorded_at']} / {best_rec['worker']}）。"
        + ("检测到收缩压波动 >10mmHg，已按时间衰减+来源验证排序。"
           if conflict else "历史记录一致性良好。")
    )
    return ConflictResult(
        resolved=best_rec,
        conflict=conflict,
        reason=reason,
        all_ranked=[
            {"record": r, "score": round(s, 3),
             "time_weight": round(tw_i, 3), "source_weight": round(sw_i, 3)}
            for (i, r, s, tw_i, sw_i) in scored
        ],
    )


# ============================================================
# 五、Cross-Encoder Reranking（面试 Q16）：粗排→精排
# ============================================================

def build_reranking_retriever(store: QdrantVectorStore) -> ContextualCompressionRetriever:
    """组装：Qdrant 粗排 top-K → CrossEncoderReranker 精排 top-N。"""
    base_retriever = store.as_retriever(search_kwargs={"k": RECALL_K})
    reranker_model = HuggingFaceCrossEncoder(model_name=RERANKER_MODEL)
    compressor = CrossEncoderReranker(model=reranker_model, top_n=RERANK_TOP_N)
    return ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=base_retriever,
    )


def retrieve_with_rerank(
    retriever: ContextualCompressionRetriever,
    query: str,
    patient_name: str | None = None,
) -> list[Document]:
    """带重排的检索。patient_name 给定时用 Qdrant filter 预过滤。"""
    if patient_name:
        # 带 metadata filter 的检索：先用 filter 缩小范围，再粗排精排
        base = retriever.base_retriever
        docs = base.invoke(
            query,
            filter=build_metadata_filter(patient_name),
        )
        # 手动跑一次 reranker（因为带 filter 时走的是 base retriever）
        compressor = retriever.compressor
        return compressor.compress_documents(docs, query)
    return retriever.invoke(query)


# ============================================================
# 五之二、Hybrid RAG 中间校验：Query Enhancement + Retrieval Validation
# （呼应第一节 1.3 的三层校验：检索前改写 / 检索后验质 / 生成后由 Agent 兜底）
# ============================================================

# 关键词映射表：把护工口语化的问法扩展成更利于向量检索的描述
QUERY_EXPANSION_MAP = {
    "血压怎么样": "血压 收缩压 舒张压 高压 低压 mmHg",
    "体温正常吗": "体温 温度 发烧 ℃",
    "上次": "历史记录 之前 记录",
    "最近": "最近 近期 这几天 一周",
    "精神怎么样": "精神 情绪 状态 心情",
    "吃饭怎么样": "饮食 吃饭 进食 食欲 早餐 午餐 晚餐",
    "头晕": "头晕 头疼 症状 不适",
}


def enhance_query(raw_query: str) -> str:
    """Query Enhancement（检索前改写）：把护工口语化问题扩展成检索友好的描述。
    纯规则扩展，不调 LLM，零延迟。命中关键词就拼上同义描述，提升向量召回的召回率。"""
    extras: list[str] = []
    for keyword, expansion in QUERY_EXPANSION_MAP.items():
        if keyword in raw_query and expansion not in extras:
            extras.append(expansion)
    if not extras:
        return raw_query
    # 拼成"原问题 + 检索关键词"的混合 query，向量检索对关键词更敏感
    return f"{raw_query} {' '.join(extras)}"


def validate_retrieval(
    query: str, docs: list[Document], min_results: int = 1,
) -> tuple[bool, str]:
    """Retrieval Validation（检索后验质）：检查召回质量是否达标。
    返回 (是否通过, 说明)。不通过时提示 Agent 换关键词重查。"""
    if len(docs) < min_results:
        return False, f"召回数量 {len(docs)} 不足 {min_results}，建议换关键词重查"
    # 检查召回结果里有没有"实体命中"——至少一条文档的 metadata 里含老人姓名
    has_patient = any(
        (d.metadata or {}).get("patient_name") for d in docs
    )
    # 检查是否全是"无关召回"——粗略用文档长度判断（太短的文档往往是噪音）
    avg_len = sum(len(d.page_content) for d in docs) / len(docs) if docs else 0
    if avg_len < 10:
        return False, f"召回文档平均长度 {avg_len:.0f} 过短，疑似噪音，建议重查"
    note = "含老人记录" if has_patient else "未明确匹配到老人姓名"
    return True, f"召回 {len(docs)} 条，{note}，质量达标"


def extract_patient_name(query: str) -> str:
    """从用户问题里抽取老人姓名（简单规则，生产可换 LLM 抽取）。
    支持"王奶奶""李爷爷""张奶奶"等常见称呼。"""
    import re
    m = re.search(r"([\u4e00-\u9fa5]{1,3}(?:奶奶|爷爷|大爷|婆婆|公公))", query)
    return m.group(1) if m else ""


# ============================================================
# 六、动态路由（面试 Q15）：把数据源封装成 tool
# ============================================================

@tool
def query_weather_api(city: str) -> str:
    """查询实时天气。当问题涉及"今天天气""现在几度""下雨吗"等实时信息时使用。
    city 为城市名。"""
    mock = {"北京": "晴 28℃", "上海": "多云 26℃", "广州": "雷阵雨 30℃"}
    return mock.get(city, f"{city} 暂无天气数据")


@tool
def query_schedule_api(date: str) -> str:
    """查询护工排班。当问题涉及"今天谁值班""排班""谁来看护"等实时排班信息时使用。
    date 为日期，格式 YYYY-MM-DD。"""
    mock = {
        "2026-07-08": "白班：小李、小张；夜班：老王",
        "2026-07-09": "白班：小李、老王；夜班：小张",
    }
    return mock.get(date, f"{date} 暂无排班数据")


# search_history 需要 retriever，用闭包工厂动态创建，避免全局变量
def make_search_history_tool(retriever: ContextualCompressionRetriever):
    """创建 search_history 工具，闭包持有 retriever 与 conflict_resolver。
    内部串联：Query Enhancement → Qdrant 粗排 → Reranker 精排 → Retrieval Validation → 冲突处理。"""

    @tool
    def search_history(query: str, patient_name: str = "") -> str:
        """检索历史护理记录。当问题涉及老人历史状况、体征趋势、过往异常、
        "上次""最近""之前"等历史信息时使用。
        query 为检索关键词，patient_name 为老人姓名（可选，用于精确过滤）。"""
        # 1) Query Enhancement：把口语化问题扩展成检索友好的描述（零延迟规则扩展）
        enhanced = enhance_query(query)
        # 自动抽取老人姓名（若调用方未显式传入）
        name = patient_name or extract_patient_name(query) or None

        # 2) 检索 + Reranking：Qdrant 粗排 top-K → CrossEncoderReranker 精排 top-N
        docs = retrieve_with_rerank(retriever, enhanced, patient_name=name)

        # 3) Retrieval Validation：检查召回质量，不达标则提示 Agent 换关键词重查
        ok, note = validate_retrieval(query, docs, min_results=1)
        if not ok:
            return f"[检索校验未通过] {note}。请尝试换更具体的关键词，或确认老人姓名。"
        if not docs:
            return "未检索到相关历史记录"

        # 4) 冲突处理：把精排结果转成记录列表，做时间加权 + 多源验证
        records = []
        for d in docs:
            m = d.metadata or {}
            records.append({
                "content": d.page_content,
                "blood_pressure": m.get("blood_pressure"),
                "temperature": m.get("temperature"),
                "recorded_at": m.get("recorded_at", ""),
                "worker": m.get("worker", "未知"),
                "patient_name": m.get("patient_name", ""),
            })

        conflict = resolve_conflicts(records)
        lines = [f"[检索校验] {note}", f"[冲突分析] {conflict.reason}"]
        if conflict.conflict:
            lines.append("[注意] 检测到历史记录存在冲突，已按时间+来源加权排序。")
        for i, r in enumerate(conflict.all_ranked, 1):
            rec = r["record"]
            bp = rec.get("blood_pressure", "无")
            lines.append(
                f"  {i}. {rec['recorded_at']} | {rec['worker']} | "
                f"血压:{bp} | 得分:{r['score']} | {rec['content'][:40]}"
            )
        return "\n".join(lines)

    return search_history


# ============================================================
# 七、Agent 构建
# ============================================================

AGENT_SYSTEM_PROMPT = """你是养老护工智能记录系统的查询助手。

你的工作流程：
1. 先判断问题类型：
   - 实时信息（天气/排班/时间）→ 调对应 API 工具（query_weather_api / query_schedule_api）
   - 历史记录（体征趋势/过往异常/"上次""最近"）→ 调 search_history 工具
2. 如果是历史记录问题，且能从问题中识别出老人姓名，务必传入 patient_name 做精确过滤
3. search_history 返回的结果已做过冲突处理（时间加权+多源验证），含"冲突分析"说明，
   你要基于最可信记录回答，并在答案中说明采信了哪条记录、为什么
4. 如果检测到冲突，要向用户解释冲突情况，不要回避
5. 实时问题和历史问题可能同时出现（如"今天天气好不好，王奶奶上次说怕冷"），要分别调对应工具

回答要简洁、可信、可解释。养老场景宁可说"信息不足需人工确认"，也不要编造。"""


def build_agentic_rag_agent(
    retriever: ContextualCompressionRetriever,
    model: str = "openai:gpt-4o-mini",
):
    """构建 Agentic RAG Agent：动态路由 + 冲突处理 + Reranking 三合一。"""
    search_history = make_search_history_tool(retriever)
    tools = [query_weather_api, query_schedule_api, search_history]
    llm = init_chat_model(model)
    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=AGENT_SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )


# ============================================================
# 八、种子数据：模拟历史护理记录
# ============================================================

def seed_demo_data(store: QdrantVectorStore) -> None:
    """写入一批演示用历史记录（含故意制造的冲突）。"""
    records = [
        CareRecordDoc(
            patient_name="王奶奶",
            content="王奶奶今天血压偏高 150/95，老人有点激动，已安抚。",
            blood_pressure="150/95", temperature=37.0,
            recorded_at="2026-07-05T10:00:00", worker="小李",
            symptoms=["激动"],
        ),
        CareRecordDoc(
            patient_name="王奶奶",
            content="王奶奶昨天血压 135/85，刚量完老人平静，状态良好。",
            blood_pressure="135/85", temperature=36.6,
            recorded_at="2026-07-07T09:00:00", worker="小张",
            symptoms=[],
        ),
        CareRecordDoc(
            patient_name="王奶奶",
            content="王奶奶今天血压 138/88，体温 36.8，精神不错，吃饭正常。",
            blood_pressure="138/88", temperature=36.8,
            recorded_at="2026-07-08T08:00:00", worker="小李",
            symptoms=[],
        ),
        CareRecordDoc(
            patient_name="王奶奶",
            content="王奶奶上周说有点头晕，量了血压正常，已多喝水观察。",
            blood_pressure="125/80", temperature=36.5,
            recorded_at="2026-07-02T14:00:00", worker="小张",
            symptoms=["头晕"],
        ),
        CareRecordDoc(
            patient_name="王奶奶",
            content="王奶奶今天吃饭挺好，参加了手工活动，情绪平静。",
            blood_pressure=None, temperature=36.7,
            recorded_at="2026-07-08T16:00:00", worker="小张",
            symptoms=[],
        ),
        CareRecordDoc(
            patient_name="李爷爷",
            content="李爷爷今天血压 160/100，头晕明显，已通知家属并服药。",
            blood_pressure="160/100", temperature=37.2,
            recorded_at="2026-07-08T09:30:00", worker="老王",
            symptoms=["头晕"],
        ),
    ]
    add_care_records(store, records)
    print(f"[种子] 写入 {len(records)} 条历史记录")


# ============================================================
# 九、运行入口
# ============================================================

def ask(agent, question: str, case_name: str = "") -> None:
    """向 Agent 提问并打印结果。"""
    print(f"\n{'='*60}")
    if case_name:
        print(f"案例：{case_name}")
    print(f"问题：{question}")
    print(f"{'-'*60}")
    config = {"configurable": {"thread_id": f"q-{datetime.now().timestamp()}"}}
    result = agent.invoke(
        {"messages": [HumanMessage(content=question)]},
        config=config,
    )
    print(result["messages"][-1].content)
    # 打印工具调用链
    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    for tm in tool_msgs:
        preview = tm.content[:80].replace("\n", " ")
        print(f"  [工具] {tm.name}: {preview}...")


def demo_retrieval_pipeline(retriever: ContextualCompressionRetriever) -> None:
    """单独演示检索管线（不走 Agent）：
    Query Enhancement → 粗排 → 精排 → Retrieval Validation → 冲突处理。
    用来验证 Reranking 和冲突处理是否生效，不依赖 LLM。"""
    print(f"\n{'#'*60}")
    print("# 检索管线独立演示（不走 Agent，验证 Reranking + 冲突处理）")
    print(f"{'#'*60}")
    raw = "王奶奶最近血压怎么样"
    name = extract_patient_name(raw)
    enhanced = enhance_query(raw)
    print(f"[原始问题] {raw}")
    print(f"[自动抽名] {name or '(未识别)'}")
    print(f"[问题增强] {enhanced}")

    docs = retrieve_with_rerank(retriever, enhanced, patient_name=name)
    ok, note = validate_retrieval(raw, docs, min_results=1)
    print(f"[检索校验] {note}")

    if not docs:
        print("[结果] 未检索到记录")
        return

    records = []
    for d in docs:
        m = d.metadata or {}
        records.append({
            "content": d.page_content,
            "blood_pressure": m.get("blood_pressure"),
            "temperature": m.get("temperature"),
            "recorded_at": m.get("recorded_at", ""),
            "worker": m.get("worker", "未知"),
            "patient_name": m.get("patient_name", ""),
        })
    conflict = resolve_conflicts(records)
    print(f"[冲突分析] {conflict.reason}")
    print(f"[是否冲突] {conflict.conflict}")
    print("[精排+冲突排序结果]")
    for i, r in enumerate(conflict.all_ranked, 1):
        rec = r["record"]
        bp = rec.get("blood_pressure", "无")
        print(f"  {i}. {rec['recorded_at']} | {rec['worker']} | "
              f"血压:{bp} | 得分:{r['score']} | {rec['content'][:40]}")


def main():
    """主流程：初始化向量库 → 写种子数据 → 构建 Agent → 跑演示。"""
    print("[1/4] 初始化 Embedding 模型...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    print("[2/4] 初始化 Qdrant 向量库...")
    store = init_qdrant_store(embeddings)
    print("[3/4] 写入种子数据...")
    seed_demo_data(store)

    print("[4/4] 构建 Reranking Retriever + Agentic RAG Agent...")
    retriever = build_reranking_retriever(store)

    # 先单独演示检索管线（不走 Agent，验证 Reranking + 冲突处理生效）
    demo_retrieval_pipeline(retriever)

    # 再跑完整 Agent（动态路由 + 冲突处理 + Reranking 三合一）
    agent = build_agentic_rag_agent(retriever, model="openai:gpt-4o-mini")

    # 案例 1：历史记录问题（含冲突）——触发 search_history + conflict_resolver
    ask(agent,
        "王奶奶最近血压怎么样？和上次比有变化吗？",
        "历史记录 + 冲突处理")

    # 案例 2：实时问题——触发 query_weather_api（不走向量库）
    ask(agent,
        "今天北京天气怎么样？适合带老人出去晒太阳吗？",
        "实时问题 → API 路由")

    # 案例 3：实时 + 历史混合——同时调天气 API 和历史检索
    ask(agent,
        "今天上海天气如何？另外王奶奶上次说怕冷，最近情况怎样？",
        "实时 + 历史混合路由")

    # 案例 4：排班实时问题——触发 query_schedule_api
    ask(agent,
        "2026-07-08 今天谁值班看护？",
        "排班实时查询")

    # 案例 5：另一位老人的异常记录——验证不同老人的检索隔离
    ask(agent,
        "李爷爷今天情况怎么样？有没有异常？",
        "不同老人检索隔离")


if __name__ == "__main__":
    main()
```

这个文件把三大能力串成一条完整链路：`search_history` 工具内部先调 `retrieve_with_rerank`（Qdrant 粗排 + BGE 精排），再调 `resolve_conflicts`（时间加权 + 多源验证），最后把"冲突分析 + 排序结果"返回给 Agent；Agent 拿到结构化的冲突分析后，能在回答里解释"采信了今天 138/88 这条，因为它是最近的且经过多源验证"。而 `query_weather_api` / `query_schedule_api` 这两个实时工具让 Agent 能把"今天天气"这类问题直接路由到 API，不会去向量库里捞一堆过期记录硬答。

> **2026 API 速查：** `QdrantVectorStore` 来自 `langchain_qdrant`（不是旧的 `Qdrant`）；Qdrant filter 用 `qdrant_client.models.Filter/FieldCondition/MatchValue`；Cross-Encoder 三件套是 `ContextualCompressionRetriever` + `CrossEncoderReranker` + `HuggingFaceCrossEncoder`；Agent 用 `create_agent`（`langchain.agents`），工具用 `@tool`（`langchain.tools`），模型用 `init_chat_model`（`langchain.chat_models`）。这套 import 路径是 2026 的正确姿势，面试时能脱口而出是加分项。

---

## 动手实验

### 🟢 青铜：跑通 reranking 精排对比

1. 装依赖：`pip install langchain-qdrant langchain-huggingface sentence-transformers qdrant-client`
2. 把第三节 reranking.py 跑起来，先用 `as_retriever(k=20)` 看粗排 top-20 的顺序
3. 再用 `compression_retriever` 看精排后的 top-3 顺序
4. 对比："王奶奶今天血压正常吗"这个 query，粗排第 1 名和精排第 1 名是不是不一样？精排有没有把"今天血压 138/88"顶到第 1？

```python
# 粗排 vs 精排对比
print("=== 粗排 top-5 ===")
for d in base_retriever.invoke("王奶奶今天血压正常吗")[:5]:
    print(f"  {d.page_content[:50]}")
print("=== 精排 top-3 ===")
for d in compression_retriever.invoke("王奶奶今天血压正常吗"):
    print(f"  {d.page_content[:50]}")
```

### 🟡 白银：构造冲突场景验证 conflict_resolver

1. 在种子数据里再加 2 条王奶奶的冲突记录（不同护工、不同时间、差值 >10）
2. 单独跑 `resolve_conflicts`，验证：时间最近的得分最高？多源验证的有没有 boost？
3. 改 `TIME_DECAY_TAU` 从 7 天改成 3 天，观察一周前的记录权重怎么变
4. 整理表格：记录 → time_weight → source_weight → 综合得分 → 是否被采信

### 🔴 王者：Hybrid RAG 全链路 + 评估

1. 跑通完整的 `agentic_rag.py`，观察四个案例分别调了哪些工具
2. 准备 10 个测试问题（3 历史 / 3 实时 / 4 混合），统计：路由准确率（该查历史的有没有查历史）、冲突检测召回率（有冲突的有没有被标出来）
3. 对比"有 Reranking"和"无 Reranking（直接用 base_retriever top-3）"的答案质量，写一份对比报告
4. 思考题：如果老人同名（两个王奶奶），怎么用 metadata filter 区分？提示：加 `patient_id` 字段做精确过滤

---

## 踩坑记录 🕳️

### 坑 1：QdrantVectorStore 用了旧 import 报错

```python
# ❌ 旧版（已废弃，2026 会报错或行为异常）
from langchain_community.vectorstores import Qdrant

# ✅ 2026 新版
from langchain_qdrant import QdrantVectorStore
```

**原因：** LangChain 拆分后，Qdrant 集成独立成 `langchain-qdrant` 包，类名也从 `Qdrant` 改成 `QdrantVectorStore`。旧版 `langchain_community.vectorstores.Qdrant` 还在但已 deprecated，且和 2026 的 retriever 接口不完全兼容。

**解决：** `pip install langchain-qdrant`，import 用 `QdrantVectorStore`。如果你看到 `AttributeError: 'Qdrant' object has no attribute 'as_retriever'` 之类报错，八成是用了旧包。

### 坑 2：bge-reranker-v2-m3 首次加载慢且占内存

首次跑 `HuggingFaceCrossEncoder(model_name="BAAI/bge-reranker-v2-m3")` 会从 HuggingFace 下载模型（约 2GB），而且推理时每个 `(query, doc)` 对都要前向传播一次，top-20 精排要跑 20 次前向。

**解决：** 一是接受首次下载成本，后续走本地缓存；二是控制 `RECALL_K`（粗排数），20 够用了，别开到 100 否则精排慢死；三是 CPU 推理慢的话，有 GPU 的话 `HuggingFaceCrossEncoder` 会自动用；四是对延迟敏感的生产场景，考虑把 Reranker 部署成独立微服务（用 TEI 或 vLLM 跑），Agent 走 HTTP 调用。

### 坑 3：带 filter 检索时 Reranker 没生效

`retriever.invoke(query, filter=...)` 直接调时，`ContextualCompressionRetriever` 不一定把 filter 透传给 base retriever，导致要么没过滤、要么没重排。

**解决：** 像第五节 `retrieve_with_rerank` 那样——带 filter 时手动先拿 `base_retriever.invoke(query, filter=...)` 拿到 docs，再手动调 `compressor.compress_documents(docs, query)` 做重排。把"过滤检索"和"重排"拆成两步显式调用，避免框架内部透传 filter 的不确定性。

### 坑 4：冲突处理只看数值，漏了语义冲突

`resolve_conflicts` 现在只比较血压数值的极差，但有些冲突是语义层面的——比如一条记录说"老人头晕"，另一条同时段说"老人状态良好"，数值都对得上但描述矛盾。

**解决：** 数值冲突用代码兜底（确定性强），语义冲突交给 Agent——在 `search_history` 返回里带上"冲突分析"提示，让 Agent 在生成时判断描述是否自洽。代码处理"硬冲突"（数值打架），Agent 处理"软冲突"（描述打架），各司其职。

### 坑 5：动态路由把历史问题误判成实时问题

护工问"王奶奶今天血压怎么样"里有"今天"二字，Agent 可能误判成实时问题去调 API，而不是查历史记录。

**解决：** 在 `AGENT_SYSTEM_PROMPT` 里明确路由规则："问题里出现老人姓名 + 体征/状况关键词（血压/体温/头晕/吃饭/情绪），即使带'今天'也是历史记录问题，走 search_history。只有纯天气/排班/时间类才走 API。"用 system_prompt 强化路由判据，比单靠 Agent 语义判断更稳。

---

## 副线笔记

### Week 04 基础 RAG vs Week 10 Agentic RAG

今天学的 Agentic RAG 是 Week 04 基础 RAG 的深化升级。把两周放一起对比，能看清"检索"这件事是怎么从"固定流水线"进化成"Agent 自主决策"的：

| 维度 | Week 04 基础 RAG（2-Step） | Week 10 Agentic RAG（Hybrid） |
|------|--------------------------|------------------------------|
| **检索触发** | 每个问题都检索（固定一步） | Agent 判断该不该检索 |
| **向量库** | Chroma（本地原型） | Qdrant（生产级，filter 更强） |
| **召回策略** | 纯向量 top-K | 向量粗排 + Cross-Encoder 精排 |
| **冲突处理** | 无（全塞给 LLM） | 元数据加权 + 多源验证 |
| **实时信息** | 全靠检索（过期数据硬答） | 动态路由到 API |
| **可解释性** | 黑盒（LLM 直接答） | 带冲突分析 + 采信原因 |
| **检索控制** | 一次检索，不可调整 | Agent 多轮检索、换关键词重查 |

**进化的本质：** Week 04 把检索当"必经之路"，所以它的优化方向是"召回得更准"（Week 05 学了 ANN 索引 HNSW、Week 06 学了 chunk 策略）。Week 10 把检索当"可选工具"，所以它的优化方向是"该不该查、查回来对不对、冲突了怎么办"。前者优化的是检索器本身，后者优化的是检索的"使用方式"。

**为什么先学基础再学 Agentic：** 你得先理解 Bi-Encoder 检索的局限（Week 04-05），才能理解为什么要加 Cross-Encoder 精排（今天）；得先写过固定流水线的 RAG（Week 04 的 pipeline.py），才能理解 Agent 把检索降级成 tool 后灵活在哪（今天的 search_history 工具）。基础 RAG 是"地基"，Agentic RAG 是"装修"——没有地基的装修是空中楼阁。

> **今日观察任务：** 对比 Week 04 `homework/rag/pipeline.py` 的检索流程和今天 `agentic_rag.py` 的 `search_history` 工具，数一数今天多了几道"校验/处理"环节。这些环节正是从"能用"到"可信"的距离。

---

## 检查清单

- [ ] 能说清 2-Step RAG / Agentic RAG / Hybrid RAG 三者的区别，知道养老场景选 Hybrid 的原因
- [ ] 理解 Agentic RAG 的核心：把检索从"固定流水线"降级成"Agent 工具箱里的 tool"
- [ ] 掌握冲突处理（Q13）两大策略：元数据加权（时间衰减）+ 多源验证
- [ ] 跑通 `conflict_resolver`，理解为什么返回 `all_ranked` 和 `reason` 而不只是返回一个答案
- [ ] 理解 Bi-Encoder（粗筛/独立编码）和 Cross-Encoder（精排/拼接编码）的区别
- [ ] 用 `BAAI/bge-reranker-v2-m3` + `ContextualCompressionRetriever` 跑通精排，观察到正解被顶到第 1
- [ ] 知道 2026 的 Qdrant import：`langchain_qdrant.QdrantVectorStore`（不是旧的 `Qdrant`）
- [ ] 知道 Qdrant filter 用 `qdrant_client.models.Filter/FieldCondition/MatchValue`
- [ ] 理解动态路由（Q15）：把数据源封装成 `@tool`，路由决策隐式发生在 Agent 工具选择环节
- [ ] 跑通完整 `agentic_rag.py`，观察到四个案例分别走了不同的工具路由
- [ ] 能回答面试 Q13/Q15/Q16：冲突处理、动态路由、Reranking 各自的方案和踩过的坑

---

## 下课预告

> **Day 05 — 趋势分析 Agent + 多 Agent 协作。** 今天我们解决了"检索回来怎么用"——冲突处理让历史记录可信，Reranking 让检索精准，动态路由让实时问题走对路。但养老场景还有个硬需求：趋势分析。"王奶奶最近一周血压在涨吗""李爷爷这周情绪波动大不大"——这需要把多天的历史记录做时序聚合和趋势判断，单个检索 + 生成搞不定。明天我们搭趋势分析 Agent，和已有的提取 Agent、查询 Agent 组成多 Agent 协作（Week 07 学过的编排模式落地）。这是 Week 07 多 Agent 理论在养老项目里的真实落地，也是从"单 Agent 能用"到"多 Agent 协作"的关键一跃。
