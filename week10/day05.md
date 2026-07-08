# Day 05 — 向量检索 + 趋势分析

## 学习目标

Day 04 我们学了 Agentic RAG 的冲突处理和 Reranking——当历史记录矛盾时用元数据加权 + 多 Agent 辩论解决，当检索结果不准时用 Cross-Encoder 重排。今天把这些能力落地到养老护工场景的真实痛点：护工每天记一两条，日子一长记录就堆成山，"王奶奶上周血压多少""张爷爷最近情绪怎么样"根本翻不过来。我们要把这些记录存进 Qdrant 向量库，再搭一个趋势分析 Agent，让它能回答"王奶奶最近 7 天血压先升后降""张爷爷体温连续 3 天偏高"这类趋势问题。

养老护理的核心价值不是记一条记一条，而是从一堆记录里看出趋势、看出异常、看出该不该通知家属。从单次记录到趋势洞察，这是养老系统从"记事本"升级成"健康守门人"的关键一步。

学完今天你能：

1. 用 Week 05 学过的 Qdrant（不是 Milvus）把护工记录存入向量库，理解 `QdrantVectorStore` 替代旧版 `Qdrant` 类的原因，说清三种检索模式 DENSE / SPARSE(BM25) / HYBRID 的差异
2. 设计护工记录的 metadata 结构（elderly_id / date / record_type / vital_values），用 `qdrant_client.models.Filter` 做按老人、按日期、按记录类型的精准过滤检索
3. 用 `create_agent` + `@tool` 搭建 `trend_agent.py`，封装三个趋势分析工具：`search_history`（带 filter 的向量检索）、`compare_vitals`（对比今天和历史生命体征）、`detect_anomaly_trend`（检测异常趋势）
4. 跑通完整趋势分析示例——"王奶奶最近 7 天血压先升后降，建议关注"，理解从单次记录到趋势洞察的产品价值跃迁

---

## 一、回顾 Week 05 向量库

### 1.1 Week 05 我们学过什么

Week 05 那周我们横向对比了四种向量库——Chroma、Milvus、Qdrant、Pinecone，最后用一棵决策树把"什么场景该选谁"钉死。那张对比表和决策树是本周的基础，今天我们要从中挑一个真正落地到养老项目里。

| 向量库 | Week 05 时的定位 | 今天用不用 |
|--------|------------------|-----------|
| Chroma | 原型之王，装即用 | ❌ 过滤能力弱（`where` 扁平） |
| Milvus | 生产级分布式老大哥 | ❌ 运维太重，养老项目用不上 |
| Qdrant | Rust 性能 + payload 过滤 + 内置量化 | ✅ 今天用它 |
| Pinecone | 全托管 Serverless | ❌ 数据要落自己机房 |

> **为什么不选 Milvus：** Week 05 Day 04 我们用过 Milvus，它确实能扛亿级数据，但养老院一个项目顶多几千条记录，杀鸡用牛刀。而且 Milvus 要 Docker 起一组容器（etcd + MinIO + Milvus），开发环境太重。养老项目要的是轻量 + 强过滤，Qdrant 正好。

### 1.2 为什么选 Qdrant

Qdrant 用 Rust 写成，单机性能强，同时原生支持分布式。对养老项目来说，它有三个特性正好卡在痛点上：

| 特性 | 养老场景怎么用 | 为什么比 Chroma 强 |
|------|---------------|-------------------|
| **payload 过滤** | 按老人 ID / 日期 / 记录类型过滤 | Chroma 的 `where` 只能扁平等值，Qdrant 支持嵌套、范围、Geo |
| **混合检索** | "头晕"这种关键词查 SPARSE，"精神不好"这种语义查 DENSE | Chroma 要自己拼 RRF 融合 |
| **内存模式** | `QdrantClient(":memory:")` 开发零部署 | Milvus 起不来内存模式 |

```
养老项目的检索需求：
  "王奶奶最近 7 天的血压记录" → 按 elderly_id + 日期范围 filter（Qdrant payload 过滤）
  "精神状态不好的记录"       → 语义检索（DENSE 向量检索）
  "头晕/恶心/呕吐"           → 关键词检索（SPARSE BM25）
  两者都要                   → HYBRID 混合检索
```

> **前端类比：** 向量检索就像前端的搜索功能——DENSE 是"语义搜索"（像 Google 搜"心情不好的老人"能找到"情绪低落"），SPARSE 是"关键词搜索"（像浏览器 Ctrl+F 精确匹配"头晕"），HYBRID 是两者融合（像 ElasticSearch 既算 TF-IDF 又算语义相似度）。filter 就像 SQL 的 WHERE 条件——`WHERE elderly_id = 'W001' AND date BETWEEN '2026-07-01' AND '2026-07-07'`，只不过 Qdrant 用 `Filter(must=[FieldCondition(...)])` 表达。

### 1.3 Qdrant 的 payload 过滤回顾

Week 05 Day 05 我们写过 Qdrant 的 payload 过滤，今天要重新捡起来。核心是三个类：`Filter`、`FieldCondition`、`MatchValue`（还有 `Range` 做范围过滤）。

```python
# Week 05 学过的 payload 过滤（回顾）
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

client = QdrantClient(path="./qdrant_data")

# 查"川西海拔>=4000的路线"——等值 + 范围组合
results = client.search(
    collection_name="routes",
    query_vector=[0.15] * 384,
    query_filter=Filter(
        must=[
            FieldCondition(key="region", match=MatchValue(value="川西")),       # 等值
            FieldCondition(key="elevation_m", range=Range(gte=4000)),            # 范围
        ]
    ),
    limit=5,
)
```

今天要把这套过滤语法用在养老记录上——`elderly_id` 做等值过滤（指定老人），`date` 做范围过滤（最近 7 天），`record_type` 做等值过滤（只要生命体征记录）。**filter 是趋势分析的命脉**——不做 filter，你查出来的是全院所有老人的记录混在一起，根本没法做"王奶奶的趋势"。

---

## 二、Qdrant + LangChain 2026 集成

### 2.1 包名变了：langchain-qdrant

Week 05 我们用的是 `qdrant-client` 裸调 SDK——`client.upsert()` / `client.search()`。今天要接 LangChain，让向量库和 Agent、Chain 能联动。2026 年 LangChain 官方把 Qdrant 集成拆成了独立包 `langchain-qdrant`（不再塞在 `langchain-community` 里）。

```bash
# 安装（2026 版本）
pip install langchain-qdrant qdrant-client
```

> **为什么要独立包：** 就像前端从 webpack 拆出 babel-loader、css-loader 一样——把每个向量库的集成做成独立包，按需安装，不装的人不用背着-community 这个大包。这也是 2026 年 LangChain 的整体趋势——模块化拆分，按需引入。

### 2.2 核心类：QdrantVectorStore

2026 年的核心类是 `QdrantVectorStore`（注意不是旧版的 `Qdrant`）。旧版 `from langchain_community.vectorstores import Qdrant` 已经废弃，新包里改名了，加上了 `VectorStore` 后缀，和其他向量库的命名对齐（`Chroma` → `ChromaVectorStore`，`FAISS` → `FAISSVectorStore`）。

```python
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from langchain_openai import OpenAIEmbeddings

# 三行初始化：client + collection_name + embedding
client = QdrantClient(":memory:")  # 内存模式，开发零部署
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vector_store = QdrantVectorStore(
    client=client,
    collection_name="care_records",
    embedding=embeddings,
)
```

> **前端类比：** `QdrantVectorStore` 就像前端的 ORM——你不用手写 SQL（裸 `qdrant-client` 的 `upsert`/`search`），而是用对象方法（`add_texts` / `similarity_search`）。就像 Prisma 把 PostgreSQL 封装成 `prisma.record.findMany()`，LangChain 把 Qdrant 封装成 `vector_store.similarity_search()`。

### 2.3 三种检索模式：DENSE / SPARSE / HYBRID

Qdrant 支持三种检索模式，这是它比 Chroma 强的地方（Chroma 只有 DENSE）：

| 模式 | 含义 | 适合场景 | 养老场景用在哪 |
|------|------|---------|---------------|
| **DENSE** | 纯向量检索（embedding 相似度） | 语义模糊查询 | "精神状态不好的记录" |
| **SPARSE** | 稀疏向量检索（BM25 关键词） | 精确关键词匹配 | "头晕/恶心/呕吐" |
| **HYBRID** | DENSE + SPARSE 融合 | 两者都要 | "头晕且精神不好" |

```python
# 三种检索模式（2026 用法）
from qdrant_client import QdrantClient, models
from langchain_qdrant import QdrantVectorStore

client = QdrantClient(":memory:")

# DENSE 模式（默认）：纯向量相似度
vector_store_dense = QdrantVectorStore(
    client=client,
    collection_name="care_records",
    embedding=embeddings,
)

# HYBRID 模式：需要同时配置 sparse_embedding
# sparse_embedding 可以用 FastEmbedBM25（Qdrant 内置的 BM25 稀疏向量器）
from fastembed import SparseTextEmbedding
sparse_embedding = SparseTextEmbedding(model_name="Qdrant/bm25")

vector_store_hybrid = QdrantVectorStore(
    client=client,
    collection_name="care_records_hybrid",
    embedding=embeddings,                    # dense 向量器
    sparse_embedding=sparse_embedding,       # sparse 向量器（BM25）
    retrieval_mode="hybrid",                  # 检索模式：dense / sparse / hybrid
)
```

