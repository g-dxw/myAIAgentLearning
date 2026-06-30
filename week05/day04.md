# Day 04 — Milvus 生产级特性 + Docker 部署

## 学习目标

Day 03 我们把 Chroma 用到了工程化级别：多集合、元数据过滤、批量 upsert、持久化迁移。但 Chroma 的天花板很明显——它是单机嵌入式向量库，索引全量驻留内存，百万级数据就开始吃力，更别说高并发写入和多副本高可用。今天我们跨入生产级：用 Docker 跑起 Milvus，理解它的存算分离架构，把 Schema、索引选型、分区检索这三把刀磨快。学完今天，你就具备了"从原型向量库升级到分布式向量库"的判断力和动手能力。

学完今天你能：
1. 用 Docker Compose 一键拉起 Milvus Standalone（etcd + MinIO + milvus），并验证服务健康
2. 用 pymilvus 的 `MilvusClient` 新 API 定义 Schema、建索引、插入、检索、标量过滤
3. 说清楚 FLAT / IVF_FLAT / IVF_SQ8 / IVF_PQ / HNSW / DISKANN 六种索引的原理、内存与召回权衡，并按数据规模选出索引
4. 用 Partition 按业务维度（地区/时间）物理分区，检索时指定分区加速

---

## 一、为什么单机不够：从 Chroma 到 Milvus

### 1.1 Chroma 单机的三道天花板

Day 03 的 `AdvancedVectorStore` 在十万级数据下表现尚可，但只要业务往上长，三道墙会依次撞上：

| 瓶颈维度 | Chroma 的表现 | 触发阈值 |
|----------|--------------|----------|
| **数据量** | HNSW 索引全量驻留内存，百万级要预留几个 GB | 约 100 万向量 |
| **并发** | SQLite 单写者锁，多进程并发写直接 `database is locked` | 任意并发写 |
| **可用性** | 单机单盘，进程挂了/磁盘坏了即数据不可用 | 任意故障 |

Day 03 踩坑记录里的"PersistentClient 多进程写会锁死"就是并发墙的具象——SQLite 不支持多进程并发写。要绕开它只能上 `HttpClient` 起独立 server，但那依然是个单点。

### 1.2 Milvus 的定位

Milvus 是**云原生、存算分离、开源**的分布式向量数据库，由 Zilliz 团队主导，CNCF 毕业项目。它的设计目标就是补上 Chroma 缺的那三块：

- **亿级规模**：索引可下沉到磁盘（DISKANN），内存不再是硬上限
- **水平扩展**：QueryNode / DataNode / IndexNode 可独立扩缩容，读写分离
- **高可用**：依赖 etcd 做服务发现 + MinIO 做对象存储，组件多副本

> **类比记忆：** Chroma 之于向量库，就像 SQLite 之于关系数据库——单机原型利器；Milvus 之于向量库，就像 PostgreSQL/分布式数据库——生产级选手。Day 03 学的是怎么把 SQLite 用到极致，今天学的是什么时候该换 Postgres。

---

## 二、Milvus 架构：存算分离

### 2.1 核心思想：存算分离

Milvus 把"存数据"和"算检索"拆开：
- **存储层**：MinIO（对象存储，存 segment 数据和索引文件）+ etcd（元数据）
- **计算层**：QueryNode（查询）、DataNode（写入）、IndexNode（建索引），无状态可随时增删

这意味着检索压力大时只加 QueryNode，建索引慢时只加 IndexNode，互不影响。Chroma 那种"计算和存储绑死在一个进程"的设计做不到这一点。

### 2.2 架构组件表

