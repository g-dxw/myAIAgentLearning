# Day 05 — Qdrant + Pinecone 对比 + 选型决策

## 学习目标

Week 05 走到第五天，Chroma 和 Milvus 都已经上手了。今天把视野再打开一档：引入 Qdrant（Rust 写的高性能本地+云双模库）和 Pinecone（全托管 Serverless 云服务），把四库放在同一张桌子上横向对比，最后用一棵决策树把"什么场景该选谁"钉死。学完今天你不再纠结"哪个向量库最好"——因为答案永远是"看场景"——而是能用三个问题（规模？运维？过滤？）在五分钟内给出选型结论。

学完今天你能：
1. 用 `qdrant-client` 完成 `create_collection` → `upsert` → `payload filter` 检索全流程，说清楚 Qdrant 的 payload 过滤为什么比 Chroma 的 `where` 更强
2. 用 `pinecone-client` 连上 Serverless 索引，用 namespace 分区 + 混合检索（dense+sparse）跑通托管云方案，并讲清楚"托管 vs 自建"的取舍
3. 默写四库横向对比表（Chroma / Milvus / Qdrant / Pinecone），按 11 个维度给每家打分，并能复述一棵覆盖 6 类场景的选型决策树
4. 用自封装的 `VectorStore` 抽象层把向量库的写入/查询/过滤 API 统一成一套接口，理解 vendor lock-in 风险和迁移成本的结构（向量可导出，索引/过滤语法不可移植）

---

## 一、Qdrant 特性：Rust 写的性能怪兽

### 1.1 Qdrant 速览

Qdrant 用 Rust 写成，单机性能在四库里名列前茅，同时原生支持分布式。它最讨喜的不是速度本身，而是 **payload 过滤** + **内置量化** 两个特性，把 Day 03 在 Chroma 上要靠 `where` 凑出来的过滤、Day 06 要靠压缩凑出来的省内存，都做成了开箱即用的官方功能。

| 特性 | 说明 |
|------|------|
| 语言 | Rust（核心）+ Python/JS/Rust 客户端 |
| 部署 | 本地嵌入式 / Docker 一行 / Qdrant Cloud |
| 过滤 | payload 过滤，支持嵌套对象、范围、地理坐标（Geo） |
| 量化 | 内置 Scalar 量化（int8）+ Binary 量化，内存可省 4-32x |
| 混合检索 | 支持 dense + sparse（BM25 内置）融合查询 |
| 索引 | HNSW + 量化联合索引，支持 `on_disk` 模式 |

### 1.2 Docker 一行启动

```bash
# 拉镜像即起，默认 6333 是 HTTP，6334 是 gRPC
docker run -p 6333:6333 -p 6334:6334 \
    -v $(pwd)/qdrant_storage:/qdrant/storage \
    qdrant/qdrant
```

起来后浏览器开 `http://localhost:6333/dashboard` 就有现成的 Web UI，这点对调试比 Milvus 的 Attu 还省事。

### 1.3 基础操作代码

