# Day 03 — 向量数据库 + 检索

## 学习目标

把 Day 01 的 Embedding 和 Day 02 的 Chunk 结合起来，存进向量数据库，实现第一次语义检索。

学完今天你能：
1. 选一个合适的向量存储方案（Chroma / FAISS / Milvus）
2. 用 Chroma 完成 upsert → query → delete 全流程
3. 实现语义检索和关键词检索的混合（Hybrid Search）
4. 理解 RRF 融合算法

---

## 一、选型：Chroma vs FAISS vs Milvus

### 1.1 三种方案速览

| 维度 | Chroma | FAISS | Milvus / Qdrant |
|------|--------|-------|-----------------|
| **定位** | 本地原型 | 高性能内存库 | 生产级分布式 |
| **安装** | `pip install chromadb` | `pip install faiss-cpu` | Docker 部署 |
| **持久化** | ✅ 内置 | ❌ 需手动 json | ✅ 内置 |
| **Metadata 过滤** | ✅ 内置 where | ❌ 需自建 | ✅ 强大 |
| **百万级检索** | 毫秒级 | **微秒级** | 毫秒级（分布式） |
| **分布式** | ❌ | ❌ | ✅ |
| **本周选它** | ✅ **Day 03-06** | Day 05 才对比 | Week 05 专题 |

> **本周选 Chroma** — 安装最简单，持久化零配置，metadata 过滤方便，单机原型开发首选。

### 1.2 安装 Chroma

```bash
pip install chromadb
```

Chroma 不需要 Docker，不需要独立服务。它是一个嵌入式的 Python 库，数据存在本地磁盘。

---

## 二、Chroma 核心操作

### 2.1 初始化 + 创建 Collection

```python
"""vector_store.py — Chroma 向量库封装"""
import chromadb
from chromadb.config import Settings
import uuid


class VectorStore:
    """
    Chroma 向量库封装。

    用法:
        store = VectorStore("./chroma_db")
        await store.add_chunks(doc_id, chunks, embeddings)
        results = await store.query(query_embedding, top_k=5)
        await store.delete_document(doc_id)
    """

    def __init__(self, persist_path: str = "./chroma_db"):
        # PersistentClient: 数据持久化到磁盘
        self.client = chromadb.PersistentClient(
            path=persist_path,
            settings=Settings(anonymized_telemetry=False),
        )
        # 获取或创建 collection
        # collection 相当于关系数据库里的"表"
        self.collection = self.client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"},  # 用余弦相似度
        )

    # ─── 增 ───

    def add_chunks(
        self,
        doc_id: str,
        chunks: list[dict],
        embeddings: list[list[float]],
    ) -> int:
        """
        将一批 chunk 和它们的向量写入 Chroma。

        参数:
            doc_id: 文档唯一标识（如 "doc_001"）
            chunks: [{"text": "...", "metadata": {...}}, ...]
            embeddings: [[0.1, 0.2, ...], [0.3, 0.4, ...], ...]

        返回:
            写入的 chunk 数量
        """
        ids = []
        documents = []
        metadatas = []
        embeds = []

        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            chunk_id = f"{doc_id}_chunk_{i}"
            ids.append(chunk_id)

            # Chroma 的 documents 字段存原文
            documents.append(chunk["text"])

            # metadata 里的值必须是 str / int / float / bool
            meta = {k: str(v) for k, v in chunk.get("metadata", {}).items()}
            meta["doc_id"] = doc_id
            metadatas.append(meta)

            embeds.append(emb)

        if ids:
            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeds,
            )

        return len(ids)

    # ─── 查 ───

    def query(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict | None = None,
        min_similarity: float = 0.0,
    ) -> list[dict]:
        """
        语义检索：用向量检索最相关的 chunk。

        返回:
        [
            {
                "id": "doc_001_chunk_3",
                "text": "匹配到的文本...",
                "metadata": {"source": "xxx.pdf", "page": "3"},
                "distance": 0.12,  # 余弦距离，越小越相似
                "similarity": 0.88,  # 转为相似度
            },
            ...
        ]
        """
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        formatted = []
        # Chroma 返回的是嵌套列表（因为支持批量查询）
        ids = results["ids"][0] if results["ids"] else []
        docs = results["documents"][0] if results["documents"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []
        dists = results["distances"][0] if results["distances"] else []

        for id_, doc, meta, dist in zip(ids, docs, metas, dists):
            sim = 1 - dist  # 余弦距离 → 余弦相似度
            if sim < min_similarity:
                continue
            formatted.append({
                "id": id_,
                "text": doc,
                "metadata": meta,
                "distance": dist,
                "similarity": round(sim, 4),
            })

        return formatted

    # ─── 删 ───

    def delete_document(self, doc_id: str) -> int:
        """
        删除一个文档的所有 chunk。

        参数:
            doc_id: 文档 ID（如 "doc_001"）

        返回:
            删除的 chunk 数量
        """
        # 先找到所有属于这个文档的 chunk id
        results = self.collection.get(
            where={"doc_id": doc_id},
            include=[],
        )
        chunk_ids = results["ids"]

        if chunk_ids:
            self.collection.delete(ids=chunk_ids)

        return len(chunk_ids)

    # ─── 统计 ───

    def count(self) -> int:
        """返回向量库中的 chunk 总数"""
        return self.collection.count()

    def list_documents(self) -> list[str]:
        """列出所有文档 ID"""
        # 用 get 获取所有不同的 doc_id
        results = self.collection.get(include=["metadatas"])
        doc_ids = set()
        for meta in (results.get("metadatas") or []):
            if meta and "doc_id" in meta:
                doc_ids.add(meta["doc_id"])
        return sorted(doc_ids)
```