| 组件 | 类型 | 职责 | 是否有状态 |
|------|------|------|-----------|
| **RootCoord** | 协调节点 | 元数据管理、DDL/DML 入口，集群"大脑" | 轻状态 |
| **QueryCoord** | 协调节点 | 调度 QueryNode，决定哪个 segment 在哪个节点查 | 无状态 |
| **DataCoord** | 协调节点 | 管理 segment 生命周期、数据写入分配 | 无状态 |
| **IndexCoord** | 协调节点 | 调度 IndexNode 构建索引 | 无状态 |
| **QueryNode** | 计算节点 | 执行向量检索，加载 segment 到内存 | 无状态 |
| **DataNode** | 计算节点 | 消费 Pulsar 日志、写 segment 到 MinIO | 无状态 |
| **IndexNode** | 计算节点 | 构建 FLAT/IVF/HNSW 等索引 | 无状态 |
| **etcd** | 依赖 | 存元数据、服务发现、配置 | 有状态 |
| **MinIO** | 依赖 | 对象存储，存 segment 和索引文件 | 有状态 |
| **Pulsar** | 依赖 | 消息队列，写请求流式处理（Cluster 模式） | 有状态 |

### 2.3 两种部署模式

| 模式 | 组件 | 适用场景 | 资源占用 |
|------|------|----------|----------|
| **Standalone** | 一个 milvus 进程内置所有 Coord + Node + 依赖 | 学习/开发/小规模生产（<1000万） | 低（约 2-4GB 内存） |
| **Cluster** | Coord / Node 独立部署，依赖外部 etcd + MinIO + Pulsar | 生产大规模（千万~亿级） | 高，可水平扩展 |

> **本节关键决策：** 今天我们用 **Standalone** 跑通流程——它把 Cluster 的所有组件压缩进一个容器，API 完全一致。学习阶段用 Standalone，理解了之后生产环境切 Cluster 只是改部署编排，业务代码一行不用动。这是 Milvus 设计的友好之处。

---

## 三、Docker Compose 部署 Milvus Standalone

### 3.1 docker-compose.yml

在项目下建 `week05/milvus/` 目录，放入以下 `docker-compose.yml`。Standalone 模式仍需要 etcd 和 MinIO 两个外部依赖：

```yaml
# docker-compose.yml — Milvus Standalone 单机部署
version: '3.5'

services:
  # ─── etcd：存元数据和服务发现 ───
  etcd:
    image: quay.io/coreos/etcd:v3.5.5
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
      - ETCD_QUOTA_BACKEND_BYTES=4294967296
      - ETCD_SNAPSHOT_COUNT=50000
    volumes:
      - etcd_data:/etcd
    command: etcd -advertise-client-urls=http://etcd:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    healthcheck:
      test: ["CMD", "etcdctl", "endpoint", "health"]
      interval: 30s
      timeout: 20s
      retries: 3

  # ─── MinIO：对象存储，存 segment 和索引 ───
  minio:
    image: minio/minio:RELEASE.2023-03-20T20-16-18Z
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    volumes:
      - minio_data:/minio_data
    command: minio server /minio_data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

  # ─── Milvus Standalone：内置所有 Coord + Node ───
  milvus-standalone:
    image: milvusdb/milvus:v2.4.0
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
    volumes:
      - milvus_data:/var/lib/milvus
    ports:
      - "19530:19530"   # gRPC 端口，pymilvus 连这个
      - "9091:9091"     # 健康检查/metrics 端口
    depends_on:
      - etcd
      - minio
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9091/healthz"]
      interval: 30s
      timeout: 20s
      retries: 3

volumes:
  etcd_data:
  minio_data:
  milvus_data:
```

### 3.2 启动与验证

```bash
# 进入部署目录
cd week05/milvus

# 后台拉起三个容器（首次会拉镜像，约几分钟）
docker compose up -d

# 查看容器状态，三个都应为 Up
docker compose ps

# 验证 Milvus 健康（9091 是健康检查端口）
curl http://localhost:9091/healthz
# 输出 OK 即正常

# 查看 Milvus 启动日志，确认监听 19530
docker logs milvus-standalone --tail 50

# 停止（保留数据）
docker compose down

# 彻底清除（连数据卷一起删，谨慎）
# docker compose down -v
```

> **端口速记：** `19530` 是 pymilvus 连接的 gRPC 端口（对应 Chroma 的 8000）；`9091` 是健康检查和 Prometheus metrics 端口。开发时只暴露这两个就够。

---

## 四、pymilvus 基础操作（MilvusClient 新 API）