养老场景的选型逻辑：

```
护工说"今天精神不太好" → DENSE（语义，"精神不太好"和"情绪低落"向量相近）
护工说"头晕恶心"       → SPARSE（关键词，"头晕""恶心"精确匹配）
护工说"头晕且精神差"   → HYBRID（既要匹配"头晕"关键词，又要语义找"精神差"）
```

今天主代码用 DENSE（默认模式），因为养老记录的趋势分析主要靠语义理解（"先升后降"这种趋势描述是语义不是关键词）。HYBRID 留给白银实验。

### 2.4 Filter 语法：向量检索的 WHERE 条件

这是今天的核心——Qdrant 的 filter 语法。`similarity_search` 方法支持 `filter` 参数，传入 `qdrant_client.models.Filter`：

```python
from qdrant_client import models

# 基础 filter：按老人 ID 过滤（等值）
results = vector_store.similarity_search(
    query="血压头晕",
    k=5,
    filter=models.Filter(
        must=[
            models.FieldCondition(
                key="elderly_id",
                match=models.MatchValue(value="W001"),
            )
        ]
    )
)

# 进阶 filter：老人 ID + 日期范围 + 记录类型（三条件组合）
from datetime import datetime
results = vector_store.similarity_search(
    query="血压变化",
    k=10,
    filter=models.Filter(
        must=[
            # 条件1：指定老人
            models.FieldCondition(
                key="elderly_id",
                match=models.MatchValue(value="W001"),
            ),
            # 条件2：最近7天（日期范围）
            models.FieldCondition(
                key="date",
                range=models.Range(
                    gte="2026-07-01",
                    lte="2026-07-07",
                ),
            ),
            # 条件3：只要生命体征记录
            models.FieldCondition(
                key="record_type",
                match=models.MatchValue(value="vitals"),
            ),
        ]
    )
)
```

> **前端类比：** 这个 filter 就像 SQL 的 WHERE 条件。上面那段等价于：
> ```sql
> SELECT * FROM care_records
> WHERE elderly_id = 'W001'
>   AND date BETWEEN '2026-07-01' AND '2026-07-07'
>   AND record_type = 'vitals'
> ORDER BY similarity(query_embedding, vector) DESC
> LIMIT 10
> ```
> 区别是向量检索的 ORDER BY 不是普通字段排序，而是向量相似度排序。filter 先把范围缩小（WHERE），再在缩小后的集合里算相似度（ORDER BY similarity）。这叫"先过滤后检索"，比"先检索后过滤"快得多——就像 SQL 先 WHERE 再 ORDER BY，不会先全表排序再过滤。

### 2.5 add_texts / similarity_search / 元数据写入

`QdrantVectorStore` 封装了三个核心方法，对应向量库的三种基本操作：

| 方法 | 作用 | 对应裸 SDK |
|------|------|-----------|
| `add_texts(texts, metadatas)` | 写入文本 + 元数据 | `client.upsert(points=[PointStruct(...)])` |
| `similarity_search(query, k, filter)` | 向量检索 + 过滤 | `client.search(query_vector=..., query_filter=...)` |
| `similarity_search_with_score(query, k, filter)` | 带分数的检索 | 同上，但返回 score |

```python
# 写入：add_texts
ids = vector_store.add_texts(
    texts=["王奶奶今天体温36.8，血压135/85，精神不错"],
    metadatas=[{
        "elderly_id": "W001",
        "date": "2026-07-01",
        "record_type": "vitals",
        "vital_values": {"temperature": 36.8, "systolic": 135, "diastolic": 85},
    }],
)

# 检索：similarity_search（不带分数）
results = vector_store.similarity_search(query="血压", k=5)
for doc in results:
    print(doc.page_content, doc.metadata)

# 检索：similarity_search_with_score（带分数，score 越高越相似）
results = vector_store.similarity_search_with_score(query="血压", k=5)
for doc, score in results:
    print(f"score={score:.3f}  {doc.page_content}")
```

---

## 三、护工记录入向量库

### 3.1 从 CareRecord 到可检索文本

Day 02 我们定义了 `CareRecord` Pydantic 模型，包含老人信息、生命体征、饮食、情绪、异常标记。但那个模型是给结构化提取用的——字段是离散的。要存进向量库，得先把它拍平成一段文本，再做 embedding。

```
CareRecord（结构化）
├── name: "王奶奶"
├── room: "302"
├── vitals: {temperature: 36.8, systolic: 135, diastolic: 85, heart_rate: 72}
├── diet: {breakfast: "半碗粥", lunch: null, dinner: null, appetite: "一般"}
├── emotion: "平静"
├── notes: "今天精神不错"
└── anomalies: []

        ↓ 拍平成文本 ↓

"王奶奶(房间302) 2026-07-01 记录：体温36.8℃，血压135/85mmHg，心率72bpm。
 早餐半碗粥，食欲一般。情绪平静。备注：今天精神不错。无异常。"
```

> **前端类比：** 这就像前端把一个嵌套对象序列化成 JSON 字符串再存 localStorage。CareRecord 是结构化对象，向量库要的是文本——中间这步"拍平"是必须的。拍平的文本要包含所有关键字段，因为 embedding 是对这段文本做的，漏了字段就检索不到。

### 3.2 metadata 设计：过滤的基石

metadata 是 filter 的依据。养老记录的 metadata 要支持这几种过滤：

| 字段 | 类型 | 过滤用途 | 示例值 |
|------|------|---------|--------|
| `elderly_id` | str | 按老人过滤 | "W001"（王奶奶） |
| `date` | str | 按日期范围过滤 | "2026-07-01" |
| `record_type` | str | 按记录类型过滤 | "vitals" / "diet" / "emotion" |
| `vital_values` | dict | 按生命体征值过滤（嵌套） | {"temperature": 36.8, "systolic": 135} |
| `worker_id` | str | 按护工过滤 | "小李" |
| `is_abnormal` | bool | 按异常标记过滤 | true / false |

> **关键设计：** `vital_values` 是嵌套 dict。Qdrant 的 payload 支持嵌套结构，过滤时用 `key="vital_values.temperature"` 这种点号路径访问嵌套字段。这是 Qdrant 比 Chroma 强的地方——Chroma 的 `where` 只能扁平字段。

```python
# 嵌套字段过滤示例（Qdrant 独有，Chroma 做不到）
results = vector_store.similarity_search(
    query="体温偏高",
    k=5,
    filter=models.Filter(
        must=[
            models.FieldCondition(
                key="vital_values.temperature",   # 嵌套字段路径
                range=models.Range(gte=37.5),      # 体温 >= 37.5
            )
        ]
    )
)
```

### 3.3 入库代码：CareRecord → 向量库

把 CareRecord 转成文本 + metadata，调 `add_texts` 写入 Qdrant：