### 2.2 核心操作速查

```python
# 初始化
store = VectorStore("./chroma_db")

# 写入
store.add_chunks("doc_001", chunks, embeddings)

# 语义检索
results = store.query(query_embedding, top_k=5)

# 按文档过滤检索
results = store.query(
    query_embedding,
    top_k=5,
    where={"doc_id": "doc_001"},  # 只查这个文档
)

# 相似度阈值过滤
results = store.query(
    query_embedding,
    top_k=10,
    min_similarity=0.5,  # 低于 0.5 的结果丢弃
)

# 删文档
store.delete_document("doc_001")

# 统计
print(f"总 chunk 数: {store.count()}")
print(f"文档列表: {store.list_documents()}")
```

---

## 三、检索方式详解

### 3.1 语义检索（Semantic Search）

流程：`用户问题 → Embedding 向量 → Chroma 余弦距离查询 → top_k 结果`

Chroma 内部使用 HNSW 索引（分层可导航小世界图），是一种近似最近邻（ANN）算法。不是精确搜索（那太慢了），但精度足够（>95%）。

### 3.2 关键词检索（BM25）

语义检索擅长"意思相近"，但有时用户就是找特定关键词：

```
用户: "Python 3.12 的 PEP 701 是什么？"
语义检索: 可能返回 Python 3.11、PEP 684 等相关但不精确的结果
关键词检索: 精准匹配 "PEP 701" 这个字符串
```

BM25 是一种经典的关键词检索算法，基于 TF-IDF 改进：