### 4.1 安装与连接

```bash
# 安装 pymilvus（注意版本要 ≥ 2.4，对齐 Milvus server 版本）
pip install "pymilvus>=2.4.0"
```

```python
"""连接 Milvus —— MilvusClient 是 2.3+ 推荐的新统一 API"""
from pymilvus import MilvusClient

# Standalone 直接连 uri 即可，无需显式 disconnect
client = MilvusClient(uri="http://localhost:19530")

# 验证连接：列出 collection（首次应为空）
print("已有 collections:", client.list_collections())
```

### 4.2 定义 Schema：主键 / 向量 / 标量字段

Day 03 Chroma 的 metadata 只能存 str/int/float/bool 四种扁平类型。Milvus 的 Schema 是强类型的，更像关系数据库的表定义：

```python
"""定义 Collection Schema：主键 + 向量字段 + 标量字段"""
from pymilvus import MilvusClient, DataType

# 用 create_schema 构建强类型 schema
schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)

# 主键：VARCHAR 类型，存业务 id（如 route_001）
schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)

# 向量字段：固定维度，必须和 embedding 模型对齐
schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=384)

# 标量字段：用于过滤，类型比 Chroma 丰富
schema.add_field("region", DataType.VARCHAR, max_length=32)    # 地区：川西/滇西北
schema.add_field("elevation_m", DataType.INT64)                # 海拔：整型
schema.add_field("difficulty", DataType.VARCHAR, max_length=16) # 难度
schema.add_field("is_loop", DataType.BOOL)                     # 是否环线
```

> **与 Chroma 的关键差异：** Chroma 的 metadata 是松散 dict，灌库时才确定类型；Milvus 是**先定义 Schema 再灌数据**，类型不对直接报错。这看似繁琐，但能避免"上线后才发现一半数据缺字段"的灾难。

### 4.3 创建索引 + 建集合 + 插入 + 检索

索引必须在**检索前**创建，且 Milvus 2.4 要求建集合时就带索引参数。下面把完整流程串起来：

```python
"""完整流程：建集合 → 建索引 → 插入 → 加载 → 检索"""
import random

COLLECTION = "routes"
DIM = 384

# Step 1: 准备索引参数（HNSW，适合中小规模 + 高召回）
index_params = client.prepare_index_params()
index_params.add_index(
    field_name="embedding",
    index_type="HNSW",
    metric_type="COSINE",
    params={"M": 16, "efConstruction": 200},
)

# Step 2: 创建集合（schema + 索引一起带上）
if client.has_collection(COLLECTION):
    client.drop_collection(COLLECTION)  # 重建前先删，保证幂等

client.create_collection(
    collection_name=COLLECTION,
    schema=schema,
    index_params=index_params,
)

# Step 3: 插入数据（MilvusClient 接受 list[dict]，字段对齐 schema）
data = [
    {
        "id": f"route_{i:03d}",
        "embedding": [random.random() for _ in range(DIM)],
        "region": "川西" if i % 2 == 0 else "滇西北",
        "elevation_m": 3500 + i * 100,
        "difficulty": "困难" if i % 3 == 0 else "中等",
        "is_loop": bool(i % 2),
    }
    for i in range(100)
]
client.insert(collection_name=COLLECTION, data=data)
print(f"插入 {len(data)} 条")

# Step 4: 加载集合到 QueryNode 内存（检索前必须 load）
client.load_collection(COLLECTION)

# Step 5: 向量检索（带标量过滤）
query_vec = [random.random() for _ in range(DIM)]
results = client.search(
    collection_name=COLLECTION,
    data=[query_vec],
    limit=5,
    filter='region == "川西" and elevation_m >= 3800',  # 标量过滤表达式
    output_fields=["id", "region", "elevation_m", "difficulty"],
)

for hits in results:
    for hit in hits:
        print(f"  id={hit['id']} distance={hit['distance']:.4f} "
              f"region={hit['entity']['region']} elev={hit['entity']['elevation_m']}")
```

### 4.4 标量过滤表达式语法

Milvus 的 `filter` 用的是类 SQL 表达式，比 Chroma 的 `$and/$or` 字典更直观：

