# Day 03 — Chroma 深入：集合 / 元数据 / 持久化

## 学习目标

Week 04 把 Chroma 当黑盒用——`add` / `query` 一把梭，一个 collection 装天下。今天要把这层黑盒拆开：用多 collection 给业务分库，用元数据过滤做精准召回，用距离函数适配不同语义场景，用批量操作扛住规模，用持久化与迁移保证数据安全。学完今天，Chroma 在你手里就不再是"能跑就行"的玩具，而是可以工程化管理的向量存储。

学完今天你能：
1. 用多 collection 按业务分库（routes / gear / trips 互不污染），并动态管理集合的生命周期
2. 用 `where` 和 `where_document` 做精准的元数据过滤与组合过滤，把召回率从"全量乱撞"提到"定向命中"
3. 说清楚 `cosine` / `l2` / `ip` 三种距离函数的语义差异，并在不同场景下正确切换
4. 写出支持批量 upsert、跨 collection 迁移、目录级备份的 `AdvancedVectorStore` 高级封装

---

## 一、Collection 集合管理

### 1.1 Collection = 数据库里的"表"

Week 04 我们自始至终只用了一个叫 `documents` 的 collection。但现实业务里，路线数据、装备数据、行程数据混在一个 collection 里就像把用户表、订单表、商品表塞进同一张表——查起来要带一堆 `where` 过滤，索引也无法针对不同分布优化。

正确做法是**按业务域分库**：

| Collection | 存什么 | 典型 metadata | 距离函数 |
|------------|--------|---------------|----------|
| `routes` | 徒步路线描述 | region / difficulty / distance_km | cosine |
| `gear` | 装备介绍 | category / weight_g / season | cosine |
| `trips` | 行程游记 | author / date / route_id | ip |

每个 collection 有独立的 HNSW 索引和独立的距离函数，互不干扰。

### 1.2 集合的增删查改

```python
"""collection 管理：创建 / 列举 / 删除 / 改配置"""
import chromadb
from chromadb.config import Settings

# PersistentClient：数据落盘，重启不丢
client = chromadb.PersistentClient(
    path="./chroma_db",
    settings=Settings(anonymized_telemetry=False),
)

# ─── 创建（或获取已存在的）───
# get_or_create：存在就拿，不存在就建，幂等安全
routes_col = client.get_or_create_collection(
    name="routes",
    metadata={"hnsw:space": "cosine"},  # 余弦相似度
)

# create_collection：不存在才建，已存在会抛异常
# 适合你想严格保证"这是第一次初始化"的场景
try:
    gear_col = client.create_collection(
        name="gear",
        metadata={"hnsw:space": "cosine"},
    )
except Exception as e:
    print(f"集合已存在: {e}")

# ─── 列举 ───
print(client.list_collections())  # ['routes', 'gear']

# ─── 删除 ───
# client.delete_collection(name="gear")  # 谨慎：不可恢复

# ─── 修改 collection 的 metadata ───
# ⚠️ Chroma 不支持直接改已建集合的 hnsw:space（索引已定型）
# 只能改非索引类的 metadata，或重建集合
routes_col.modify(metadata={"description": "徒步路线库", "hnsw:space": "cosine"})
```

> **关键认知：** `hnsw:space` 在集合创建时就定死了，因为 HNSW 索引是按这个距离函数构建的。想换距离函数 = 必须新建集合 + 重新灌数据。这和关系数据库"改个字段类型要重建索引"是一个道理。

---

## 二、元数据过滤（重点）

### 2.1 为什么元数据过滤是召回质量的分水岭

纯向量检索是"语义相近"，但它会被高频语义带偏。比如查"川西高海拔路线"，向量检索可能返回一堆"川西"相关但海拔只有 2000 米的路线。加上 `where={"region": "川西", "elevation_m": {"$gte": 3500}}`，就能精准锁定目标。

元数据过滤的执行顺序是：**先用 where 条件筛出候选集 → 再在候选集上跑向量相似度**。这叫 pre-filtering，能极大缩小搜索空间。

### 2.2 where 操作符全表