```python
"""ingest_records.py — 护工记录入向量库"""
from datetime import date
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from langchain_openai import OpenAIEmbeddings

# 复用 Day 02 的 CareRecord 模型（简化版，完整定义见 Day 02）
from pydantic import BaseModel, Field, model_validator
from typing import Optional


class Vitals(BaseModel):
    temperature: Optional[float] = None
    systolic: Optional[int] = None
    diastolic: Optional[int] = None
    heart_rate: Optional[int] = None


class CareRecord(BaseModel):
    name: str
    room: Optional[str] = None
    vitals: Vitals = Field(default_factory=Vitals)
    emotion: str = "未说明"
    notes: Optional[str] = None
    anomalies: list[str] = Field(default_factory=list)


def record_to_text(record: CareRecord, record_date: str) -> str:
    """把 CareRecord 拍平成可检索文本。

    前端类比：就像把嵌套对象序列化成 JSON 字符串，
    要包含所有关键字段，因为 embedding 是对这段文本做的。
    """
    v = record.vitals
    parts = [f"{record.name}({record.room or '房间未登记'}) {record_date} 记录："]

    # 生命体征
    vital_parts = []
    if v.temperature is not None:
        vital_parts.append(f"体温{v.temperature}℃")
    if v.systolic is not None and v.diastolic is not None:
        vital_parts.append(f"血压{v.systolic}/{v.diastolic}mmHg")
    if v.heart_rate is not None:
        vital_parts.append(f"心率{v.heart_rate}bpm")
    if vital_parts:
        parts.append("，".join(vital_parts) + "。")

    parts.append(f"情绪{record.emotion}。")
    if record.notes:
        parts.append(f"备注：{record.notes}。")

    if record.anomalies:
        parts.append(f"异常：{'、'.join(record.anomalies)}。")
    else:
        parts.append("无异常。")

    return "".join(parts)


def record_to_metadata(record: CareRecord, elderly_id: str,
                       record_date: str, worker_id: str) -> dict:
    """生成 metadata，供 filter 使用。"""
    v = record.vitals
    return {
        "elderly_id": elderly_id,          # 按老人过滤
        "date": record_date,               # 按日期范围过滤
        "record_type": "vitals",           # 按记录类型过滤
        "worker_id": worker_id,            # 按护工过滤
        "is_abnormal": len(record.anomalies) > 0,  # 按异常标记过滤
        "vital_values": {                  # 嵌套：按生命体征值过滤（Qdrant 独有）
            "temperature": v.temperature,
            "systolic": v.systolic,
            "diastolic": v.diastolic,
            "heart_rate": v.heart_rate,
        },
        "emotion": record.emotion,        # 按情绪过滤
    }


def ingest_records(records: list[tuple[CareRecord, str, str, str]],
                   vector_store: QdrantVectorStore) -> list[str]:
    """批量入库：把 CareRecord 列表写入 Qdrant。

    Args:
        records: [(CareRecord, elderly_id, date, worker_id), ...]
        vector_store: 已初始化的 QdrantVectorStore

    Returns:
        写入的文档 ID 列表
    """
    texts = []
    metadatas = []

    for record, elderly_id, record_date, worker_id in records:
        text = record_to_text(record, record_date)
        metadata = record_to_metadata(record, elderly_id, record_date, worker_id)
        texts.append(text)
        metadatas.append(metadata)
        print(f"  入库: {text[:50]}...")

    ids = vector_store.add_texts(texts=texts, metadatas=metadatas)
    print(f"  共写入 {len(ids)} 条记录，IDs: {ids}")
    return ids


if __name__ == "__main__":
    # 初始化向量库
    client = QdrantClient(":memory:")
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    vector_store = QdrantVectorStore(
        client=client,
        collection_name="care_records",
        embedding=embeddings,
    )

    # 构造 7 天的模拟记录（王奶奶，血压先升后降）
    sample_records = [
        # Day 1-2: 血压正常
        (CareRecord(name="王奶奶", room="302",
                    vitals=Vitals(temperature=36.5, systolic=125, diastolic=80, heart_rate=72),
                    emotion="平静", notes="一切正常"), "W001", "2026-07-01", "小李"),
        (CareRecord(name="王奶奶", room="302",
                    vitals=Vitals(temperature=36.6, systolic=128, diastolic=82, heart_rate=74),
                    emotion="平静", notes="状态稳定"), "W001", "2026-07-02", "小李"),
        # Day 3-4: 血压开始升高
        (CareRecord(name="王奶奶", room="302",
                    vitals=Vitals(temperature=36.8, systolic=138, diastolic=88, heart_rate=78),
                    emotion="焦虑", notes="说有点头晕"), "W001", "2026-07-03", "小李"),
        (CareRecord(name="王奶奶", room="302",
                    vitals=Vitals(temperature=37.0, systolic=145, diastolic=92, heart_rate=82),
                    emotion="烦躁", notes="头晕加重，量了血压偏高"), "W001", "2026-07-04", "小李"),
        # Day 5: 血压达到峰值
        (CareRecord(name="王奶奶", room="302",
                    vitals=Vitals(temperature=37.2, systolic=152, diastolic=98, heart_rate=85),
                    emotion="低落", notes="头晕厉害，没怎么吃饭", anomalies=["收缩压偏高"]),
                    "W001", "2026-07-05", "小李"),
        # Day 6-7: 血压开始下降（吃药后）
        (CareRecord(name="王奶奶", room="302",
                    vitals=Vitals(temperature=36.9, systolic=140, diastolic=90, heart_rate=80),
                    emotion="好转", notes="吃了降压药，头晕减轻"), "W001", "2026-07-06", "小李"),
        (CareRecord(name="王奶奶", room="302",
                    vitals=Vitals(temperature=36.7, systolic=132, diastolic=85, heart_rate=75),
                    emotion="平静", notes="血压降下来了，精神恢复"), "W001", "2026-07-07", "小李"),
    ]

    ingest_records(sample_records, vector_store)
    print("\n7 天记录已入库，可以开始趋势分析了。")
```

> **注意 metadata 的 `date` 字段：** 这里用字符串 `"2026-07-01"` 而不是 `datetime` 对象。因为 Qdrant 的 payload 不直接支持 Python datetime，要转成 ISO 格式字符串。过滤时用 `Range(gte="2026-07-01", lte="2026-07-07")` 做字符串范围比较——ISO 格式的日期字符串恰好可以字典序比较，"2026-07-03" >= "2026-07-01" 成立。

---

## 四、趋势分析 Agent

### 4.1 为什么趋势分析要做成 Agent

你可能会想：趋势分析不就是查 7 条记录画个折线图吗？为什么要做成 Agent？

因为护工/家属问的趋势问题是**自然语言的、模糊的、需要推理的**：

```
家属问："王奶奶最近情况怎么样？"
护工问："张爷爷的血压有没有异常？"
院长问："这周哪个老人需要重点关注？"
```

这些问题不是 SQL 能直接查的——"最近情况怎么样"要综合体温、血压、情绪、饮食多个维度，"有没有异常"要对比历史基线，"哪个老人需要重点关注"要跨老人横向比较。这种多步推理 + 多工具调用的场景，正是 Agent 的主场。

```
趋势分析 Agent 的工作流：
  用户问"王奶奶最近7天血压趋势"
    ↓
  Agent 推理：要查王奶奶最近7天的血压记录
    ↓ 调 search_history 工具
  检索到 7 条记录，提取血压数值
    ↓ 调 compare_vitals 工具
  对比发现：血压先升后降，峰值在 Day 5
    ↓ 调 detect_anomaly_trend 工具
  检测到 Day 4-5 血压超标，属于异常趋势
    ↓
  Agent 总结："王奶奶最近7天血压先升后降，Day5达到峰值152/98，
             属于高血压。Day6 吃降压药后开始下降，建议持续关注。"
```

> **前端类比：** 这就像前端的搜索 + 聚合查询——用户搜"王奶奶"，前端不只是返回搜索结果列表，还要算出"最近 7 天血压趋势图""异常天数统计""风险等级"。只不过前端是调多个 API 聚合，Agent 是调多个工具推理。区别是 Agent 能根据问题**动态决定**调哪些工具、调几次——前端是写死的聚合逻辑，Agent 是 LLM 现场推理出来的。

### 4.2 三个工具设计

趋势分析 Agent 需要三个工具，分别对应趋势分析的三个层次：检索 → 对比 → 检测。

| 工具 | 作用 | 输入 | 输出 | 前端类比 |
|------|------|------|------|---------|
| `search_history` | 带过滤的向量检索 | elderly_id, query, date_range | 历史记录列表 | 搜索 API（带筛选条件） |
| `compare_vitals` | 对比今天和历史的生命体征 | today_vitals, historical_vitals | 对比报告 | 数据对比组件 |
| `detect_anomaly_trend` | 检测异常趋势 | vital_series, thresholds | 异常趋势列表 | 异常检测算法 |

三个工具的依赖关系是递进的：

```
search_history（检索原始数据）
    ↓ 输出历史记录
compare_vitals（对比提取数值）
    ↓ 输出对比报告
detect_anomaly_trend（分析趋势异常）
    ↓ 输出最终结论
```

Agent 会根据问题**动态选择**调哪个工具、调几次。简单问题可能只调 `search_history` 就够了，复杂问题三个都要调。

### 4.3 工具1：search_history（带 filter 的向量检索）

第一个工具是基础——从 Qdrant 检索历史记录。关键是用 filter 限定范围（指定老人 + 日期范围），否则查出来的是全院记录混在一起。

```python
from langchain.tools import tool
from qdrant_client import models
from langchain_qdrant import QdrantVectorStore
from langchain_openai import OpenAIEmbeddings


@tool
def search_history(elderly_id: str, query: str,
                   start_date: str = "", end_date: str = "",
                   record_type: str = "", k: int = 10) -> str:
    """检索老人的历史护理记录。

    根据老人ID和查询条件，从向量库检索相关的历史记录。
    可按日期范围和记录类型过滤。

    Args:
        elderly_id: 老人ID，如 "W001"（王奶奶）
        query: 查询内容，如 "血压变化" "情绪状态" "饮食情况"
        start_date: 开始日期（可选），格式 "2026-07-01"
        end_date: 结束日期（可选），格式 "2026-07-07"
        record_type: 记录类型（可选），如 "vitals" "diet" "emotion"
        k: 返回记录数，默认10

    Returns:
        检索到的历史记录列表，含日期和生命体征
    """
    # 构建 filter 条件
    must_conditions = [
        models.FieldCondition(
            key="elderly_id",
            match=models.MatchValue(value=elderly_id),
        )
    ]

    # 日期范围过滤（ISO格式字符串可字典序比较）
    if start_date or end_date:
        date_range = models.Range()
        if start_date:
            date_range.gte = start_date
        if end_date:
            date_range.lte = end_date
        must_conditions.append(
            models.FieldCondition(key="date", range=date_range)
        )

    # 记录类型过滤
    if record_type:
        must_conditions.append(
            models.FieldCondition(
                key="record_type",
                match=models.MatchValue(value=record_type),
            )
        )

    filter_obj = models.Filter(must=must_conditions)

    # 执行向量检索
    results = VECTOR_STORE.similarity_search(
        query=query, k=k, filter=filter_obj
    )

    # 格式化结果，方便 LLM 阅读推理
    if not results:
        return f"未找到 {elderly_id} 在指定条件下的历史记录。"

    output_lines = [f"找到 {len(results)} 条历史记录："]
    for i, doc in enumerate(results, 1):
        meta = doc.metadata
        date_str = meta.get("date", "未知日期")
        output_lines.append(f"\n[{i}] 日期:{date_str}")
        output_lines.append(f"    内容:{doc.page_content}")
        vital = meta.get("vital_values", {})
        if vital:
            output_lines.append(
                f"    体征: 体温={vital.get('temperature')}℃ "
                f"血压={vital.get('systolic')}/{vital.get('diastolic')}mmHg "
                f"心率={vital.get('heart_rate')}bpm"
            )
    return "\n".join(output_lines)
```