```python
# 等值
filter='region == "川西"'
# 范围
filter='elevation_m >= 3500 and elevation_m <= 5000'
# 枚举（IN）
filter='difficulty in ["困难", "中等"]'
# 布尔
filter='is_loop == true'
# 组合
filter='region == "川西" and elevation_m >= 3800 and is_loop == true'
```

> **坑预警：** 字符串值要用**双引号** `"川西"`，表达式整体在 Python 里用单引号包裹。混用引号会解析失败（见踩坑记录坑 2）。

---

## 五、索引类型选型（重点）

这是今天最值钱的知识点。Day 02 我们深入过 HNSW，今天把 Milvus 支持的六种主流索引放一起对比，建立"数据规模 → 索引"的决策直觉。

### 5.1 六种索引原理对比

| 索引 | 原理 | 内存占用 | 召回率 | 建索引速度 | 适用规模 |
|------|------|----------|--------|-----------|----------|
| **FLAT** | 暴力遍历，无近似 | 高（原始向量） | 100% | 无需建 | < 10 万 |
| **IVF_FLAT** | K-means 聚类后簇内暴力 | 中 | 高（95%+） | 中 | 10万 ~ 100万 |
| **IVF_SQ8** | IVF + 标量量化（8bit） | 低（压缩 4x） | 中高 | 中 | 100万 ~ 1000万 |
| **IVF_PQ** | IVF + 乘积量化 | 极低（压缩 16x+） | 中 | 中 | 1000万 ~ 亿 |
| **HNSW** | 分层小世界图 | 高（图结构） | 极高（98%+） | 慢 | < 1000万（内存够） |
| **DISKANN** | 磁盘图索引，热点驻内存 | 极低（下沉磁盘） | 高 | 慢 | 亿级，内存放不下 |

### 5.2 决策表：数据规模 → 推荐索引

| 数据规模 | 内存预算 | 推荐索引 | 推荐理由 |
|----------|----------|----------|----------|
| < 10 万 | 充足 | FLAT | 数据少，暴力搜最快且召回 100% |
| 10万 ~ 100万 | 充足 | HNSW | 召回极高，查询毫秒级 |
| 10万 ~ 100万 | 紧张 | IVF_FLAT | 召回略低于 HNSW，但内存省一半 |
| 100万 ~ 1000万 | 充足 | HNSW | 仍可放内存，体验最好 |
| 100万 ~ 1000万 | 紧张 | IVF_SQ8 | 量化压缩，召回损失可接受 |
| 1000万 ~ 1亿 | 紧张 | IVF_PQ | 极致压缩，换取内存可控 |
| > 1 亿 | 放不下内存 | DISKANN | 索引下沉磁盘，内存只放热点 |

### 5.3 选型决策树（口语版）

```
数据量 < 10 万？              → FLAT（别折腾，暴力最快）
内存放得下全部向量？
  ├─ 是 + 召回要求高           → HNSW
  └─ 是 + 要省内存             → IVF_FLAT / IVF_SQ8
内存放不下？
  ├─ 能接受召回损失换极致压缩   → IVF_PQ
  └─ 召回要高 + 接受磁盘延迟   → DISKANN
```

> **和 Day 02 的呼应：** Day 02 我们手撕了 HNSW 的 `M` 和 `efConstruction`。在 Milvus 里 HNSW 仍是"内存够就首选"的索引，只是当数据大到内存扛不住时，才下沉到 IVF 系列或 DISKANN。索引选型本质是"内存/召回/延迟"三角的权衡。

---

## 六、Partition 分区检索

### 6.1 为什么需要分区

Day 03 我们用元数据 `where={"region": "川西"}` 做过滤——这是**逻辑过滤**，检索时仍要遍历全量索引再筛。当数据量上百万，全量遍历的开销就很可观。

Milvus 的 Partition 是**物理分区**：把数据按维度（如地区、时间）预先切到不同物理 segment，检索时指定 `partition_names`，直接跳过其他分区，搜索空间骤减。