| 操作符 | 含义 | 示例 | 适用类型 |
|--------|------|------|----------|
| `$eq` | 等于（可省略） | `{"region": {"$eq": "川西"}}` | str/int/float/bool |
| `$ne` | 不等于 | `{"difficulty": {"$ne": "休闲"}}` | str/int/float/bool |
| `$gt` | 大于 | `{"elevation_m": {"$gt": 3000}}` | int/float |
| `$gte` | 大于等于 | `{"elevation_m": {"$gte": 3500}}` | int/float |
| `$lt` | 小于 | `{"distance_km": {"$lt": 20}}` | int/float |
| `$lte` | 小于等于 | `{"distance_km": {"$lte": 15}}` | int/float |
| `$in` | 在列表中 | `{"season": {"$in": ["春", "秋"]}}` | str/int/float |
| `$nin` | 不在列表中 | `{"region": {"$nin": ["市区"]}}` | str/int/float |
| `$and` | 逻辑与 | `{"$and": [...]}` | 组合 |
| `$or` | 逻辑或 | `{"$or": [...]}` | 组合 |

### 2.3 代码示例：等值 / 范围 / 组合过滤

```python
# 等值过滤：只查川西的路线
results = routes_col.query(
    query_embeddings=[q_emb],
    n_results=5,
    where={"region": "川西"},
)

# 范围过滤：海拔 ≥ 3500 且 距离 ≤ 30km
results = routes_col.query(
    query_embeddings=[q_emb],
    n_results=5,
    where={
        "$and": [
            {"elevation_m": {"$gte": 3500}},
            {"distance_km": {"$lte": 30}},
        ]
    },
)

# 枚举过滤：春季或秋季路线
results = routes_col.query(
    query_embeddings=[q_emb],
    n_results=5,
    where={"season": {"$in": ["春", "秋"]}},
)
```

### 2.4 where_document：按文本内容过滤

除了 metadata，Chroma 还能按 `documents` 字段（原文）做子串/正则过滤：

```python
# where_document 支持的操作符：$contains / $not_contains
results = routes_col.query(
    query_embeddings=[q_emb],
    n_results=5,
    where_document={"$contains": "雪山"},  # 原文必须包含"雪山"
    where={"region": "川西"},               # 再叠加 metadata 过滤
)
```

`where` 和 `where_document` 是 **AND 关系**——两个条件同时满足才进候选集。

### 2.5 metadata 值的类型铁律

```python
# ❌ 这些类型会直接报错
{"tags": ["高海拔", "风景"]}   # list 不行
{"info": {"a": 1}}            # dict 不行
{"author": None}              # None 不行

# ✅ 只能是 str / int / float / bool
{"elevation_m": 4500}         # int ✅
{"difficulty": "困难"}         # str ✅
{"is_loop": True}             # bool ✅
{"avg_slope": 12.5}           # float ✅

# list 的正确存法：拆成多个字段或用拼接字符串 + 查询时 $in
{"season_spring": True, "season_autumn": True}  # 拆字段
{"seasons": "春,秋,夏"}                          # 拼字符串（牺牲过滤灵活性）
```

---

## 三、距离函数切换

### 3.1 三种 hnsw:space 对照

| space | distance 含义 | 取值范围 | 最相似 | 典型场景 |
|-------|--------------|----------|--------|----------|
| `cosine` | `1 - cosine_similarity` | [0, 2] | 0 | 文本语义（归一化后的方向） |
| `l2` | 欧氏距离 `‖a-b‖` | [0, +∞) | 0 | 图像特征、地理坐标 |
| `ip` | 内积取负 `-（a·b）` | (-∞, +∞) | 最负 | 已归一化向量 + 想保留模长信息 |

### 3.2 怎么选

```python
# 文本语义检索 → cosine（最常用）
# 不关心向量模长，只关心方向是否一致
routes_col = client.get_or_create_collection(
    name="routes", metadata={"hnsw:space": "cosine"}
)

# 图像/坐标检索 → l2
# 模长有物理意义（如经纬度、像素特征），距离越近越像
location_col = client.get_or_create_collection(
    name="locations", metadata={"hnsw:space": "l2"}
)

# 推荐系统 → ip（内积）
# 向量已 L2 归一化时，ip 等价于 cosine，但能保留 popularity 信号
trips_col = client.get_or_create_collection(
    name="trips", metadata={"hnsw:space": "ip"}
)
```

### 3.3 distance 转 similarity 的陷阱