```python
"""qdrant_basic.py — Qdrant 基础操作：建集合 → 写点 → payload 过滤检索"""
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    Range,
    GeoBoundingBox,
)


def demo_qdrant():
    """
    Qdrant 基础流程演示。

    流程: 连接 → 建集合(指定维度+距离) → upsert 点(含 payload) → 过滤检索
    """
    # 1. 连接：本地模式（无需 Docker，数据落 ./qdrant_data）
    # 生产环境改成 host="localhost", port=6333 连 Docker/Cloud
    client = QdrantClient(path="./qdrant_data")

    collection_name = "routes"

    # 2. 创建集合：必须指定向量维度和距离度量
    # on_disk=True 可让索引落盘，省内存（适合亿级）
    client.recreate_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )

    # 3. upsert 点：每个 point 有 id、向量、payload（等价于 metadata 但更强）
    # payload 可以存嵌套 dict、list、坐标——这是 Chroma metadata 做不到的
    client.upsert(
        collection_name=collection_name,
        points=[
            PointStruct(
                id=1,
                vector=[0.1] * 384,  # 实际应为 embedding 结果
                payload={
                    "region": "川西",
                    "elevation_m": 4500,
                    "seasons": ["春", "秋"],  # ✅ list 直接存
                    "geo": {"lat": 30.0, "lon": 102.0},  # ✅ 嵌套对象
                    "tags": ["雪山", "高海拔"],
                },
            ),
            PointStruct(
                id=2,
                vector=[0.2] * 384,
                payload={
                    "region": "川西",
                    "elevation_m": 3200,
                    "seasons": ["夏"],
                    "geo": {"lat": 31.0, "lon": 103.0},
                    "tags": ["草原"],
                },
            ),
        ],
    )

    # 4. payload 过滤检索：等值 + 范围 + 地理 三条件组合
    # 这在 Chroma 里要拼 $and，在 Qdrant 里就是一个 Filter 列表
    results = client.search(
        collection_name=collection_name,
        query_vector=[0.15] * 384,
        query_filter=Filter(
            must=[
                # 等值：region == "川西"
                FieldCondition(key="region", match=MatchValue(value="川西")),
                # 范围：海拔 >= 4000
                FieldCondition(key="elevation_m", range=Range(gte=4000)),
            ]
        ),
        limit=5,
    )

    for hit in results:
        print(f"  score={hit.score:.3f}  payload={hit.payload}")
```

> **关键认知：** Qdrant 的 payload 可以存 `list` / 嵌套 `dict` / 地理坐标，过滤时用 `must` / `should` / `must_not` 组合，表达力远超 Chroma 的扁平 `where`。代价是学习曲线略陡，Filter DSL 要记一套语法。

---

## 二、Pinecone 特性：全托管 Serverless 云

### 2.1 Pinecone 速览

Pinecone 是四库里唯一的**纯托管云服务**——你永远不用 `docker run`，不用管磁盘、不用调 HNSW 参数、不用做量化调优。建索引、灌向量、查向量全走 API，背后所有运维 Pinecone 替你扛。它走的是 Serverless 路线：按存储 + 查询用量计费，零流量时几乎不花钱。

| 特性 | 说明 |
|------|------|
| 部署 | 仅云托管（AWS/GCP/Azure 区域），无自建 |
| 架构 | Serverless，按用量计费（存储 CU + 查询 RU） |
| 分区 | namespace（同一索引内逻辑分区） |
| 混合检索 | 内置 dense + sparse 向量，一条 query 出融合结果 |
| 过滤 | metadata filter（等值/范围/集合，比 Chroma 强但弱于 Qdrant 的 Geo） |
| 运维 | 零运维，但代价是数据在别人机房 |

### 2.2 托管 vs 自建的取舍

| 维度 | 自建（Chroma/Milvus/Qdrant） | 托管（Pinecone/Qdrant Cloud） |
|------|------------------------------|-------------------------------|
| 运维成本 | 要管磁盘、备份、扩容、监控 | 零运维 |
| 数据主权 | 数据在自己机房 | 数据在厂商机房（合规风险） |
| 弹性 | 手动扩容，提前备机 | 自动弹性，流量高峰自动扛 |
| 成本结构 | 固定机器成本，量大摊薄 | 按量付费，量大可能比自建贵 |
| 上手速度 | 要部署要调参 | 注册即用，5 分钟出第一个 query |
| vendor lock-in | 低（数据/索引本地可控） | 高（API 私有，迁移要重写代码） |

> **经验法则：** 原型和中小规模（< 千万向量）优先自建省成本、保数据主权；流量波动剧烈或团队没有 SRE 时优先托管省人力。两者不是二选一——很多团队是"生产托管 + 开发自建"双轨。

### 2.3 Pinecone 基础操作代码