> **filter 的精髓在 `must` 列表：** 每个 `FieldCondition` 是一个条件，`must` 表示 AND（全部满足）。还有 `should`（OR，至少满足一个）和 `must_not`（NOT，不能满足）。养老场景最常用 `must`——"老人是王奶奶 AND 日期在最近7天 AND 类型是生命体征"，三个条件全要满足。

### 4.4 工具2：compare_vitals（对比今天和历史的生命体征）

第二个工具做对比——今天的血压 vs 历史 7 天的平均血压，是高了还是低了。这是趋势分析的核心——单看今天的数值看不出问题，对比历史才能发现趋势。

```python
@tool
def compare_vitals(elderly_id: str, today_temperature: float,
                   today_systolic: int, today_diastolic: int,
                   today_heart_rate: int = 0) -> str:
    """对比今天的生命体征和历史平均值，判断是偏高还是偏低。

    从向量库检索该老人最近7天的历史记录，
    计算生命体征的平均值，和今天的数值对比。

    Args:
        elderly_id: 老人ID
        today_temperature: 今天体温
        today_systolic: 今天收缩压
        today_diastolic: 今天舒张压
        today_heart_rate: 今天心率（可选）

    Returns:
        对比报告：今天 vs 历史7天均值，偏高/偏低/正常
    """
    # 检索最近7天的历史记录
    history_results = VECTOR_STORE.similarity_search(
        query="体温血压心率生命体征",
        k=20,  # 多取一些确保覆盖7天
        filter=models.Filter(must=[
            models.FieldCondition(
                key="elderly_id",
                match=models.MatchValue(value=elderly_id),
            ),
            models.FieldCondition(
                key="record_type",
                match=models.MatchValue(value="vitals"),
            ),
        ]),
    )

    if not history_results:
        return f"未找到 {elderly_id} 的历史生命体征记录，无法对比。"

    # 提取历史数值
    temps, sys_list, dia_list, hr_list = [], [], [], []
    for doc in history_results:
        vital = doc.metadata.get("vital_values", {})
        if vital.get("temperature") is not None:
            temps.append(vital["temperature"])
        if vital.get("systolic") is not None:
            sys_list.append(vital["systolic"])
        if vital.get("diastolic") is not None:
            dia_list.append(vital["diastolic"])
        if vital.get("heart_rate") is not None:
            hr_list.append(vital["heart_rate"])

    # 计算历史平均值
    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    avg_temp = avg(temps)
    avg_sys = avg(sys_list)
    avg_dia = avg(dia_list)
    avg_hr = avg(hr_list)

    # 对比判断
    report_lines = [f"=== {elderly_id} 生命体征对比报告 ==="]
    report_lines.append(f"历史记录数: {len(history_results)} 条\n")

    comparisons = []

    # 体温对比
    if avg_temp:
        diff = round(today_temperature - avg_temp, 1)
        status = "偏高" if diff > 0.5 else ("偏低" if diff < -0.5 else "正常")
        comparisons.append(
            f"体温: 今日{today_temperature}℃ vs 历史{avg_temp}℃ "
            f"(差{diff}℃, {status})"
        )

    # 收缩压对比
    if avg_sys:
        diff = today_systolic - avg_sys
        status = "偏高" if diff > 10 else ("偏低" if diff < -10 else "正常")
        comparisons.append(
            f"收缩压: 今日{today_systolic}mmHg vs 历史{avg_sys}mmHg "
            f"(差{diff}, {status})"
        )

    # 舒张压对比
    if avg_dia:
        diff = today_diastolic - avg_dia
        status = "偏高" if diff > 5 else ("偏低" if diff < -5 else "正常")
        comparisons.append(
            f"舒张压: 今日{today_diastolic}mmHg vs 历史{avg_dia}mmHg "
            f"(差{diff}, {status})"
        )

    # 心率对比
    if avg_hr and today_heart_rate > 0:
        diff = today_heart_rate - avg_hr
        status = "偏快" if diff > 10 else ("偏慢" if diff < -10 else "正常")
        comparisons.append(
            f"心率: 今日{today_heart_rate}bpm vs 历史{avg_hr}bpm "
            f"(差{diff}, {status})"
        )

    report_lines.extend(comparisons)
    report_lines.append(f"\n历史均值: 体温{avg_temp}℃ 血压{avg_sys}/{avg_dia}mmHg 心率{avg_hr}bpm")

    return "\n".join(report_lines)
```

### 4.5 工具3：detect_anomaly_trend（检测异常趋势）

第三个工具最关键——它不只是对比，而是检测**趋势**。"先升后降""连续 3 天偏高""突升突降"这些都是趋势异常。这个工具要从一堆数值里看出趋势模式。

```python
@tool
def detect_anomaly_trend(elderly_id: str, metric: str = "systolic",
                         days: int = 7) -> str:
    """检测老人生命体征的异常趋势。

    从历史记录中提取指定指标的数值序列，
    分析趋势模式：持续上升/下降、突升突降、连续超标等。

    Args:
        elderly_id: 老人ID
        metric: 分析指标，可选 "systolic"(收缩压) "diastolic"(舒张压)
                "temperature"(体温) "heart_rate"(心率)
        days: 分析最近多少天，默认7

    Returns:
        异常趋势分析报告
    """
    # 检索历史记录
    history_results = VECTOR_STORE.similarity_search(
        query=f"{metric} 变化趋势",
        k=20,
        filter=models.Filter(must=[
            models.FieldCondition(
                key="elderly_id",
                match=models.MatchValue(value=elderly_id),
            ),
        ]),
    )

    if not history_results:
        return f"未找到 {elderly_id} 的历史记录，无法分析趋势。"

    # 按日期排序，提取指标序列
    records_by_date = {}
    for doc in history_results:
        meta = doc.metadata
        date_str = meta.get("date", "")
        vital = meta.get("vital_values", {})
        value = vital.get(metric)
        if value is not None and date_str:
            records_by_date[date_str] = value

    if not records_by_date:
        return f"未找到 {elderly_id} 的 {metric} 数据。"

    # 按日期排序
    sorted_dates = sorted(records_by_date.keys())
    values = [records_by_date[d] for d in sorted_dates]
    metric_name = {
        "systolic": "收缩压", "diastolic": "舒张压",
        "temperature": "体温", "heart_rate": "心率",
    }.get(metric, metric)

    # 趋势分析
    report_lines = [
        f"=== {elderly_id} {metric_name}趋势分析（最近{len(values)}条记录）===",
    ]

    # 数值序列
    for date, val in zip(sorted_dates, values):
        report_lines.append(f"  {date}: {metric_name}={val}")

    if len(values) < 2:
        report_lines.append("数据不足，无法分析趋势。")
        return "\n".join(report_lines)

    # 计算趋势指标
    max_val = max(values)
    min_val = min(values)
    max_idx = values.index(max_val)
    min_idx = values.index(min_val)
    first_val = values[0]
    last_val = values[-1]
    overall_change = round(last_val - first_val, 1)

    # 异常阈值
    thresholds = {
        "systolic": 140, "diastolic": 90,
        "temperature": 37.3, "heart_rate": 100,
    }
    threshold = thresholds.get(metric, float("inf"))

    # 检测异常模式
    anomalies = []

    # 1. 检测峰值位置和先升后降模式
    if max_idx > 0 and max_idx < len(values) - 1:
        before = values[:max_idx]
        after = values[max_idx:]
        if all(after[i] <= after[i - 1] for i in range(1, len(after))):
            anomalies.append(
                f"先升后降模式：{metric_name}在第{max_idx + 1}条记录"
                f"达到峰值{max_val}，之后持续下降至{last_val}"
            )

    # 2. 检测连续超标
    over_threshold = [i for i, v in enumerate(values) if v > threshold]
    if over_threshold:
        anomalies.append(
            f"连续超标：第{over_threshold[0] + 1}至{over_threshold[-1] + 1}条记录"
            f"的{metric_name}超过阈值{threshold}（最高{max_val}）"
        )

    # 3. 检测突升突降
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        if metric in ("systolic", "diastolic") and abs(change) >= 15:
            direction = "突升" if change > 0 else "突降"
            anomalies.append(
                f"{direction}异常：第{i}条到第{i + 1}条记录"
                f"{metric_name}变化{change}（从{values[i - 1]}到{values[i]}）"
            )
        elif metric == "temperature" and abs(change) >= 1.0:
            direction = "突升" if change > 0 else "突降"
            anomalies.append(
                f"{direction}异常：第{i}条到第{i + 1}条记录"
                f"体温变化{change}℃（从{values[i - 1]}到{values[i]}℃）"
            )

    # 4. 整体趋势
    if overall_change > 0:
        trend_desc = f"整体上升趋势：从{first_val}升至{last_val}（+{overall_change}）"
    elif overall_change < 0:
        trend_desc = f"整体下降趋势：从{first_val}降至{last_val}（{overall_change}）"
    else:
        trend_desc = f"整体平稳：始终在{first_val}附近"

    report_lines.append(f"\n--- 趋势分析 ---")
    report_lines.append(trend_desc)
    report_lines.append(f"峰值: {max_val}（第{max_idx + 1}条）  谷值: {min_val}（第{min_idx + 1}条）")

    if anomalies:
        report_lines.append(f"\n--- 检测到 {len(anomalies)} 个异常 ---")
        for i, a in enumerate(anomalies, 1):
            report_lines.append(f"  [{i}] {a}")
    else:
        report_lines.append("\n未检测到明显异常趋势。")

    return "\n".join(report_lines)
```