```python
# cosine: distance = 1 - sim, 所以 sim = 1 - distance
similarity = 1 - distance          # ✅ cosine
# sim 范围 [−1, 1]，distance 范围 [0, 2]

# l2: distance 就是欧氏距离，没有自然的"相似度"映射
# 常用 sim = 1 / (1 + distance) 做归一化
similarity = 1 / (1 + distance)    # ✅ l2 的经验转换

# ip: distance = -(内积), 所以 内积 = -distance
inner_product = -distance          # ✅ ip
```

> **血泪教训：** Week 04 我们的 `query()` 里写死 `sim = 1 - dist`，那是因为当时只用 cosine。今天多 collection 不同 space，转相似度的逻辑必须按 space 分支处理，否则 l2 / ip 的"相似度"全是错的。

---

## 四、批量操作与性能

### 4.1 批量 add：分批灌库

Chroma 单次 `add` 几万条会卡住甚至 OOM。生产实践是**分批**，每批 1000-5000 条：

```python
def batch_add(collection, ids, documents, metadatas, embeddings, batch_size=2000):
    """分批写入，避免单次 add 过大导致卡顿或内存峰值。"""
    total = len(ids)
    for start in range(0, total, batch_size):
        end = start + batch_size
        collection.add(
            ids=ids[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
            embeddings=embeddings[start:end],
        )
        print(f"  已写入 {end}/{total}")
    return total
```

### 4.2 upsert：先 delete 再 add

Chroma 没有 `upsert`（早期版本），但 `add` 时若 id 重复会**追加而不是覆盖**，导致脏数据。正确做法是**先按 id 删，再 add**：

```python
def upsert(collection, ids, documents, metadatas, embeddings):
    """Chroma 的 upsert = 先 delete 同 id 数据，再 add 新数据。"""
    # 先删（id 不存在的删操作是安全的，不会报错）
    collection.delete(ids=ids)
    # 再加
    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )
```

> 新版 Chroma（≥0.4.16）已提供 `collection.upsert()`，内部就是这个逻辑，但理解原理有助于排查重复数据问题。

### 4.3 统计与按 id 取数

```python
# count：总数（不返回数据，很轻量）
print(routes_col.count())  # 1234

# peek：看前 N 条，常用于调试
sample = routes_col.peek(limit=5)

# get：按 id 精确取，或按 where 过滤取
by_id = routes_col.get(ids=["route_001", "route_002"])
by_filter = routes_col.get(
    where={"region": "川西"},
    include=["metadatas", "documents"],
    limit=100,
)
```

### 4.4 性能建议

| 场景 | 建议 |
|------|------|
| 灌库 | 分批 2000-5000 条，关掉 telemetry |
| 查询 | `n_results` 不要过大（>50 召回质量下降明显） |
| 过滤 | 高基数字段（如 route_id）做 where，比全量查再筛快 10x |
| 索引 | 数据量 < 10 万不用调 HNSW 参数；> 50 万考虑换 Milvus |
| 内存 | Chroma 会全量加载索引到内存，百万级要预留几个 GB |

---

## 五、持久化与迁移

### 5.1 PersistentClient vs HttpClient

```python
import chromadb

# ─── PersistentClient：嵌入式，数据落本地目录 ───
# 适合：单机原型、开发调试、小规模数据
client = chromadb.PersistentClient(path="./chroma_db")

# ─── HttpClient：连接独立部署的 Chroma Server ───
# 适合：多进程共享、生产环境、需要隔离计算与存储
# 启动 server:  chroma run --host 0.0.0.0 --port 8000 --path ./chroma_data
client = chromadb.HttpClient(host="localhost", port=8000)
```

### 5.2 数据目录结构

```
chroma_db/
├── chroma.sqlite3          # 元数据 + collection 信息（SQLite）
└── <collection_uuid>/
    ├── data_level0.bin     # HNSW 索引数据
    ├── header.bin          # 索引头
    ├── length.bin          # 长度信息
    └── link_lists.bin      # 图的邻接表
```

### 5.3 备份：直接拷目录

```python
"""Chroma 备份 = 冷拷贝整个数据目录"""
import shutil

# 备份前最好停掉写入，避免 sqlite 锁冲突
shutil.copytree("./chroma_db", "./chroma_db_backup_20260630")
# 恢复：反向拷贝即可
```

### 5.4 跨 collection 迁移数据