```python
"""pinecone_basic.py — Pinecone Serverless 基础操作"""
from pinecone import Pinecone, ServerlessSpec


def demo_pinecone(api_key: str):
    """
    Pinecone Serverless 流程演示。

    流程: 初始化 → 建 Serverless 索引 → namespace 灌数据 → 混合检索
    """
    # 1. 初始化客户端（api_key 从 Pinecone 控制台拿）
    pc = Pinecone(api_key=api_key)

    index_name = "routes"

    # 2. 创建 Serverless 索引：指定云厂商 + 区域
    # Serverless 不用选 pod 类型、不用预估容量，按用量自动伸缩
    if index_name not in [i.name for i in pc.list_indexes()]:
        pc.create_index(
            name=index_name,
            dimension=384,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )

    # 3. 连接索引（host 在创建后由 Pinecone 分配）
    index = pc.Index(index_name)

    # 4. namespace 分区：相当于同一索引内的"逻辑子库"
    # 比如把川西/新疆/西藏分到不同 namespace，互不干扰
    ns = "sichuan"

    index.upsert(
        vectors=[
            {
                "id": "route_001",
                "values": [0.1] * 384,
                "metadata": {"region": "川西", "elevation_m": 4500},
            },
            {
                "id": "route_002",
                "values": [0.2] * 384,
                "metadata": {"region": "川西", "elevation_m": 3200},
            },
        ],
        namespace=ns,
    )

    # 5. 带 metadata 过滤的查询
    results = index.query(
        vector=[0.15] * 384,
        top_k=5,
        namespace=ns,
        filter={"elevation_m": {"$gte": 4000}},  # 元数据过滤
        include_metadata=True,
    )

    for match in results["matches"]:
        print(f"  score={match['score']:.3f}  meta={match['metadata']}")
```

> **关键认知：** Pinecone 的 namespace 不是物理分区，是逻辑分区——好处是切换 namespace 零成本，坏处是它不解决单 namespace 的规模上限。真正扛规模的是 Serverless 底层的自动分片。

---

## 三、四库横向对比表（重点）

把 Chroma（Day 03）、Milvus（Day 04）、Qdrant、Pinecone 放在一张表里，11 个维度逐一对照。这张表是本周的"选型总表"，建议背下来或贴在墙上。

| 维度 | Chroma | Milvus | Qdrant | Pinecone |
|------|--------|--------|--------|----------|
| **定位** | 本地原型 | 生产级分布式 | 高性能本地+云 | 全托管 Serverless |
| **部署方式** | `pip install` 嵌入式 | Docker/K8s 集群 | Docker/本地/Cloud | 仅云（无自建） |
| **实现语言** | Python + Rust 核心 | Go + C++ | Rust | 闭源云服务 |
| **分布式** | ❌ 单机 | ✅ 原生分布式 | ✅ 分片集群 | ✅ 厂商托管 |
| **过滤能力** | `where`（扁平，类型受限） | 标量字段索引+表达式 | **payload 过滤（嵌套/范围/Geo）** | metadata filter（中等） |
| **量化压缩** | ❌ 无 | ✅ SQ/PQ/二值 | ✅ Scalar/Binary 内置 | ✅ 厂商自动 |
| **混合检索** | 需自拼 RRF | ✅ 内置 dense+sparse | ✅ 内置 dense+sparse | ✅ 内置 dense+sparse |
| **计费** | 免费 | 免费 | 免费 / Cloud 付费 | 按用量付费（CU+RU） |
| **适用规模** | < 100 万 | 千万~亿级 | 百万~亿级 | 任意（弹性） |
| **学习曲线** | 最低（半天上手） | 高（要懂集群/索引） | 中（Filter DSL 要学） | 低（API 简单） |
| **本周何时用** | Day 03 原型 | Day 04 生产 | Day 05 强过滤/省内存 | Day 05 全托管对照 |

**一句话总结每家：**
- **Chroma** — 装上就能跑，原型之王，但千万级就吃力。
- **Milvus** — 生产级分布式老大哥，能扛亿级，但运维重。
- **Qdrant** — Rust 性能 + payload 过滤 + 内置量化，性价比之王。
- **Pinecone** — 零运维，把麻烦全外包给厂商，适合没 SRE 的团队。

---

## 四、选型决策树（重点）

光有对比表还不够，真正做决策时要按场景走路径。下面这棵树覆盖 6 类典型场景，从根节点开始问问题，落到叶子就是答案。