> **趋势检测的三种模式：** 先升后降（峰值在中间）、连续超标（多天超阈值）、突升突降（相邻天差值大）。这三种覆盖了养老场景最常见的生命体征异常模式。实际生产还可以加"连续 N 天上升/下降""波动率超标"等，但这三个已经能抓住 80% 的问题。

### 4.6 完整 trend_agent.py

下面是完整的趋势分析 Agent，把三个工具组装起来。模型用 `init_chat_model` 统一初始化，可切换 OpenAI / Ollama：

```python
"""trend_agent.py — 趋势分析 Agent

养老护工智能记录系统 Day 05 产出
功能：把护工记录存入 Qdrant 向量库，做趋势分析（血压/体温/情绪变化）

依赖（2026 版本）：
    pip install langchain langgraph langchain-qdrant qdrant-client langchain-openai
运行：python trend_agent.py
"""
from uuid import uuid4
from datetime import date, timedelta

from langchain.agents import create_agent
from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client import models
from langchain_openai import OpenAIEmbeddings
from pydantic import BaseModel, Field, model_validator
from typing import Optional


# ============================================================
# 第一部分：CareRecord 模型（复用 Day 02，简化版）
# ============================================================

class Vitals(BaseModel):
    """生命体征"""
    temperature: Optional[float] = Field(default=None, description="体温℃")
    systolic: Optional[int] = Field(default=None, description="收缩压mmHg")
    diastolic: Optional[int] = Field(default=None, description="舒张压mmHg")
    heart_rate: Optional[int] = Field(default=None, description="心率bpm")

    @model_validator(mode="after")
    def check_ranges(self):
        """字段级范围校验：防 LLM 提取出错"""
        if self.temperature is not None and not (30 <= self.temperature <= 45):
            raise ValueError(f"体温{self.temperature}不在合理范围30-45℃")
        if self.systolic is not None and not (60 <= self.systolic <= 250):
            raise ValueError(f"收缩压{self.systolic}不合理")
        if self.diastolic is not None and not (40 <= self.diastolic <= 150):
            raise ValueError(f"舒张压{self.diastolic}不合理")
        return self


class CareRecord(BaseModel):
    """养老护工记录——趋势分析的数据源"""
    name: str = Field(description="老人姓名")
    room: Optional[str] = Field(default=None, description="房间号")
    vitals: Vitals = Field(default_factory=Vitals, description="生命体征")
    emotion: str = Field(default="未说明", description="情绪状态")
    notes: Optional[str] = Field(default=None, description="其他备注")
    anomalies: list[str] = Field(default_factory=list, description="异常标记")

    @model_validator(mode="after")
    def auto_flag_anomalies(self):
        """自动标记异常（复用 Day 02 的逻辑）"""
        v = self.vitals
        if v.temperature is not None and v.temperature > 37.3:
            self.anomalies.append(f"体温偏高({v.temperature}℃)")
        if v.systolic is not None and v.systolic > 140:
            self.anomalies.append(f"收缩压偏高({v.systolic}mmHg)")
        if v.diastolic is not None and v.diastolic > 90:
            self.anomalies.append(f"舒张压偏高({v.diastolic}mmHg)")
        if v.heart_rate is not None and v.heart_rate > 100:
            self.anomalies.append(f"心率过快({v.heart_rate}bpm)")
        return self


# ============================================================
# 第二部分：向量库初始化 + 数据入库
# ============================================================

# 全局向量库实例（工具函数共享）
VECTOR_STORE: QdrantVectorStore = None


def init_vector_store(use_openai: bool = True) -> QdrantVectorStore:
    """初始化 Qdrant 向量库。

    2026 用法：langchain-qdrant 包的 QdrantVectorStore 类
    内存模式开发零部署，生产改成 host/port 连 Docker。
    """
    global VECTOR_STORE

    client = QdrantClient(":memory:")

    # embedding 模型：有 OpenAI key 用 OpenAI，否则用 Ollama 本地
    if use_openai:
        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    else:
        from langchain_ollama import OllamaEmbeddings
        embeddings = OllamaEmbeddings(model="nomic-embed-text")

    VECTOR_STORE = QdrantVectorStore(
        client=client,
        collection_name="care_records",
        embedding=embeddings,
    )
    return VECTOR_STORE


def record_to_text(record: CareRecord, record_date: str) -> str:
    """CareRecord → 可检索文本（拍平成自然语言段落）"""
    v = record.vitals
    parts = [f"{record.name}({record.room or '房间未登记'}) {record_date}记录："]

    vital_parts = []
    if v.temperature is not None:
        vital_parts.append(f"体温{v.temperature}℃")
    if v.systolic is not None and v.diastolic is not None:
        vital_parts.append(f"血压{v.systolic}/{v.diastolic}mmHg")
    if v.heart_rate is not None:
        vital_parts.append(f"心率{v.heart_rate}bpm")
    if vital_parts:
        parts.append("，".join(vital_parts) + "。")

    parts.append(f"情绪{record.emotion}。")
    if record.notes:
        parts.append(f"备注：{record.notes}。")
    parts.append("异常：" + "、".join(record.anomalies) if record.anomalies else "无异常。")
    return "".join(parts)


def record_to_metadata(record: CareRecord, elderly_id: str,
                       record_date: str, worker_id: str) -> dict:
    """生成 metadata，供 Qdrant filter 使用"""
    v = record.vitals
    return {
        "elderly_id": elderly_id,
        "date": record_date,
        "record_type": "vitals",
        "worker_id": worker_id,
        "is_abnormal": len(record.anomalies) > 0,
        "vital_values": {
            "temperature": v.temperature,
            "systolic": v.systolic,
            "diastolic": v.diastolic,
            "heart_rate": v.heart_rate,
        },
        "emotion": record.emotion,
    }


def seed_sample_data(vector_store: QdrantVectorStore):
    """灌入7天模拟数据：王奶奶血压先升后降的典型趋势"""
    base_date = date(2026, 7, 1)
    sample_data = [
        # 血压正常 → 升高 → 峰值 → 下降（吃药后恢复）
        (Vitals(temperature=36.5, systolic=125, diastolic=80, heart_rate=72),
         "平静", "一切正常", False),
        (Vitals(temperature=36.6, systolic=128, diastolic=82, heart_rate=74),
         "平静", "状态稳定", False),
        (Vitals(temperature=36.8, systolic=138, diastolic=88, heart_rate=78),
         "焦虑", "说有点头晕", False),
        (Vitals(temperature=37.0, systolic=145, diastolic=92, heart_rate=82),
         "烦躁", "头晕加重，血压偏高", True),
        (Vitals(temperature=37.2, systolic=152, diastolic=98, heart_rate=85),
         "低落", "头晕厉害，没怎么吃饭", True),
        (Vitals(temperature=36.9, systolic=140, diastolic=90, heart_rate=80),
         "好转", "吃了降压药，头晕减轻", True),
        (Vitals(temperature=36.7, systolic=132, diastolic=85, heart_rate=75),
         "平静", "血压降下来了，精神恢复", False),
    ]

    records = []
    for i, (vitals, emotion, notes, _) in enumerate(sample_data):
        record_date = (base_date + timedelta(days=i)).isoformat()
        record = CareRecord(
            name="王奶奶", room="302",
            vitals=vitals, emotion=emotion, notes=notes,
        )
        records.append((record, "W001", record_date, "小李"))

    # 批量入库
    texts = [record_to_text(r, d) for r, _, d, _ in records]
    metadatas = [record_to_metadata(r, eid, d, w) for r, eid, d, w in records]

    print("正在入库 7 天护工记录...")
    for text in texts:
        print(f"  -> {text[:60]}...")

    ids = vector_store.add_texts(texts=texts, metadatas=metadatas)
    print(f"\n入库完成，共 {len(ids)} 条记录，IDs: {ids}\n")


# ============================================================
# 第三部分：三个趋势分析工具
# ============================================================

@tool
def search_history(elderly_id: str, query: str,
                   start_date: str = "", end_date: str = "",
                   record_type: str = "", k: int = 10) -> str:
    """检索老人的历史护理记录。

    从向量库检索与查询相关的历史记录，可按日期范围和记录类型过滤。
    当需要查看老人的历史血压、体温、情绪等记录时使用此工具。

    Args:
        elderly_id: 老人ID，如 "W001"（王奶奶）
        query: 查询内容，如 "血压变化" "情绪状态" "体温记录"
        start_date: 开始日期（可选），格式 "2026-07-01"
        end_date: 结束日期（可选），格式 "2026-07-07"
        record_type: 记录类型（可选），如 "vitals"
        k: 返回记录数，默认10

    Returns:
        检索到的历史记录列表
    """
    # 构建 Qdrant filter（must = AND 条件）
    must_conditions = [
        models.FieldCondition(
            key="elderly_id",
            match=models.MatchValue(value=elderly_id),
        )
    ]

    # 日期范围过滤
    if start_date or end_date:
        date_range = models.Range()
        if start_date:
            date_range.gte = start_date
        if end_date:
            date_range.lte = end_date
        must_conditions.append(
            models.FieldCondition(key="date", range=date_range)
        )

    # 记录类型过滤
    if record_type:
        must_conditions.append(
            models.FieldCondition(
                key="record_type",
                match=models.MatchValue(value=record_type),
            )
        )

    filter_obj = models.Filter(must=must_conditions)

    # 执行向量检索
    results = VECTOR_STORE.similarity_search(
        query=query, k=k, filter=filter_obj
    )

    if not results:
        return f"未找到 {elderly_id} 在指定条件下的历史记录。"

    # 格式化输出
    output_lines = [f"找到 {len(results)} 条历史记录："]
    for i, doc in enumerate(results, 1):
        meta = doc.metadata
        date_str = meta.get("date", "未知日期")
        output_lines.append(f"\n[{i}] 日期:{date_str}")
        output_lines.append(f"    内容:{doc.page_content}")
        vital = meta.get("vital_values", {})
        if vital.get("systolic") is not None:
            output_lines.append(
                f"    体征: 体温={vital.get('temperature')}℃ "
                f"血压={vital.get('systolic')}/{vital.get('diastolic')}mmHg "
                f"心率={vital.get('heart_rate')}bpm"
            )
    return "\n".join(output_lines)


@tool
def compare_vitals(elderly_id: str, today_temperature: float,
                   today_systolic: int, today_diastolic: int,
                   today_heart_rate: int = 0) -> str:
    """对比今天的生命体征和历史平均值。

    检索该老人最近的历史记录，计算生命体征平均值，
    和今天的数值对比，判断偏高/偏低/正常。

    当护工报告了今天的生命体征，需要和历史对比时使用此工具。

    Args:
        elderly_id: 老人ID
        today_temperature: 今天体温（℃）
        today_systolic: 今天收缩压（mmHg）
        today_diastolic: 今天舒张压（mmHg）
        today_heart_rate: 今天心率（bpm，可选）

    Returns:
        对比报告：今天 vs 历史均值
    """
    # 检索历史记录
    history_results = VECTOR_STORE.similarity_search(
        query="体温血压心率生命体征记录",
        k=20,
        filter=models.Filter(must=[
            models.FieldCondition(
                key="elderly_id",
                match=models.MatchValue(value=elderly_id),
            ),
            models.FieldCondition(
                key="record_type",
                match=models.MatchValue(value="vitals"),
            ),
        ]),
    )

    if not history_results:
        return f"未找到 {elderly_id} 的历史生命体征记录，无法对比。"

    # 提取历史数值
    temps, sys_list, dia_list, hr_list = [], [], [], []
    for doc in history_results:
        vital = doc.metadata.get("vital_values", {})
        if vital.get("temperature") is not None:
            temps.append(vital["temperature"])
        if vital.get("systolic") is not None:
            sys_list.append(vital["systolic"])
        if vital.get("diastolic") is not None:
            dia_list.append(vital["diastolic"])
        if vital.get("heart_rate") is not None:
            hr_list.append(vital["heart_rate"])

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    avg_temp, avg_sys, avg_dia, avg_hr = avg(temps), avg(sys_list), avg(dia_list), avg(hr_list)

    # 生成对比报告
    lines = [f"=== {elderly_id} 生命体征对比报告 ===",
             f"历史记录数: {len(history_results)} 条\n"]

    if avg_temp:
        diff = round(today_temperature - avg_temp, 1)
        status = "偏高" if diff > 0.5 else ("偏低" if diff < -0.5 else "正常")
        lines.append(f"体温: 今日{today_temperature}℃ vs 均值{avg_temp}℃ (差{diff}, {status})")

    if avg_sys:
        diff = today_systolic - avg_sys
        status = "偏高" if diff > 10 else ("偏低" if diff < -10 else "正常")
        lines.append(f"收缩压: 今日{today_systolic} vs 均值{avg_sys} (差{diff}, {status})")

    if avg_dia:
        diff = today_diastolic - avg_dia
        status = "偏高" if diff > 5 else ("偏低" if diff < -5 else "正常")
        lines.append(f"舒张压: 今日{today_diastolic} vs 均值{avg_dia} (差{diff}, {status})")

    if avg_hr and today_heart_rate > 0:
        diff = today_heart_rate - avg_hr
        status = "偏快" if diff > 10 else ("偏慢" if diff < -10 else "正常")
        lines.append(f"心率: 今日{today_heart_rate} vs 均值{avg_hr} (差{diff}, {status})")

    lines.append(f"\n历史均值: 体温{avg_temp}℃ 血压{avg_sys}/{avg_dia} 心率{avg_hr}bpm")
    return "\n".join(lines)


@tool
def detect_anomaly_trend(elderly_id: str, metric: str = "systolic",
                          days: int = 7) -> str:
    """检测老人生命体征的异常趋势。

    分析指定指标的历史数值序列，检测：
    - 先升后降模式（峰值在中间）
    - 连续超标（多天超过阈值）
    - 突升突降（相邻记录差值过大）

    当需要分析血压/体温/心率的长期变化趋势时使用此工具。

    Args:
        elderly_id: 老人ID
        metric: 分析指标，可选 "systolic" "diastolic" "temperature" "heart_rate"
        days: 分析最近多少天，默认7

    Returns:
        异常趋势分析报告
    """
    # 检索历史记录
    history_results = VECTOR_STORE.similarity_search(
        query=f"{metric} 变化趋势",
        k=20,
        filter=models.Filter(must=[
            models.FieldCondition(
                key="elderly_id",
                match=models.MatchValue(value=elderly_id),
            ),
        ]),
    )

    if not history_results:
        return f"未找到 {elderly_id} 的历史记录，无法分析趋势。"

    # 按日期排序，提取指标序列
    records_by_date = {}
    for doc in history_results:
        meta = doc.metadata
        date_str = meta.get("date", "")
        vital = meta.get("vital_values", {})
        value = vital.get(metric)
        if value is not None and date_str:
            records_by_date[date_str] = value

    if not records_by_date:
        return f"未找到 {elderly_id} 的 {metric} 数据。"

    sorted_dates = sorted(records_by_date.keys())
    values = [records_by_date[d] for d in sorted_dates]
    metric_names = {
        "systolic": "收缩压", "diastolic": "舒张压",
        "temperature": "体温", "heart_rate": "心率",
    }
    metric_name = metric_names.get(metric, metric)

    lines = [f"=== {elderly_id} {metric_name}趋势分析（{len(values)}条记录）==="]
    for d, v in zip(sorted_dates, values):
        lines.append(f"  {d}: {metric_name}={v}")

    if len(values) < 2:
        lines.append("数据不足，无法分析趋势。")
        return "\n".join(lines)

    # 趋势分析
    max_val, min_val = max(values), min(values)
    max_idx, min_idx = values.index(max_val), values.index(min_val)
    first_val, last_val = values[0], values[-1]
    overall = round(last_val - first_val, 1)

    # 异常阈值
    thresholds = {"systolic": 140, "diastolic": 90,
                  "temperature": 37.3, "heart_rate": 100}
    threshold = thresholds.get(metric, float("inf"))

    anomalies = []

    # 1. 先升后降
    if 0 < max_idx < len(values) - 1:
        after = values[max_idx:]
        if all(after[i] <= after[i - 1] for i in range(1, len(after))):
            anomalies.append(
                f"先升后降：{metric_name}在第{max_idx + 1}条达峰值{max_val}，"
                f"之后下降至{last_val}"
            )

    # 2. 连续超标
    over = [i for i, v in enumerate(values) if v > threshold]
    if over:
        anomalies.append(
            f"连续超标：第{over[0]+1}至{over[-1]+1}条{metric_name}"
            f"超阈值{threshold}（最高{max_val}）"
        )

    # 3. 突升突降
    jump_threshold = 15 if metric in ("systolic", "diastolic") else 1.0
    for i in range(1, len(values)):
        change = round(values[i] - values[i-1], 1)
        if abs(change) >= jump_threshold:
            direction = "突升" if change > 0 else "突降"
            anomalies.append(
                f"{direction}：第{i}→{i+1}条{metric_name}变化{change}"
                f"（{values[i-1]}→{values[i]}）"
            )

    # 整体趋势
    if overall > 0:
        trend = f"整体上升：{first_val}→{last_val}（+{overall}）"
    elif overall < 0:
        trend = f"整体下降：{first_val}→{last_val}（{overall}）"
    else:
        trend = f"整体平稳：始终在{first_val}附近"

    lines.append(f"\n--- 趋势分析 ---")
    lines.append(trend)
    lines.append(f"峰值: {max_val}（第{max_idx+1}条）  谷值: {min_val}（第{min_idx+1}条）")

    if anomalies:
        lines.append(f"\n--- 检测到 {len(anomalies)} 个异常 ---")
        for i, a in enumerate(anomalies, 1):
            lines.append(f"  [{i}] {a}")
    else:
        lines.append("\n未检测到明显异常趋势。")

    return "\n".join(lines)


# ============================================================
# 第四部分：趋势分析 Agent 组装 + 运行
# ============================================================

TREND_SYSTEM_PROMPT = """你是养老护理趋势分析助手。

你的职责是分析老人的历史护理记录，发现生命体征和情绪的变化趋势，
为护工和家属提供趋势洞察和异常预警。

你可以使用以下工具：
1. search_history：检索老人的历史记录（可按日期、类型过滤）
2. compare_vitals：对比今天的生命体征和历史平均值
3. detect_anomaly_trend：检测生命体征的异常趋势

分析原则：
- 趋势比单次数值更重要：先升后降、连续超标、突升突降都是关注点
- 结合情绪和体征综合判断：血压升高+情绪低落比单纯血压高更需关注
- 给出可执行建议：不要只说"异常"，要说"建议关注""建议通知家属""建议就医"

回答格式：
- 先给结论（趋势是什么）
- 再给数据支撑（具体数值变化）
- 最后给建议（该怎么做）"""


def build_trend_agent(model: str = "openai:gpt-4o-mini"):
    """创建趋势分析 Agent。

    用 create_agent + @tool 搭建，工具包括：
    - search_history：向量检索历史记录
    - compare_vitals：对比今天 vs 历史生命体征
    - detect_anomaly_trend：检测异常趋势
    """
    llm = init_chat_model(model)
    return create_agent(
        model=llm,
        tools=[search_history, compare_vitals, detect_anomaly_trend],
        system_prompt=TREND_SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )


def run_trend_analysis(agent, question: str, thread_id: str = None):
    """运行趋势分析并格式化输出"""
    config = {"configurable": {"thread_id": thread_id or f"trend-{uuid4()}"}}

    print(f"\n{'='*60}")
    print(f"问题：{question}")
    print(f"{'='*60}")

    result = agent.invoke(
        {"messages": [HumanMessage(content=question)]},
        config=config,
    )

    # 提取最终回答
    final_msg = result["messages"][-1]
    print(f"\n回答：\n{final_msg.content}")

    # 打印工具调用过程
    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    if tool_msgs:
        print(f"\n--- 工具调用过程（{len(tool_msgs)}次）---")
        for tm in tool_msgs:
            # 截断过长的工具输出
            content = tm.content
            if len(content) > 200:
                content = content[:200] + "...(截断)"
            print(f"  [{tm.name}] {content}")

    return result


# ============================================================
# 主程序入口
# ============================================================

if __name__ == "__main__":
    # 1. 初始化向量库（内存模式，开发零部署）
    print("=" * 60)
    print("Step 1: 初始化 Qdrant 向量库")
    print("=" * 60)
    vector_store = init_vector_store(use_openai=True)

    # 2. 灌入 7 天模拟数据
    print("\n" + "=" * 60)
    print("Step 2: 灌入 7 天护工记录（王奶奶血压先升后降）")
    print("=" * 60)
    seed_sample_data(vector_store)

    # 3. 创建趋势分析 Agent
    print("=" * 60)
    print("Step 3: 创建趋势分析 Agent")
    print("=" * 60)
    agent = build_trend_agent(model="openai:gpt-4o-mini")
    print("Agent 创建完成，工具：search_history / compare_vitals / detect_anomaly_trend\n")

    # 4. 跑三个趋势分析场景
    print("=" * 60)
    print("Step 4: 趋势分析场景演示")
    print("=" * 60)

    # 场景1：查最近7天血压趋势
    run_trend_analysis(
        agent,
        question="王奶奶最近7天的血压有什么变化趋势？需要关注吗？",
        thread_id="trend-blood-pressure",
    )

    # 场景2：对比今天的血压和历史
    run_trend_analysis(
        agent,
        question="王奶奶今天血压148/95，和历史比怎么样？算异常吗？",
        thread_id="trend-compare-today",
    )

    # 场景3：检测体温异常趋势
    run_trend_analysis(
        agent,
        question="王奶奶最近的体温有没有异常趋势？",
        thread_id="trend-temperature",
    )
```