```python
def migrate(src_col, dst_col, batch_size=1000):
    """把 src collection 的数据迁移到 dst collection。"""
    total = src_col.count()
    offset = 0
    while offset < total:
        batch = src_col.get(
            limit=batch_size,
            offset=offset,
            include=["metadatas", "documents", "embeddings"],
        )
        if not batch["ids"]:
            break
        dst_col.add(
            ids=batch["ids"],
            documents=batch["documents"],
            metadatas=batch["metadatas"],
            embeddings=batch["embeddings"],
        )
        offset += len(batch["ids"])
        print(f"  迁移 {offset}/{total}")
    return offset
```

### 5.5 完整高级封装：AdvancedVectorStore

把前面所有知识点串成一个生产可用的封装类。这就是今天的产出文件 `chroma_advanced.py` 的核心：

```python
"""chroma_advanced.py — Chroma 高级封装：多集合 + 元数据过滤 + 批量 + 持久化"""
import chromadb
from chromadb.config import Settings


class AdvancedVectorStore:
    """
    Chroma 高级封装：多集合 + 元数据过滤 + 批量 + 持久化。

    用法:
        store = AdvancedVectorStore("./chroma_db")
        store.ensure_collection("routes", space="cosine")
        store.batch_add("routes", ids, docs, metas, embs)
        results = store.query("routes", q_emb, where={"region": "川西"})
    """

    # 默认距离函数
    DEFAULT_SPACE = "cosine"

    def __init__(self, persist_path: str = "./chroma_db"):
        """初始化持久化客户端，并缓存 collection 句柄。"""
        self.client = chromadb.PersistentClient(
            path=persist_path,
            settings=Settings(anonymized_telemetry=False),
        )
        # collection 句柄缓存，避免反复 get_or_create
        self._collections: dict[str, chromadb.Collection] = {}

    # ─── 集合管理 ───

    def ensure_collection(self, name: str, space: str = None) -> chromadb.Collection:
        """获取或创建集合，space 决定距离函数。"""
        if name in self._collections:
            return self._collections[name]
        col = self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": space or self.DEFAULT_SPACE},
        )
        self._collections[name] = col
        return col

    def list_collections(self) -> list[str]:
        """列出所有集合名。"""
        return self.client.list_collections()

    def drop_collection(self, name: str) -> None:
        """删除集合（不可恢复）。"""
        self.client.delete_collection(name=name)
        self._collections.pop(name, None)

    # ─── 写入 ───

    def batch_add(
        self,
        collection_name: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
        embeddings: list[list[float]],
        batch_size: int = 2000,
    ) -> int:
        """分批写入，避免单次过大。"""
        col = self.ensure_collection(collection_name)
        total = len(ids)
        for start in range(0, total, batch_size):
            end = start + batch_size
            col.add(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
                embeddings=embeddings[start:end],
            )
        return total

    def upsert(
        self,
        collection_name: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
        embeddings: list[list[float]],
    ) -> int:
        """先删后增，保证幂等覆盖。"""
        col = self.ensure_collection(collection_name)
        col.delete(ids=ids)
        col.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        return len(ids)

    # ─── 查询 ───

    def query(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict | None = None,
        where_document: dict | None = None,
    ) -> list[dict]:
        """
        语义检索 + 元数据/文档过滤。

        返回统一格式，similarity 按 collection 的 space 自动转换。
        """
        col = self.ensure_collection(collection_name)
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            where_document=where_document,
            include=["documents", "metadatas", "distances"],
        )

        space = col.metadata.get("hnsw:space", self.DEFAULT_SPACE)
        formatted = []
        ids = results["ids"][0] if results["ids"] else []
        docs = results["documents"][0] if results["documents"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []
        dists = results["distances"][0] if results["distances"] else []

        for id_, doc, meta, dist in zip(ids, docs, metas, dists):
            # 按 space 转换相似度，避免 l2/ip 误用 1-dist
            if space == "cosine":
                sim = 1 - dist
            elif space == "l2":
                sim = 1 / (1 + dist)
            else:  # ip
                sim = -dist
            formatted.append({
                "id": id_,
                "text": doc,
                "metadata": meta,
                "distance": dist,
                "similarity": round(sim, 4),
            })
        return formatted

    # ─── 统计与取数 ───

    def count(self, collection_name: str) -> int:
        """返回集合中的向量总数。"""
        return self.ensure_collection(collection_name).count()

    def peek(self, collection_name: str, limit: int = 5) -> dict:
        """预览前 N 条，用于调试。"""
        return self.ensure_collection(collection_name).peek(limit=limit)

    def get_by_ids(self, collection_name: str, ids: list[str]) -> dict:
        """按 id 精确取数据。"""
        return self.ensure_collection(collection_name).get(ids=ids)

    # ─── 迁移 ───

    def migrate(
        self,
        src: str,
        dst: str,
        batch_size: int = 1000,
    ) -> int:
        """把 src 集合的数据迁移到 dst 集合。"""
        src_col = self.ensure_collection(src)
        dst_col = self.ensure_collection(dst)
        total = src_col.count()
        offset = 0
        while offset < total:
            batch = src_col.get(
                limit=batch_size,
                offset=offset,
                include=["metadatas", "documents", "embeddings"],
            )
            if not batch["ids"]:
                break
            dst_col.add(
                ids=batch["ids"],
                documents=batch["documents"],
                metadatas=batch["metadatas"],
                embeddings=batch["embeddings"],
            )
            offset += len(batch["ids"])
        return offset
```