```
                   ┌─ 你要的是什么规模/诉求？─┐
                   │                          │
        ┌──────────┴──────────┐               │
        ▼                     ▼               ▼
   原型开发               百万~千万级        亿级生产
   (Week04-05 日常)       (单机扛得住)       (要分布式)
        │                     │               │
        ▼                     ▼               ▼
   【Chroma】          ┌── 要强过滤/省内存? ──┐  ┌── 有 SRE 团队? ──┐
   装即用,零运维       │                     │  │                  │
                      是──────────否         │  是──────否         │
                      ▼                      ▼  ▼                   ▼
                 【Qdrant】            【Chroma/            【Milvus】      【Pinecone】
                 payload+量化          Milvus单机】         扛亿级,运维重   全托管,省人力

        ┌──────────────────────────────────────────┐
        │  两个特殊分支:                            │
        │  ① 要全托管(无运维) ──→ Pinecone          │
        │  ② 要强过滤(嵌套/Geo) ──→ Qdrant          │
        │  ③ 成本敏感(量大)   ──→ Milvus 自建       │
        │  ④ 成本敏感(量小)   ──→ Chroma/Qdrant 本地│
        └──────────────────────────────────────────┘
```

**决策路径速查：**

| 场景 | 决策路径 | 落点 |
|------|----------|------|
| 原型开发 | 规模<10万 + 零运维 | **Chroma** |
| 百万级单机 | 单机扛得住 + 要强过滤 | **Qdrant** |
| 亿级生产（有 SRE） | 要分布式 + 有运维 | **Milvus** |
| 亿级生产（无 SRE） | 要分布式 + 要全托管 | **Pinecone** |
| 要全托管 | 任何规模 + 零运维 | **Pinecone**（或 Qdrant Cloud） |
| 要强过滤 | 嵌套/Geo/范围 | **Qdrant** |
| 成本敏感（量大） | 千万级以上 + 预算紧 | **Milvus** 自建 |
| 成本敏感（量小） | 百万以下 + 预算紧 | **Chroma / Qdrant 本地** |

> **核心心法：** 决策树不是"哪个最好"，而是"先排除不适用的，再在剩下的里挑最省事的"。先问规模（排掉扛不住的），再问运维（排掉没人管的），最后问特性（在剩下的里挑过滤/量化的强项）。

---

## 五、迁移成本与锁定

### 5.1 迁移的真实成本结构

很多人以为"向量库迁移就是导出向量再导入"，这是低估了。真正的成本分三层：

| 层 | 可迁移性 | 迁移成本 |
|----|----------|----------|
| 向量数据本身 | ✅ 完全可导出（就是 float 数组） | 低 |
| payload/metadata | ✅ 可导出，但字段类型要对齐 | 中 |
| 索引结构 | ❌ 不可移植（HNSW/IVF 图是厂商私有） | 高（必须重建索引） |
| 过滤语法 | ❌ 不可移植（每家 DSL 不同） | 高（必须重写查询代码） |
| 混合检索/量化配置 | ❌ 不可移植 | 高（语义可能有差异） |

**也就是说：** 向量本身是流动的，但"怎么索引、怎么过滤、怎么融合"是绑死的。这就是 vendor lock-in 的本质——锁的不是数据，是访问数据的代码。

### 5.2 用抽象层降低迁移成本

解法是在业务代码和具体向量库之间插一层**抽象接口**。业务只依赖接口，不依赖具体 SDK。换库时只需新增一个 Adapter，业务代码零改动。这就是今天产出文件 `vector_db_compare.py` 的核心设计。