```python
"""hybrid_search.py — 关键词检索 + RRF 混合"""
import re
import math
from collections import Counter


class KeywordRetriever:
    """简易 BM25 关键词检索器"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1  # 词频饱和参数
        self.b = b    # 长度归一化参数
        self.documents: list[str] = []
        self.avgdl: float = 0  # 平均文档长度
        self.df: Counter = Counter()  # 文档频率
        self.idf: dict[str, float] = {}

    def fit(self, documents: list[str]):
        """建立索引：计算 IDF"""
        self.documents = documents
        self.avgdl = sum(len(d) for d in documents) / len(documents)

        # 分词（简单空格/标点分词）
        for doc in documents:
            terms = set(self._tokenize(doc))
            for term in terms:
                self.df[term] += 1

        # IDF = log((N - df + 0.5) / (df + 0.5))
        N = len(documents)
        self.idf = {
            term: math.log((N - freq + 0.5) / (freq + 0.5) + 1)
            for term, freq in self.df.items()
        }

    def _tokenize(self, text: str) -> list[str]:
        """简易中英文分词"""
        # 对于中文：按字/词切分
        # 对于英文：按空格和标点切分
        return re.findall(r"[一-鿿]+|[a-zA-Z0-9]+", text.lower())

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        """BM25 检索，返回 [(doc_index, score), ...]"""
        terms = self._tokenize(query)
        scores = []

        for idx, doc in enumerate(self.documents):
            score = 0.0
            doc_len = len(doc)
            doc_terms = self._tokenize(doc)
            tf = Counter(doc_terms)

            for term in terms:
                if term not in self.idf:
                    continue
                term_freq = tf.get(term, 0)
                if term_freq == 0:
                    continue

                # BM25 公式
                idf = self.idf[term]
                numerator = term_freq * (self.k1 + 1)
                denominator = term_freq + self.k1 * (
                    1 - self.b + self.b * doc_len / self.avgdl
                )
                score += idf * numerator / denominator

            if score > 0:
                scores.append((idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
```

### 3.3 混合检索：RRF 融合

**为什么需要混合？** 语义检索和关键词检索各有盲区，融合后互补。

```python
def reciprocal_rank_fusion(
    semantic_results: list[dict],
    keyword_results: list[dict],
    k: int = 60,
) -> list[dict]:
    """
    RRF (Reciprocal Rank Fusion) 融合算法。

    公式: RRF_score(d) = Σ 1 / (k + rank_i(d))

    对每个文档 d，把它在多个排序列表中的排名取倒数求和。
    k=60 是经验值，平滑排名差异。

    返回: 按融合分数降序排列的结果列表
    """
    scores: dict[str, dict] = {}

    # 语义检索结果
    for rank, item in enumerate(semantic_results, start=1):
        doc_id = item["id"]
        scores.setdefault(doc_id, {"item": item, "score": 0})
        scores[doc_id]["score"] += 1 / (k + rank)

    # 关键词检索结果
    for rank, (chunk_idx, _) in enumerate(keyword_results, start=1):
        doc_id = f"chunk_{chunk_idx}"
        if doc_id not in scores:
            scores[doc_id] = {
                "item": {"id": doc_id, "text": "", "metadata": {}},
                "score": 0,
            }
        scores[doc_id]["score"] += 1 / (k + rank)

    # 按融合分数排序
    sorted_ids = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)
    return [info["item"] for _, info in sorted_ids]
```

**RRF 的核心思想：** 两个列表排第一的都被排第一更重要。不关心绝对分数，只关心相对排名。

---

## 四、完整检索流程图

```
用户问题: "RAG 的 chunk_size 应该设多大？"
                │
                ▼
        ┌──────────────┐
        │ Query Embedding│  ← 调 Embedding API
        └──────┬───────┘
               │
               ├──────────────────┐
               ▼                  ▼
        ┌──────────┐      ┌──────────────┐
        │语义检索    │      │关键词检索(BM25)│
        │Chroma.query│      │KeywordRetriever│
        └─────┬────┘      └──────┬───────┘
              │                  │
              ▼                  ▼
        top_k=10 results    top_k=10 results
              │                  │
              └────────┬─────────┘
                       ▼
               ┌──────────────┐
               │   RRF 融合    │  ← 1/(k+rank) 加权
               └──────┬───────┘
                       │
                       ▼
                融合后 top_k=5
                       │
                       ▼
                 发给 Generator
```

---

## 五、动手实验

### 🟢 青铜级：跑通 Chroma 增删查