> **2026 API 注意事项：**
> - `QdrantVectorStore` 从 `langchain_qdrant` 来（不是旧的 `langchain_community.vectorstores.Qdrant`）
> - `Filter / FieldCondition / MatchValue / Range` 从 `qdrant_client.models` 来
> - `create_agent` 从 `langchain.agents` 来
> - `@tool` 从 `langchain.tools` 来
> - `init_chat_model` 从 `langchain.chat_models` 来
> - Embedding 用 `langchain_openai.OpenAIEmbeddings` 或 `langchain_ollama.OllamaEmbeddings`

### 4.7 趋势分析示例输出

跑完上面的代码，预期输出类似这样：

```
============================================================
问题：王奶奶最近7天的血压有什么变化趋势？需要关注吗？
============================================================

--- 工具调用过程（2次）---
  [search_history] 找到 7 条历史记录：
    [1] 日期:2026-07-01  内容:王奶奶(房间302) 2026-07-01记录：体温36.5℃，血压125/80mmHg...
    [2] 日期:2026-07-02  内容:王奶奶(房间302) 2026-07-02记录：体温36.6℃，血压128/82mmHg...
    ...
    [5] 日期:2026-07-05  内容:王奶奶(房间302) 2026-07-05记录：体温37.2℃，血压152/98mmHg...
    ...
  [detect_anomaly_trend] === W001 收缩压趋势分析（7条记录）===
    2026-07-01: 收缩压=125
    2026-07-02: 收缩压=128
    ...
    2026-07-05: 收缩压=152  ← 峰值
    ...
    --- 检测到 2 个异常 ---
    [1] 先升后降：收缩压在第5条达峰值152，之后下降至132
    [2] 连续超标：第4至6条收缩压超阈值140（最高152）

回答：
王奶奶最近7天血压呈现"先升后降"趋势，需要重点关注：

1. 趋势概述：血压从7月1日的125/80逐步攀升，7月5日达到峰值152/98（高血压），
   7月6日起开始下降，7月7日回落至132/85。

2. 数据支撑：
   - 收缩压：125→128→138→145→152→140→132（先升后降，峰值Day5）
   - 舒张压：80→82→88→92→98→90→85（同步先升后降）
   - 连续3天（Day4-6）收缩压超过140mmHg阈值

3. 建议：
   - Day5血压峰值152/98已达高血压标准，建议通知家属
   - Day6起血压开始下降（吃了降压药），说明用药有效
   - 建议持续监测，如果血压再次升高需就医调整用药
```