```python
"""vector_db_compare.py — 统一 VectorStore 抽象层 + 四库 Adapter 示例"""
from abc import ABC, abstractmethod
from typing import Any


class VectorStore(ABC):
    """
    向量库统一抽象接口。

    业务代码只依赖这个接口，不依赖任何具体向量库 SDK。
    换库时只需新增一个 Adapter 实现这个接口，业务零改动。
    """

    @abstractmethod
    def ensure_collection(self, name: str, dim: int, metric: str = "cosine") -> None:
        """创建或获取集合（collection/index），指定向量维度和距离度量。"""

    @abstractmethod
    def upsert(self, collection: str, points: list[dict]) -> int:
        """
        批量写入/更新向量点。

        参数:
            collection: 集合名
            points: [{"id": str, "vector": list[float], "metadata": dict}, ...]

        返回: 写入点数
        """

    @abstractmethod
    def query(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[dict]:
        """
        语义检索 + 元数据过滤，返回统一格式结果。

        返回: [{"id": str, "score": float, "metadata": dict}, ...]
        """


class ChromaAdapter(VectorStore):
    """Chroma 适配器：把 Chroma 的 API 翻译成统一接口。"""

    def __init__(self, path: str = "./chroma_db"):
        import chromadb
        # 延迟导入：业务不装 chromadb 也能跑其他 Adapter
        self.client = chromadb.PersistentClient(path=path)
        self._cols = {}

    def ensure_collection(self, name: str, dim: int, metric: str = "cosine") -> None:
        # Chroma 用 hnsw:space 指定距离
        self._cols[name] = self.client.get_or_create_collection(
            name=name, metadata={"hnsw:space": metric}
        )

    def upsert(self, collection: str, points: list[dict]) -> int:
        col = self._cols[collection]
        # Chroma 的 metadata 不接受 list/None，这里做类型清洗
        clean_meta = []
        for p in points:
            meta = {k: v for k, v in p["metadata"].items() if v is not None}
            clean_meta.append(meta)
        col.upsert(
            ids=[p["id"] for p in points],
            embeddings=[p["vector"] for p in points],
            metadatas=clean_meta,
        )
        return len(points)

    def query(self, collection, query_vector, top_k=5, filters=None):
        col = self._cols[collection]
        res = col.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=filters,  # Chroma 的 where 语法
            include=["metadatas", "distances"],
        )
        # 统一返回格式
        out = []
        for i, id_ in enumerate(res["ids"][0]):
            out.append({
                "id": id_,
                "score": 1 - res["distances"][0][i],  # cosine: sim = 1 - dist
                "metadata": res["metadatas"][0][i],
            })
        return out


class QdrantAdapter(VectorStore):
    """Qdrant 适配器：payload 过滤语法在 Adapter 内部翻译。"""

    def __init__(self, path: str = "./qdrant_data"):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        self._Distance = Distance
        self._VectorParams = VectorParams
        self.client = QdrantClient(path=path)

    def ensure_collection(self, name: str, dim: int, metric: str = "cosine") -> None:
        # metric 字符串映射到 Qdrant 的 Distance 枚举
        dist_map = {"cosine": self._Distance.COSINE, "l2": self._Distance.EUCLID}
        self.client.recreate_collection(
            collection_name=name,
            vectors_config=self._VectorParams(size=dim, distance=dist_map[metric]),
        )

    def upsert(self, collection: str, points: list[dict]) -> int:
        from qdrant_client.models import PointStruct
        # Qdrant 的 id 必须是 int 或 UUID 字符串，这里统一转 str
        pts = [
            PointStruct(id=str(p["id"]), vector=p["vector"], payload=p["metadata"])
            for p in points
        ]
        self.client.upsert(collection_name=collection, points=pts)
        return len(points)

    def query(self, collection, query_vector, top_k=5, filters=None):
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        # 把统一的 filters dict 翻译成 Qdrant 的 Filter DSL
        qdrant_filter = None
        if filters:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filters.items()
            ]
            qdrant_filter = Filter(must=conditions)
        res = self.client.search(
            collection_name=collection,
            query_vector=query_vector,
            query_filter=qdrant_filter,
            limit=top_k,
        )
        return [
            {"id": str(h.id), "score": h.score, "metadata": h.payload}
            for h in res
        ]


# ─── 业务代码：只依赖 VectorStore 接口，不知道底层是谁 ───
def recommend_routes(store: VectorStore, q_vec: list[float], region: str):
    """
    业务函数：推荐路线。换库时这个函数一行都不用改。

    参数:
        store: 任意 VectorStore 实现（Chroma/Qdrant/Pinecone...）
        q_vec: 查询向量
        region: 区域过滤
    """
    store.ensure_collection("routes", dim=len(q_vec), metric="cosine")
    results = store.query("routes", q_vec, top_k=5, filters={"region": region})
    return [{"id": r["id"], "score": r["score"]} for r in results]


# 切换底层库只需改一行：
# store = ChromaAdapter("./chroma_db")      # 原型阶段
# store = QdrantAdapter("./qdrant_data")     # 上线后换 Qdrant
# recommend_routes(store, q_vec, "川西")     # 业务代码不变
```