```bash
# 安装 Chroma
pip install chromadb

# 测试
python -c "
from vector_store import VectorStore
import random

store = VectorStore('./test_db')

# 模拟 10 条数据
chunks = [{'text': f'这是第{i}条测试文本'} for i in range(10)]
# 模拟 768 维向量
embeddings = [[random.random() for _ in range(768)] for _ in range(10)]
store.add_chunks('test', chunks, embeddings)
print(f'入库: {store.count()} 条')

# 随机查询
query_vec = [random.random() for _ in range(768)]
results = store.query(query_vec, top_k=3)
for r in results:
    print(f'  [{r[\"similarity\"]:.3f}] {r[\"text\"]}')

# 删除
store.delete_document('test')
print(f'删除后: {store.count()} 条')
"
```

### 🟡 白银级：对比语义检索 vs 关键词检索

用相同的 query 跑两种检索方式，对比结果差异。哪些 query 语义检索更好？哪些关键词更好？

### 🔴 王者级：实现 RRF 混合检索

把语义检索 top_10 + 关键词检索 top_10 用 RRF 融合，看融合后的 top_5 和单用任一种有何不同。

---

## 六、踩坑记录 🕳️

### 坑 1：Chroma 的 metadata 值类型限制

```python
# ❌ Chroma metadata 不接受 list / dict / None
{"page": [1, 2]}           # 报错
{"tags": {"a": 1}}          # 报错
{"author": None}            # 报错

# ✅ 必须是 str / int / float / bool
{"page": 1}                 # ✅
{"page": "1"}              # ✅
{"author": "unknown"}      # ✅
```

### 坑 2：余弦距离 vs 余弦相似度

```
Chroma 的 distance 含义取决于初始化时的 hnsw:space:

"cosine"  → distance = 1 - cosine_similarity
             distance=0 最相似
             distance=2 最不相似

"l2"      → distance = 欧氏距离
             distance=0 最相似
             distance 越大越不相似
```

**确认你的 `hnsw:space` 设置，避免把 distance 当 similarity。**

### 坑 3：Chroma 不支持 update

```python
# ❌ Chroma 没有 update 方法
collection.update(ids=["id_1"], embeddings=[...])  # AttributeError

# ✅ 先删后增
collection.delete(ids=["id_1"])
collection.add(ids=["id_1"], embeddings=[...], ...)
```

### 坑 4：PersistentClient 路径注意 Windows

```python
# Windows 上路径分隔符用 / 或 \\
store = VectorStore("./chroma_db")    # ✅
store = VectorStore("C:/data/chroma") # ✅
store = VectorStore("C:\\data\\chroma")  # ✅ 但推荐用 /
```

### 坑 5：存入 0 条数据

```python
# 某些 PDF 可能提取不到文本（扫描版、纯图片）
# add_chunks 返回 0 → 后续 query 自然也没有结果
count = store.add_chunks(doc_id, chunks, embeddings)
if count == 0:
    print(f"警告: 文档 {doc_id} 没有可索引的文本")
```

---

## 七、副线笔记

### Claude Code 用什么检索？

对比你的向量检索和 Claude Code 在项目里找代码的方式：

| 维度 | 你的 VectorStore | Claude Code |
|------|-----------------|-------------|
| 检索对象 | 文档 chunks | 代码文件 |
| 索引方式 | Embedding 向量 | grep + 语义理解 |
| 排序 | 余弦相似度 | 匹配精确度 + 路径相关性 |
| 过滤 | metadata where | 文件类型 glob 过滤 |

Claude Code 实际上用的是**混合检索**（grep精确匹配 + AI 语义判断），这和你的 RRF 混合检索思路完全一致。

---

## 今日产出检查清单

- [ ] Chroma 安装成功，PersistentClient 正常初始化
- [ ] 跑通了 add_chunks → query → delete_document 全流程
- [ ] 能用 metadata where 按文档过滤检索
- [ ] 理解语义检索和关键词检索的互补关系
- [ ] (可选) 实现了 RRF 混合检索

---

> **下一课预告：Day 04 — RAG 完整流水线**。把 Load → Split → Embed → Store → Retrieve → Generate 串成一条完整的流水线。