| 维度 | Chroma where 过滤 | Milvus Partition |
|------|-------------------|------------------|
| 切分方式 | 逻辑（检索后筛） | 物理（检索前切） |
| 搜索空间 | 全量索引 | 单分区索引 |
| 适合场景 | 过滤条件多变 | 按固定维度切（地区/时间） |

### 6.2 分区创建 + 指定分区检索

```python
"""Partition 分区：按地区物理切分，检索时指定分区加速"""

# 假设 routes 集合已建好（同第四节）
REGIONS = ["川西", "滇西北", "青海"]

# Step 1: 为每个地区创建分区
for region in REGIONS:
    client.create_partition(
        collection_name=COLLECTION,
        partition_name=region,  # 分区名即地区名，直观
    )
print("已创建分区:", client.list_partitions(COLLECTION))

# Step 2: 插入时指定分区，数据落到对应物理 segment
for region in REGIONS:
    region_data = [
        {
            "id": f"{region}_{i:03d}",
            "embedding": [random.random() for _ in range(DIM)],
            "region": region,
            "elevation_m": 3500 + i * 100,
            "difficulty": "中等",
            "is_loop": True,
        }
        for i in range(50)
    ]
    client.insert(
        collection_name=COLLECTION,
        data=region_data,
        partition_name=region,  # 关键：指定分区写入
    )

# Step 3: 检索时指定分区，只在"川西"分区内搜
query_vec = [random.random() for _ in range(DIM)]
results = client.search(
    collection_name=COLLECTION,
    data=[query_vec],
    partition_names=["川西"],   # 只搜川西分区，跳过另外两个
    limit=5,
    output_fields=["id", "region", "elevation_m"],
)

print("川西分区检索结果:")
for hit in results[0]:
    print(f"  id={hit['id']} region={hit['entity']['region']} "
          f"elev={hit['entity']['elevation_m']}")
```

### 6.3 分区 vs 标量过滤：什么时候用哪个

| 场景 | 推荐方案 | 理由 |
|------|----------|------|
| 查询总是带"地区=川西" | Partition | 物理切分，搜索空间最小 |
| 查询条件多变（地区/难度/季节随意组合） | 标量过滤 | 灵活，不用预先穷举所有组合 |
| 数据有明显冷热（如按年分区，老数据冷） | Partition | 老分区可不加载到内存，省资源 |
| 数据量小（<10万） | 标量过滤 | 分区收益抵不过管理成本 |

> **生产建议：** 分区维度选**高基数且查询高频**的（如 region、tenant_id、年月）。一个 collection 最多 4096 个分区，别按 user_id 这种百万基数字段切，会撑爆。这种细粒度场景用标量过滤更合适。

---

## 七、动手实验

### 🟢 青铜级：Docker 起 Milvus + 跑通插入检索

```bash
# 1. 用第三节的 docker-compose.yml 拉起 Milvus
cd week05/milvus && docker compose up -d
curl http://localhost:9091/healthz  # 确认 OK

# 2. 跑第四节的最小示例：建集合 → 插 100 条 → 检索
python milvus_demo.py
```

目标：看到检索结果输出，`distance` 字段有合理值。

### 🟡 白银级：索引选型对比实验

对同一个 `routes` 集合，分别用 `FLAT` / `IVF_FLAT` / `HNSW` 三种索引灌同样的 1 万条数据，用同一批 50 个 query 检索，对比：
- 三者的平均查询延迟
- 三者 top-10 的召回率（以 FLAT 结果为 ground truth）

思考：为什么 HNSW 在 1 万条时可能比 IVF_FLAT 慢一点但召回更高？

### 🔴 王者级：分区 + 标量过滤混合检索

按地区建 3 个分区（川西/滇西北/青海），每个分区灌 1000 条。实现一个 `hybrid_search` 方法：先指定 `partition_names=["川西"]` 缩小空间，再叠加 `filter='elevation_m >= 4000 and difficulty == "困难"'`。统计"分区过滤"和"标量过滤"各砍掉了多少候选，验证分区加速效果。

---

## 八、踩坑记录 🕳️

### 坑 1：检索前忘记 load_collection