> **关键认知：** 抽象层的代价是多一层间接、性能微损；收益是换库时业务零改动。对原型不值得，对生产强需求。是否上抽象层的判断标准：**这个项目会不会换库？** 不确定就上，确定不会就别加。

---

## 六、动手实验

### 🟢 青铜级：Qdrant 本地跑通三步

```bash
pip install qdrant-client
# 不用 Docker，直接 path 模式跑 demo_qdrant()
python -c "from qdrant_basic import demo_qdrant; demo_qdrant()"
# 预期：打印出 1 条川西海拔≥4000 的结果
```

验证：把 `Range(gte=4000)` 改成 `gte=3000`，结果应该变成 2 条。

### 🟡 白银级：跑通 `vector_db_compare.py` 双 Adapter

用同一批 points 分别灌进 `ChromaAdapter` 和 `QdrantAdapter`，用同一个 query_vector 检索，对比两者的 top_5 排序差异。思考：为什么同样的向量、同样的 cosine，两个库的 score 可能略有不同？（提示：浮点精度 + HNSW 近似性）

### 🔴 王者级：补全 PineconeAdapter 并做三库一致性测试

在 `vector_db_compare.py` 里实现 `PineconeAdapter`（注意 Pinecone 的 namespace 映射、filter 语法 `$gte` 与 Chroma/Qdrant 的差异），然后写一个测试：同一批 100 条数据灌进三个 Adapter，用 10 个 query 跑检索，对比三库 top_1 的一致率。一致率能到多少？为什么不到 100%？

---

## 七、踩坑记录 🕳️

### 坑 1：Qdrant 的 id 类型与 Chroma 不同

```python
# Qdrant 的 id 可以是 int 或 UUID 字符串，但不接受任意字符串
client.upsert(points=[PointStruct(id="route_001", ...)])  # ❌ 可能报错
client.upsert(points=[PointStruct(id=1, ...)])            # ✅ int
client.upsert(points=[PointStruct(id="550e8400-...", ...)])  # ✅ UUID

# ✅ 统一解法：在 Adapter 里把业务 id 转成 int 序列或 UUID
# 或者用 Qdrant 的 named point（uuid 模式）
```

### 坑 2：Pinecone 的 namespace 不是 collection

```python
# ❌ 误以为 namespace 是物理隔离，往一个 namespace 灌数据另一个看不到
# 实际上 namespace 是同一索引内的逻辑分区，索引的 dimension/metric 是全局共享的
# 不同 namespace 不能用不同维度

# ✅ 要不同维度就得建不同索引（index），不是不同 namespace
pc.create_index(name="routes_384", dimension=384, ...)
pc.create_index(name="images_512", dimension=512, ...)
```

### 坑 3：Pinecone Serverless 的冷启动延迟

```python
# Serverless 索引在长时间无流量后会"休眠"
# 第一个 query 可能要 1-3 秒才返回（唤醒延迟）
# 对延迟敏感的在线场景，要么用定时心跳保活，要么改用 pod 模式

# ✅ 监控首查询询延迟，超过 500ms 就加保活任务
```

### 坑 4：Qdrant 量化的精度损失没测就上线

```python
# Scalar 量化把 float32 压成 int8，省 4x 内存，但召回率会掉 1-3%
# 生产前必须做 A/B：量化前后的召回率 / latency / 内存 三项对比
# 召回率掉太多就关量化，或换 Binary 量化（更激进但适合长文本）

# ✅ 量化配置后跑回归测试集，召回率不能低于原来的 97%
```

### 坑 5：抽象层过度设计，原型阶段就上