---

## 六、动手实验

### 🟢 青铜级：多集合分库 + 元数据过滤

```bash
# 建两个 collection：routes 和 gear，各灌 10 条假数据
# 用 where 过滤查询，验证 routes 和 gear 的数据互不串
python -c "
from chroma_advanced import AdvancedVectorStore
import random

store = AdvancedVectorStore('./test_advanced_db')
store.ensure_collection('routes', space='cosine')
store.ensure_collection('gear', space='cosine')

# 灌 10 条路线
ids = [f'route_{i:03d}' for i in range(10)]
docs = [f'川西高海拔路线 {i} 号，雪山风景' for i in range(10)]
metas = [{'region': '川西', 'elevation_m': 3500 + i * 100} for i in range(10)]
embs = [[random.random() for _ in range(384)] for _ in range(10)]
store.batch_add('routes', ids, docs, metas, embs)

print('routes 总数:', store.count('routes'))
print('所有集合:', store.list_collections())
"
```

### 🟡 白银级：距离函数对比实验

建三个相同数据的 collection，分别用 `cosine` / `l2` / `ip`，用同一个 query 向量检索，对比三者的 distance 和 similarity 排序差异。思考：为什么同一个 query 在 l2 和 cosine 下 top_3 可能不完全一样？

### 🔴 王者级：实现带元数据过滤的混合检索

在 `AdvancedVectorStore` 基础上加一个 `hybrid_query` 方法：先用 `where` 过滤出候选集，再在候选集上做向量检索，最后叠加关键词 `$contains` 过滤。要求支持"川西 + 海拔>4000 + 原文含雪山"这种三维组合检索，并统计每层过滤掉了多少候选。

---

## 七、踩坑记录 🕳️

### 坑 1：get_or_create 不会重置 hnsw:space

```python
# 第一次用 cosine 建了 routes
client.get_or_create_collection("routes", metadata={"hnsw:space": "cosine"})

# 后来想改成 l2，再调一次 get_or_create —— ❌ 没用！
# get_or_create 发现已存在就直接返回旧的，space 还是 cosine
client.get_or_create_collection("routes", metadata={"hnsw:space": "l2"})

# ✅ 必须先 delete 再 create，或者换个名字新建
client.delete_collection("routes")
client.create_collection("routes", metadata={"hnsw:space": "l2"})
```

### 坑 2：where 过滤的字段必须存在于 metadata

```python
# 如果某些文档的 metadata 没有 elevation_m 字段，下面的 where 会漏掉它们
where={"elevation_m": {"$gte": 3500}}  # 没有 elevation_m 的文档直接被排除

# ✅ 灌库时给所有文档补齐字段，缺省值用 0 或 "unknown"
meta.setdefault("elevation_m", 0)
```

### 坑 3：$in 的值必须是 list，单值会报错

```python
# ❌ 单值不是 list
where={"season": {"$in": "春"}}      # 报错或行为异常

# ✅ 必须是 list
where={"season": {"$in": ["春"]}}    # ✅
where={"season": "春"}               # ✅ 等值更简洁
```

### 坑 4：PersistentClient 路径被多进程同时写会锁死