```python
# ❌ 插入后直接 search，报错：collection not loaded
client.insert(COLLECTION, data)
client.search(COLLECTION, data=[q], limit=5)
# Raise: collection routes is not loaded

# ✅ 检索前必须 load，把 segment 加载到 QueryNode 内存
client.load_collection(COLLECTION)
client.search(COLLECTION, data=[q], limit=5)

# ✅ 改完数据后要 release 再 load，否则查到的是旧数据
client.release_collection(COLLECTION)
client.load_collection(COLLECTION)
```

### 坑 2：标量过滤的引号混用

```python
# ❌ 字符串值用单引号，和 Python 外层引号冲突，解析失败
filter="region == '川西'"
# Raise: failed to create query plan: invalid expression

# ✅ 字符串值用双引号，外层用单引号
filter='region == "川西"'

# ✅ 布尔/数字不用引号
filter='elevation_m >= 3800 and is_loop == true'
```

### 坑 3：向量维度 dim 和 embedding 模型对不上

```python
# Schema 声明 384 维（对应 bge-small / MiniLM）
schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=384)

# ❌ 但实际用的是 1536 维的 OpenAI text-embedding-3
emb = openai_embed("text")  # 返回 1536 维
client.insert(COLLECTION, data=[{"embedding": emb, ...}])
# Raise: vector dimension mismatch, expected 384, got 1536

# ✅ dim 必须和 embedding 模型输出维度严格一致，建集合前先确认
```

### 坑 4：HNSW 建索引时内存飙升，OOM

```python
# ❌ M=64 + 数据量百万级，建索引时内存峰值爆掉容器
index_params.add_index(field_name="embedding", index_type="HNSW",
                       metric_type="COSINE", params={"M": 64, "efConstruction": 500})

# ✅ 学习/小规模用默认参数 M=16, efConstruction=200
params={"M": 16, "efConstruction": 200}

# ✅ 数据量大且内存紧张，换 IVF_SQ8 或 DISKANN，别硬上 HNSW
```

### 坑 5：Docker 容器磁盘写满

```bash
# Milvus 的 segment 和索引全写 MinIO 卷，灌库几百万条后磁盘吃紧
# 现象：插入变慢、报错 "no space left on device"

# ✅ 查看卷占用
docker system df
docker volume inspect milvus_milvus_data

# ✅ 定期清理：down -v 重来（学习环境）
# ✅ 生产环境给 MinIO 卷挂大盘，或定期 compact 旧 segment
```

---

## 九、副线笔记：用 Claude Code 管理 Milvus 部署

### 9.1 基础设施即代码（IaC）的思路

Day 03 我们让 Claude Code 帮忙写 Chroma 封装类。今天升级一档：让 Claude Code **管理整个 Milvus 的部署生命周期**。核心思路是**基础设施即代码（Infrastructure as Code）**——把 docker-compose.yml、部署脚本、验证脚本都纳入版本管理，让 Claude Code 维护这些"声明式描述"，而不是靠人肉敲命令。

手敲 `docker run` 的问题在于：不可复现、不可审计、换台机器就忘参数。把这些固化成文件后，Claude Code 能基于这些文件帮你做三件事：

| 任务 | 你对 Claude Code 说 | 它做的事 |
|------|---------------------|----------|
| 写部署文件 | "帮我写个 Milvus Standalone 的 docker-compose" | 生成 etcd+MinIO+milvus 三件套 yaml |
| 调试故障 | "milvus 容器起不来，帮我查日志" | 跑 `docker logs` 定位报错行 |
| 写运维文档 | "把部署和验证步骤写成 README" | 生成可复现的命令清单 |

### 9.2 让 Claude Code 调试部署问题

部署最容易卡在"容器状态不对"。与其自己 `docker logs` 翻几百行，不如让 Claude Code 直接接管排查。在一个有 docker-compose.yml 的目录里启动 Claude Code，给它这样的指令：

```text
milvus-standalone 容器一直在 restarting，帮我排查。
先看 docker compose ps，再看 milvus 和 etcd 的日志，
找出根因并直接改 docker-compose.yml 修掉。
```