```python
# 原型阶段业务还在变，过早写 Adapter 层 = 给还没定型的需求做泛化
# 结果是改一次需求就要改接口 + 改所有 Adapter，反而更慢

# ✅ 判断标准：库选型已经确定不会换 → 不上抽象层
#           库还在评估/可能换 → 上抽象层，但只抽象你真用的 3-4 个方法
```

---

## 八、副线笔记：对比 Claude Code 的检索策略

### 8.1 Claude Code 不用向量库

把四库的过滤能力摆出来后，回头看 Claude Code 在项目里找代码的方式——它会让你惊讶：**Claude Code 压根不用向量库**。它用的是 `grep` + 文件 glob + AI 语义判断的混合方案：

| 维度 | 四库方案 | Claude Code |
|------|----------|-------------|
| 索引方式 | Embedding 向量 + HNSW | 无索引，实时 grep + 文件遍历 |
| 召回 | 余弦相似度 top_k | 精确符号匹配 + AI 判断相关性 |
| 过滤 | metadata where / payload filter | 文件类型 glob + 路径模式 |
| 排序 | 距离分数 | 匹配精确度 + 路径相关性 + AI 重排 |
| 适合对象 | 自然语言文档、语义模糊查询 | 代码符号、精确标识符 |

### 8.2 为什么代码检索不该用向量库？

四库的 payload 过滤再强，本质都是"语义近似召回"。但**代码检索的特殊性在于：精确符号匹配比语义更重要**。

```
查询: "VectorStore 这个类在哪里定义？"

向量库方案: 找语义相近的 chunk → 可能返回所有提到 VectorStore 的注释/文档
Claude Code: grep "class VectorStore" → 精确命中定义那一行
```

代码里的符号（类名、函数名、变量名）是**强标识符**，grep 的精确匹配召回率 100%、延迟亚毫秒、零运维。语义检索在这种场景下反而是杀鸡用牛刀——还要先 embed、还要建索引、还要容忍近似。

### 8.3 没有最好的检索，只有最合适的

把四库的过滤能力排个序：**Qdrant（payload+Geo）> Milvus ≈ Pinecone > Chroma**。但这不意味着 Qdrant 最强就该处处用它。Claude Code 的选择揭示了一个更深的道理：

- **文档/对话/产品描述** → 语义模糊、自然语言 → 向量库（Qdrant/Chroma）
- **代码符号/API/标识符** → 精确匹配、强结构 → grep + AST
- **混合场景** → Claude Code 的方案：grep 精确召回 + AI 语义重排（等价于 RRF 混合）

四库横向对比表的真正价值不是"选出赢家"，而是让你看清每种方案的适用边界。选型决策树给出的不是"最优解"，而是"约束下的最合适解"。**没有最好的检索，只有最合适的检索**——这是本周五天下来最该带走的一句话。

---

## 今日产出检查清单

- [ ] 用 `qdrant-client` 跑通 `create_collection` → `upsert` → `payload filter` 检索，理解 payload 为何强于 Chroma 的 `where`
- [ ] 能默写四库横向对比表的 11 个维度，说清每家的定位与适用规模
- [ ] 能复述选型决策树，对"原型/百万单机/亿级生产/全托管/强过滤/成本敏感"6 类场景给出落点
- [ ] 理解迁移成本的三层结构：向量可导出、索引不可移植、过滤语法不可移植
- [ ] `vector_db_compare.py` 跑通 `VectorStore` 抽象层 + 至少 2 个 Adapter，业务代码 `recommend_routes` 零改动切换底层库
- [ ] 能说清 Claude Code 为什么不用向量库（代码检索的精确符号匹配 vs 文档检索的语义近似）

---

> **下一课预告：Day 06 — 量化压缩 + Claude Code Hooks 自动化**。今天提到 Qdrant/Pinecone 的内置量化省内存，明天我们亲手实现 Scalar/Binary 量化的原理 demo，看召回率和内存的 trade-off 曲线；同时引入 Claude Code Hooks，把"灌库后自动跑回归测试"这类流程自动化，让向量库的迭代也带上 CI 的味道。