```python
# SQLite 不支持多进程并发写
# 两个进程同时开 PersistentClient(path="./chroma_db") 写入 → sqlite3.OperationalError: database is locked

# ✅ 解决方案：
# 1. 单进程写入，多进程只读
# 2. 或改用 HttpClient 模式（chroma run 起独立 server）
client = chromadb.HttpClient(host="localhost", port=8000)
```

### 坑 5：offset 分页在数据更新后会错位

```python
# get(limit=100, offset=200) 看似分页，但 Chroma 不保证顺序稳定
# 如果中途有 delete/add，offset 200 的位置会变 → 重复或漏数据

# ✅ 迁移数据时不要依赖 offset 分页，改用游标：
# 记录上批最后一个 id，下批 where={"_id": {"$gt": last_id}}
```

---

## 八、副线笔记：CLAUDE.md `@` 多文件引用

### 8.1 从单文件 CLAUDE.md 到 @ 引用

Week 04 我们的 `CLAUDE.md` 是单文件，所有规则堆在一起。项目一大，CLAUDE.md 就膨胀到几百行，Claude Code 每次都要读全量，既慢又稀释了重点。

Claude Code 支持 **`@path/to/file.md` 语法**——在 CLAUDE.md 里引用其他文件，Claude Code 会在需要时自动加载这些被引用文件的上下文。这和我们今天学的 Chroma 多 collection 分库是**同一个思想**：把大而全的单库拆成小而专的多库，按需加载。

### 8.2 什么时候拆分，什么时候用 @ 引用

| 场景 | 做法 | 理由 |
|------|------|------|
| 全局通用规则（代码风格、命名约定） | 留在 CLAUDE.md 主文件 | 每次都要用，不该延迟加载 |
| 某个模块的专属约定（如 `week05/` 的向量库规则） | 拆成 `week05/CLAUDE.md` 用 @ 引用 | 只在改 week05 时才需要 |
| 临时性的架构决策记录 | 拆成 `docs/adr-001.md` 用 @ 引用 | 偶尔翻阅，不必常驻上下文 |
| 大段示例代码 | 拆成 `examples/*.py` 用 @ 引用 | 避免主文件被代码淹没 |

### 8.3 一个示例 CLAUDE.md

```markdown
# 项目记忆

## 全局规则
- Python 代码用 4 空格缩进，类型注解必填
- 所有 API 返回统一 {success, data, error} 格式

## 模块约定
@week05/CLAUDE.md
@week04/CLAUDE.md

## 架构决策
@docs/adr-001-vector-db-selection.md
@docs/adr-002-embedding-strategy.md
```

### 8.4 避免上下文膨胀的三条原则

1. **@ 引用不是越多越好**：每多一个 @，Claude Code 可能多加载一个文件。只引用真正高频相关的。
2. **主文件保持精简**：CLAUDE.md 主文件控制在 50 行以内，把细节推到 @ 引用的子文件。
3. **定期清理失效引用**：项目重构后，被 @ 的文件可能已删除，Claude Code 会报找不到文件——定期 prune。

> **类比记忆：** Chroma 的多 collection 是"按业务域分库"，CLAUDE.md 的 @ 引用是"按知识域分文件"。两者都在解决同一个工程问题——**如何让上下文/数据在需要时才被加载，而不是一开始就全量铺开**。这是所有"规模化"问题的通用解法。

---

## 今日产出检查清单

- [ ] 能用 `get_or_create_collection` 管理多个 collection，理解集合生命周期
- [ ] 能用 `$gt` / `$in` / `$and` 等操作符写出组合元数据过滤
- [ ] 说清楚 `cosine` / `l2` / `ip` 三种距离函数的差异与适用场景
- [ ] 实现了分批 `batch_add` 和幂等 `upsert`
- [ ] `AdvancedVectorStore` 封装类跑通，含 query 按 space 自动转 similarity
- [ ] CLAUDE.md 用 @ 引用拆分了至少一个子文件

---

> **下一课预告：Day 04 — Milvus 生产级特性 + Docker 部署**。Chroma 是单机原型利器，但百万级数据和分布式场景就得交给 Milvus。明天我们用 Docker 起一个 Milvus，体验分区、标量字段索引、IVF/HNSW 索引选型，把"会部署生产级向量库"这一步走通。