这个输出体现了趋势分析 Agent 的三个层次：检索（search_history 找到 7 条记录）→ 分析（detect_anomaly_trend 检测到先升后降 + 连续超标）→ 建议（通知家属 + 持续监测）。从单次记录到趋势洞察，这就是养老系统从"记事本"升级成"健康守门人"的价值。

---

## 动手实验

### 🟢 青铜：跑通 trend_agent.py

1. 安装依赖：`pip install langchain langgraph langchain-qdrant qdrant-client langchain-openai`
2. 配置 OpenAI API Key（`export OPENAI_API_KEY=sk-...`），或改成 Ollama 本地模型
3. 运行 `python trend_agent.py`，观察三个场景的输出
4. 重点验证：场景 1 是否检测到了"先升后降"趋势？峰值在 Day 5 吗？

### 🟡 白银：切换 HYBRID 检索模式

1. 在 `init_vector_store` 里加 `sparse_embedding`（用 `fastembed.SparseTextEmbedding`）
2. 把 `retrieval_mode` 设成 `"hybrid"`
3. 对比 DENSE vs HYBRID：搜"头晕"这个关键词，HYBRID 能同时匹配语义和关键词吗？
4. 思考：养老场景的哪些查询适合 HYBRID？哪些纯 DENSE 就够？

```python
# 白银实验参考：HYBRID 模式初始化
from fastembed import SparseTextEmbedding

sparse_embedding = SparseTextEmbedding(model_name="Qdrant/bm25")
vector_store_hybrid = QdrantVectorStore(
    client=client,
    collection_name="care_records_hybrid",
    embedding=embeddings,
    sparse_embedding=sparse_embedding,
    retrieval_mode="hybrid",
)
```

### 🔴 王者：多老人横向对比 + 风险排序

1. 灌入 3 个老人（王奶奶/张爷爷/李爷爷）各 7 天数据
2. 扩展 Agent：加一个 `rank_elderly_risk` 工具，检索所有老人的异常趋势，按风险排序
3. 问 Agent："这周哪个老人最需要重点关注？"——它应该能横向对比 3 个老人的趋势，给出优先级排序
4. 思考：横向对比和单老人趋势分析的 Agent 设计有什么不同？（提示：先检索再聚合 vs 直接推理）