Claude Code 会用它的 shell 工具跑 `docker compose ps`、`docker logs milvus-standalone`、`docker logs milvus-etcd`，定位到（比如）etcd 健康检查没通过导致 milvus 提前启动，然后给 docker-compose.yml 的 `depends_on` 加上 `condition: service_healthy`，再 `docker compose up -d` 验证。整个过程你只发了一句话。

### 9.3 让 Claude Code 维护部署脚本

把重复的运维操作固化为脚本，让 Claude Code 帮你写并持续维护。建一个 `week05/milvus/deploy.sh`：

```bash
#!/usr/bin/env bash
# deploy.sh — Milvus Standalone 部署/验证/清理一键脚本
# 用法: ./deploy.sh {up|down|status|logs|clean}

set -e
ACTION=${1:-up}
COMPOSE_FILE="docker-compose.yml"

case "$ACTION" in
  up)
    echo "[1/3] 拉起 Milvus..."
    docker compose -f "$COMPOSE_FILE" up -d
    echo "[2/3] 等待健康..."
    sleep 15
    echo "[3/3] 验证..."
    curl -sf http://localhost:9091/healthz && echo " -> Milvus 健康 OK" || echo " -> 健康检查失败"
    ;;
  down)
    docker compose -f "$COMPOSE_FILE" down
    ;;
  status)
    docker compose -f "$COMPOSE_FILE" ps
    ;;
  logs)
    docker compose -f "$COMPOSE_FILE" logs --tail=50 milvus-standalone
    ;;
  clean)
    docker compose -f "$COMPOSE_FILE" down -v
    echo "已清除所有数据卷"
    ;;
  *)
    echo "用法: $0 {up|down|status|logs|clean}"
    exit 1
    ;;
esac
```

写完后让 Claude Code review：给它指令"看看 deploy.sh 有没有边界问题，比如 up 时 Milvus 没起来 curl 会误判"。它会指出 `set -e` + `curl -sf` 失败会直接退出，建议改成带重试的循环——这正是 IaC 的价值，脚本越打磨越稳。

### 9.4 一条原则：让 Claude Code 守住"可复现"

用 Claude Code 管部署时，守住一条底线：**任何环境变更都必须落到文件里**。装个包要写进 requirements.txt，改个端口要改 docker-compose.yml，调个参数要进配置文件。如果某次 Claude Code 建议你 `docker exec` 进容器手改配置，要拒绝——那是一次性操作，下次重建就丢了。让它改成"修改挂载的配置文件或环境变量"。这样你的部署就是可复现的：换台机器，git clone + `./deploy.sh up`，一模一样的环境就起来了。

> **类比记忆：** Day 03 的 `AdvancedVectorStore` 把 Chroma 操作封装成可复用类；今天的 `docker-compose.yml` + `deploy.sh` 把 Milvus 部署封装成可复现代码。两者都在做同一件事——**把易失的人肉操作固化为可版本管理的代码**。Claude Code 是帮你固化这些代码的搭档。

---

## 今日产出检查清单

- [ ] 用 Docker Compose 拉起 Milvus Standalone，`curl /healthz` 返回 OK
- [ ] 用 `MilvusClient` 跑通建集合 → 插入 → 加载 → 检索全流程
- [ ] 说清楚六种索引的内存/召回权衡，能按数据规模选出索引
- [ ] 实现了 Partition 分区创建 + 指定分区检索，验证搜索空间缩小
- [ ] 标量过滤表达式能正确组合 `==` / `>=` / `in` / `and`
- [ ] 产出 `milvus_demo.py`，封装了连接/建库/索引/分区/检索的完整示例

---

> **下一课预告：Day 05 — Qdrant + Pinecone 对比 + 选型决策**。今天我们上手了 Milvus，但向量数据库江湖不止一家。明天横向对比 Qdrant（Rust 写的高性能开源库）和 Pinecone（全托管 SaaS），从性能、成本、运维负担、生态四个维度建立选型框架，最终产出一张"业务场景 → 向量库推荐"的决策表。