---

## 踩坑记录 🕳️

### 坑 1：`QdrantVectorStore` vs 旧版 `Qdrant` 类名混淆

```python
# ❌ 旧版（已废弃，会报 ImportError 或功能不全）
from langchain_community.vectorstores import Qdrant

# ✅ 2026 新版
from langchain_qdrant import QdrantVectorStore
```

**原因：** 2026 年 LangChain 把向量库集成拆成独立包，类名加了 `VectorStore` 后缀。旧版 `langchain_community` 里的 `Qdrant` 类不再维护。如果你看到教程用 `from langchain_community.vectorstores import Qdrant`，那是过时的。

**解决：** 装 `langchain-qdrant` 包，用 `QdrantVectorStore`。如果旧代码迁移，全局搜 `from langchain_community.vectorstores import Qdrant` 替换掉。

### 坑 2：metadata 里的 `None` 值导致 filter 报错

```python
# ❌ metadata 里有 None，Qdrant filter 遇到 None 报错
metadata = {"vital_values": {"temperature": None, "systolic": 135}}
# 查 vital_values.temperature 的 Range 过滤时报错

# ✅ 过滤前清洗 None，或用哨兵值
metadata = {"vital_values": {"temperature": 0.0, "systolic": 135}}  # 0.0 表示未测
```

**原因：** Qdrant 的 payload 不接受 `None` 值做范围过滤（`Range(gte=None)` 没意义）。养老记录里"没测体温"是常见的，如果直接存 `None`，后续 filter 就会炸。

**解决：** 入库前把 `None` 转成哨兵值（体温用 0.0，血压用 0），或者在 filter 前判断字段是否存在。更优雅的做法是用 `should` 条件配合 `models.IsNull()` 判断字段是否存在。

### 坑 3：日期字符串比较的格式陷阱

```python
# ❌ 日期格式不统一，字典序比较出错
"7-1" > "7-10"  # True！因为 "7-1" > "7-10"（字符串比较）
"2026-7-1" > "2026-07-10"  # True！月份没补零

# ✅ 统一用 ISO 格式（YYYY-MM-DD），补零
"2026-07-01" < "2026-07-10"  # True！正确
```

**原因：** Qdrant 的 `Range(gte/lte)` 对字符串做字典序比较。ISO 格式（`YYYY-MM-DD`）的字典序恰好等于时间序，但如果不补零（`2026-7-1`）就会出错。

**解决：** 入库时强制用 `date.isoformat()` 生成 `YYYY-MM-DD` 格式。如果原始数据是 `7月1日`，要先转成 `2026-07-01` 再存。

### 坑 4：内存模式数据不持久，重启全丢

```python
# 开发用内存模式很方便
client = QdrantClient(":memory:")

# 但程序一退出，数据全没了
# 下次运行要重新灌数据
```

**原因：** `:memory:` 模式数据存在进程内存里，进程结束即销毁。开发阶段没问题（反正每次重跑），但如果要做持久化测试或演示就尴尬了。

**解决：** 改成 `QdrantClient(path="./qdrant_data")` 落盘模式，数据存本地目录。或用 Docker 起一个 Qdrant 服务（`docker run -p 6333:6333 qdrant/qdrant`），`QdrantClient(host="localhost", port=6333)` 连上去。

### 坑 5：Agent 不调工具直接瞎编趋势

```python
# 问 Agent "王奶奶最近血压趋势"
# 期望它调 search_history 检索
# 但 Agent 直接编了一段"血压先升后降"——没调工具，纯瞎编
```

**原因：** 这是 Week 06 Day 01 讲过的经典 Agent 失败模式。三个原因：模型太弱（7B 以下不爱调工具）、system_prompt 没明确说"分析趋势必须先调 search_history 检索数据"、工具 docstring 没写清"什么时候用"。

**解决：** 三管齐下——用 7B 以上模型；system_prompt 加"分析趋势前必须先用 search_history 检索历史记录，不能凭空推断"；工具 docstring 写清"当需要查看历史记录时使用此工具，不要直接编造数据"。养老场景绝不能容忍 Agent 瞎编趋势——瞎编的"血压下降"可能让护工放松警惕。

---

## 副线笔记

### 用 Week 05 的 Qdrant（不用 Milvus）

本周 Day 01 的总纲里明确写了"修正向量库：Milvus → Week 05 学过的 Chroma/Qdrant（保持技术栈一致）"。今天的副线笔记把这个决策讲透。

**为什么不用 Milvus：**

| 维度 | Milvus | Qdrant | 养老项目的影响 |
|------|--------|--------|---------------|
| 部署 | Docker 起 etcd + MinIO + Milvus 三件套 | `pip install` 或单容器 | 开发环境太重 |
| 内存占用 | 起来就占 2GB+ | 内存模式几十 MB | 笔记本跑不动 Milvus |
| 过滤能力 | 标量字段索引 + 表达式 | payload 过滤（嵌套/范围/Geo） | Qdrant 的嵌套过滤更适合 vital_values |
| 学习曲线 | 要懂集群/索引/分片 | Filter DSL 半天学会 | 上手快 |

Week 05 我们已经用 Qdrant 跑通了 payload 过滤、量化压缩，技术栈一致，今天直接复用，不用再学一遍 Milvus 的运维。

### Qdrant filter vs Chroma where 的表达力对比

把同一个"查王奶奶最近7天血压记录"的过滤条件，分别用 Qdrant 和 Chroma 写，对比表达力：

```python
# Qdrant：嵌套 + 范围组合，一步到位
filter = models.Filter(must=[
    models.FieldCondition(key="elderly_id", match=models.MatchValue(value="W001")),
    models.FieldCondition(key="date", range=models.Range(gte="2026-07-01", lte="2026-07-07")),
    models.FieldCondition(key="vital_values.systolic", range=models.Range(gte=140)),  # 嵌套字段
])

# Chroma：where 扁平，不支持嵌套，要拆成多个字段
where = {
    "$and": [
        {"elderly_id": "W001"},
        {"date": {"$gte": "2026-07-01", "$lte": "2026-07-07"}},
        # ❌ 没法查 vital_values.systolic >= 140，因为 Chroma 不支持嵌套
        # 要么把 systolic 拎到顶层，要么没法过滤
    ]
}
```

**结论：** Qdrant 的 payload 过滤表达力完胜 Chroma 的 `where`。养老场景的 `vital_values` 天然是嵌套结构（体温/收缩压/舒张压/心率都在一个 dict 里），Qdrant 能直接过滤嵌套字段，Chroma 要把字段拍平到顶层才行。这就是选 Qdrant 的技术理由。

> **今日观察任务：** 把 `trend_agent.py` 跑一遍，记录 Agent 调了哪几个工具、调了几次、最终趋势分析是否准确。重点观察：场景 1 的"先升后降"趋势，Agent 是先调 `search_history` 再调 `detect_anomaly_trend`，还是反过来？为什么这个顺序？

---

## 检查清单

- [ ] 理解为什么选 Qdrant 而不是 Milvus（轻量 + payload 过滤 + 内存模式，养老项目够用）
- [ ] 装好了 `langchain-qdrant` 包，用 `QdrantVectorStore`（不是旧版 `Qdrant`）初始化向量库
- [ ] 理解三种检索模式 DENSE / SPARSE(BM25) / HYBRID 的差异，知道养老场景各用在哪
- [ ] 会用 `qdrant_client.models.Filter / FieldCondition / MatchValue / Range` 做按老人/日期/类型/嵌套字段的过滤检索
- [ ] 设计了护工记录的 metadata 结构，把 CareRecord 拍平成文本 + metadata 入库
- [ ] 跑通了 `trend_agent.py`，三个工具都能调通：search_history / compare_vitals / detect_anomaly_trend
- [ ] 观察到趋势分析示例输出："先升后降""连续超标""突升突降"三种异常模式被检测到
- [ ] 理解从单次记录到趋势洞察的产品价值——养老系统从"记事本"升级成"健康守门人"
- [ ] 知道 metadata 里 None 值和日期格式不补零两个坑怎么避
- [ ] 能说清 Qdrant payload 过滤比 Chroma where 强在哪（嵌套字段 + 范围组合）

---

## 下课预告

> **Day 06 — 多 Agent 编排（Week 07 Subagents 模式）。** 今天趋势分析 Agent 能从历史记录看出趋势了，但它是个"单兵作战"的 Agent——一个 Agent 包揽检索、对比、检测三件事。养老系统其实需要多个专业 Agent 分工：提取 Agent（录音→表单）、趋势 Agent（今天学的）、通知 Agent（异常→家属）。明天用 Week 07 学的 Subagents 模式把这些 Agent 编排起来——一个 Orchestrator Agent 调度多个专业子 Agent，就像前端微服务架构一样。你会学到：CrewAI vs LangGraph Subagents 的选型（面试选型题）、Orchestrator 怎么路由任务给子 Agent、多 Agent 的结果怎么聚合。还会对比 Week 07 手写多 Agent 和今天单 Agent 的差异。
