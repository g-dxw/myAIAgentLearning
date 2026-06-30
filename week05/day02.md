# Day 02 — HNSW 算法深入 + 参数调优

## 学习目标

昨天我们盘点了 ANN 的三大算法族（IVF / 图 / 哈希），今天要把其中最主流的 **HNSW（Hierarchical Navigable Small World，分层可导航小世界图）** 彻底拆透。HNSW 是 Chroma / Milvus / Qdrant / Weaviate 的默认索引，理解它的原理和三个核心参数（M / ef_construction / ef_search），你才知道为什么召回低、为什么查询慢、什么时候该调哪个钮。配套产出 `hnsw_demo.py` 会用 numpy 从零实现一个简化版 HNSW，并跑一遍参数调优实验。

学完今天你能：
1. 说清楚 NSW 的"图上贪心跳跃"思想和它的两个缺陷，以及 HNSW 用"分层"如何解决
2. 解释 M / ef_construction / ef_search 三个参数各自影响什么、推荐取值范围
3. 读懂一个简化版 HNSW 的插入与查询流程（分层贪心搜索）
4. 设计一组参数调优实验，用召回率（Recall@K）和延迟定量评估索引质量

---

## 一、为什么需要图索引：IVF 的局限

Day 01 讲过 IVF（倒排文件 + 聚类）：把向量空间切成 `nlist` 个簇心，查询时只搜最近的 `nprobe` 个簇。它简单、好理解，但有两个硬伤：

| IVF 的局限 | 表现 | 根因 |
|-----------|------|------|
| **聚类粒度粗** | `nlist` 小则每簇太大、慢；`nlist` 大则每簇样本少、召回不稳 | 聚类是"硬划分"，一个点只属于一个簇 |
| **边界数据漏检** | 落在两个簇交界处的近邻，可能因为只 probe 了其中一个簇而被漏掉 | 真实近邻可能跨簇，`nprobe` 不够就丢 |
| **召回靠 nprobe 硬撑** | 想要高召回就得调大 `nprobe`，又退化为接近暴力搜索 | 没有利用"近邻的近邻大概率也是近邻"这一结构 |

图方法换了个思路：**不预先切空间，而是把每个向量当作节点，和它的近邻连边，查询时在图上"跳跃式"逼近目标**。因为利用了"近邻的近邻"这种传递性，图索引能在保持高召回的同时把搜索复杂度从 O(N) 降到约 O(log N)。HNSW 就是图索引里工程效果最好、用得最广的一个。

---

## 二、NSW（可导航小世界图）

### 2.1 基础概念

NSW（Navigable Small World）的建图思路很直白：

- 每个向量 = 图中的一个节点
- 插入时，找到新节点的若干个近邻，连双向边
- 查询时，从一个**入口点**出发，**贪心**地走向更近的邻居，直到走不动为止

```
        q (查询点)
        |
        |  贪心跳跃方向
        v
   A----B----C
   |    |    |
   D----E    F----G
        |         |
        H---------I

查询流程：入口 A → B(更近) → E(更近) → H → ... → 收敛到 q 附近
```

关键性质是"小世界"：虽然每个节点只连少数几条边（局部连接），但图的直径很短（任意两点之间几跳就能到），所以贪心搜索能快速从任意入口逼近目标区域。

### 2.2 NSW 的两个缺陷

NSW 原始版本有两个问题，正是 HNSW 要解决的：

1. **入口点随机**：从哪个点开始贪心，影响收敛速度和质量。如果入口离目标很远，贪心可能要走很多跳，甚至陷入局部最优。
2. **单层图难平衡"长距离跳"和"精确定位"**：要快速跨大距离，需要长边；要精确定位，需要短边（稠密连接）。同一个图里同时塞长边和短边，边数会爆炸，内存和搜索成本都扛不住。

HNSW 的解法很优雅：**分层**。上层只放长边（稀疏），下层放短边（稠密）。

---

## 三、HNSW 分层结构

### 3.1 多层图示意

HNSW 把图分成多层。每个节点插入时按指数衰减的概率分配一个"最高层级" `level`：绝大多数节点只在第 0 层（最稠密），少数节点出现在更高层（更稀疏）。最高层有一个全局入口点。

```
Layer 2  (最稀疏，长距离跳)         [P]
                                       |  贪心下降 (ef=1, 快速定位大区域)
Layer 1  (中等密度)         [K]------[L]
                              |        |  贪心下降
Layer 0  (最稠密，精确)  [A]--[B]--[C]--[D]--[E]--[F] ...
                         |    |    |    |    |    |
                         [G]-[H]-[I]-[J]-[M]-[N]-...

查询 q：
  1. 从顶层入口 [P] 出发，ef=1 贪心跳 -> 定位到大致区域
  2. 逐层下降，每层都在更稠密的图上精修入口点
  3. 到第 0 层用 ef_search 精搜 -> 返回 top_k
```

### 3.2 为什么分层能"又快又准"

| 层 | 节点密度 | 边的性质 | 搜索作用 |
|----|---------|---------|---------|
| 高层 | 极稀疏 | 长距离边 | 快速跨越大区域，把入口点"投递"到目标附近 |
| 中层 | 中等 | 中距离边 | 逐步收窄到目标邻域 |
| 第 0 层 | 全部节点 | 短距离稠密边 | 精确定位最近邻 |

这就像查字典：先翻目录（高层，几页就定位到章节），再翻章内小节（中层），最后逐字核对（第 0 层）。每一层都在做"缩小范围"，但高层用极少的边完成长距离移动，避免了在稠密图里长距离贪心要跳几十跳的浪费。

**核心直觉**：分层把"长距离导航"和"精确定位"解耦到不同层，既不增加总边数（高层节点少），又让搜索路径长度变成 O(log N) 量级。这就是 HNSW 比纯 NSW 又快又准的根本原因。

---

## 四、HNSW 三个核心参数详解

HNSW 的调优几乎全围绕这三个参数。理解它们的代价权衡，比死记经验值重要。

### 4.1 M —— 每个节点的最大连接数

- **含义**：每个节点在每层最多保留多少条邻居边（第 0 层通常会翻倍到 `2M`）。
- **调大**：图更稠密，连通性更好，召回更高；但内存线性增长，建索引和查询都更慢。
- **调小**：省内存、查询快；但图稀疏，容易陷入局部最优，召回下降。
- **经验值**：`16 ~ 48`。通用场景 `16` 起步，对召回要求高 / 维度高时上 `32`、`48`。

### 4.2 ef_construction —— 建索引时的搜索宽度

- **含义**：插入每个节点、为它挑选邻居时，候选集的搜索宽度。
- **调大**：建索引时探索更充分，邻居选得更准，索引质量更好、召回更高；但**建索引时间显著变长**。
- **调小**：建得快；但索引质量差，召回上不去，而且这个损失**事后调 ef_search 也补不回来**。
- **经验值**：`200 ~ 500`。这是一次性成本，通常舍得给大一点。

### 4.3 ef_search —— 查询时的搜索宽度

- **含义**：查询时在第 0 层维护的候选集大小，必须 `>= top_k`。
- **调大**：探索更多节点，召回更高；但**查询延迟线性上升**。
- **调小**：查询快；但召回降低。
- **经验值**：`>= top_k`，常用 `50 ~ 200`。这是唯一一个**可以在不重建索引的情况下动态调整**的参数，线上 A/B 最先调它。

### 4.4 参数影响对照表

| 参数 | 调大影响 | 调小影响 | 推荐范围 | 能否在线调整 |
|------|---------|---------|---------|-------------|
| `M` | 召回↑、内存↑、建/查都变慢 | 召回↓、省内存 | 16 ~ 48 | 否（需重建） |
| `ef_construction` | 索引质量↑、建索引慢 | 索引质量↓（不可逆） | 200 ~ 500 | 否（需重建） |
| `ef_search` | 召回↑、查询延迟↑ | 召回↓、查询快 | ≥ top_k，50 ~ 200 | **是** |

> **一句话记忆**：`M` 决定图的"骨架"，`ef_construction` 决定骨架"搭得准不准"，`ef_search` 决定查询时"搜得勤不勤"。前两个是建库时的一次性投资，第三个是线上可调的旋钮。

---

## 五、用 numpy 手写一个简化版 HNSW

完整可运行代码见 `hnsw_demo.py`，这里拆解三个最关键的片段。教学版用 `heapq` 实现优先队列，遵循 HNSW 论文的搜索算法。

### 5.1 层级分配：指数衰减

每个节点插入时随机抽一个"最高层级"，让上层自然变稀疏：

```python
def _random_level(self) -> int:
    """
    按指数衰减概率分配层级：层号越大，落到该层的概率越低。
    系数 mL = 1/ln(M)，这正是 HNSW「上层稀疏、下层稠密」的来源。
    """
    return int(-np.log(np.random.random() + 1e-12) * self.mL)
```

### 5.2 单层搜索：best-first + ef 边界

这是 HNSW 的心脏，对应论文 Algorithm 2。维护两个堆：候选集 `C`（min-heap，决定下一步展开谁）和结果集 `W`（max-heap，容量 `ef`，始终留最近的 `ef` 个）。

```python
def _search_layer(self, query, entry_points, ef, layer):
    """
    在单层图上做 best-first 搜索，维护大小为 ef 的结果集。

    - C: 候选 min-heap，按距离升序，决定下一个要展开的节点
    - W: 结果 max-heap（用负距离模拟），容量 ef
    - 终止条件: 候选最近 > 结果最远 时停止（更优的候选都已展开完）
    """
    visited = set(entry_points)
    C, W = [], []                       # C: (dist,node)  W: (-dist,node)
    for ep in entry_points:
        d = cosine_distance(query, self.vectors[ep])
        heapq.heappush(C, (d, ep))
        heapq.heappush(W, (-d, ep))

    while C:
        c_dist, c = heapq.heappop(C)    # 取候选中最近的
        if c_dist > -W[0][0]:           # 比结果集最远的还远 -> 停
            break
        for nb in self.layers[layer].get(c, []):
            if nb in visited:
                continue
            visited.add(nb)
            d = cosine_distance(query, self.vectors[nb])
            if len(W) < ef or d < -W[0][0]:
                heapq.heappush(C, (d, nb))
                heapq.heappush(W, (-d, nb))
                if len(W) > ef:
                    heapq.heappop(W)    # 丢弃最远，保持 ef 上限
    return sorted((-neg, node) for neg, node in W)
```

> 这里有个关键点：`ef` 通过 `W` 的容量上限控制搜索范围。`ef` 小时 `W` 很快填满、最远边界更近、终止更早 → 搜得少、快但召回低；`ef` 大时则相反。这正是 `ef_search` 起作用的机制。

### 5.3 插入：从顶层贪心下降，逐层连接

```python
def add(self, vec):
    """插入一个向量：分配层级 -> 顶层贪心下降定位 -> 逐层选邻居并双向连接。"""
    node_id = self._next_id
    self._next_id += 1
    self.vectors[node_id] = vec
    level = self._random_level()
    while len(self.layers) <= level:
        self.layers.append({})

    if self.entry_point is None:        # 第一个节点成为入口
        for l in range(level + 1):
            self.layers[l][node_id] = []
        self.entry_point = node_id
        self.max_level = level
        return node_id

    ep = self.entry_point
    # 1) 从最高层贪心下降到 level+1 层：只定位、不连接（长距离跳）
    for l in range(self.max_level, level, -1):
        ep = self._greedy_descend(vec, ep, layer=l)
    # 2) 在 min(level, max_level) ~ 0 层：选 M 个邻居并双向连接
    for l in range(min(level, self.max_level), -1, -1):
        neighbors = self._select_neighbors(vec, ep, self.M, layer=l)
        self.layers[l][node_id] = list(neighbors)
        for nb in neighbors:
            self.layers[l].setdefault(nb, []).append(node_id)
            self._prune(nb, l)          # 邻居数超过 M 则修剪
        if neighbors:
            ep = neighbors[0]           # 下一层从最近邻居继续搜
    # 3) 新节点层级更高 -> 它成为新的全局入口（高层稀疏孤立点）
    if level > self.max_level:
        for l in range(self.max_level + 1, level + 1):
            self.layers[l][node_id] = []
        self.max_level = level
        self.entry_point = node_id
    return node_id
```

### 5.4 查询：顶层 ef=1 下降，第 0 层 ef_search 精搜

```python
def search(self, query, top_k=10):
    """查询 top_k：顶层用 ef=1 快速定位，第 0 层用 ef_search 精搜。"""
    if self.entry_point is None:
        return []
    ep = self.entry_point
    for l in range(self.max_level, 0, -1):       # 顶层快速下降
        ep = self._greedy_descend(query, ep, layer=l)
    ef = max(self.ef_search, top_k)              # ef_search 必须 >= top_k
    results = self._search_layer(query, [ep], ef=ef, layer=0)
    results.sort()
    return [(n, d) for d, n in results[:top_k]]
```

> **教学版简化说明**：邻居选择用的是"取距离最近的 M 个"（论文里更优的启发式是"多样性优先"的选邻居策略）；修剪也只按距离保留最近 M 个。这些简化会让召回比工业级 hnswlib 低，但足以体现分层贪心搜索的思想。

---

## 六、参数调优实验设计

### 6.1 实验思路

固定一个数据集，扫 `M ∈ {8, 16, 32}` × `ef_search ∈ {50, 100, 200}`，对每个组合测量 **Recall@10**（对比暴力搜索的 ground truth）和**平均查询延迟**。`ef_construction` 固定为 200。

```python
def tune_experiment(n=2000, dim=32, n_queries=30):
    """扫描 M × ef_search，测召回率与延迟。"""
    data = build_dataset(n=n, dim=dim)           # 连续分布数据
    queries = data[:n_queries]
    print(f"{'M':>4} {'ef':>5} {'召回率':>8} {'延迟(ms)':>10} {'建索引(s)':>10}")
    for M in [8, 16, 32]:
        index = HNSWIndex(dim=dim, M=M, ef_construction=200)
        t0 = time.time()
        for vec in data:
            index.add(vec)
        build_s = time.time() - t0
        for ef in [50, 100, 200]:
            index.ef_search = ef
            recalls, lats = [], []
            for q in queries:
                gt = brute_force_topk(data, q, top_k=10)   # 暴力搜索 ground truth
                t0 = time.time()
                hits = index.search(q, top_k=10)
                lats.append((time.time() - t0) * 1000)
                retrieved = {nid for nid, _ in hits}
                recalls.append(recall_at_k(retrieved, gt))
            print(f"{M:>4} {ef:>5} {np.mean(recalls):>8.3f} "
                  f"{np.mean(lats):>10.2f} {build_s:>10.2f}")
```

### 6.2 实测结果（教学版，n=2000, dim=32 连续分布，ef_construction=200）

```
   M    ef      召回率     延迟(ms)     建索引(s)
---------------------------------------------
   8    50    0.957       1.39       7.49
   8   100    0.980       2.41       7.49
   8   200    0.990       4.16       7.49
  16    50    1.000       2.43      10.60
  16   100    1.000       4.77      10.60
  16   200    1.000       6.53      10.60
  32    50    1.000       3.59      17.16
  32   100    1.000       5.41      17.16
  32   200    1.000       7.02      17.16
```

**能读出的三条规律**：

1. **M 调大 → 召回提升、但建索引变慢、查询延迟上升**。最明显的是 M=8 ef=50 召回只有 0.957，升到 M=16 同样 ef=50 就到 1.000；代价是建索引时间从 7.49s 涨到 10.60s（M=32 更是 17.16s），内存也线性增大。
2. **ef_search 调大 → 召回提升或持平、查询延迟线性上升**。M=8 时召回从 0.957→0.980→0.990 稳步提升，延迟也从 1.39→2.41→4.16ms 近似翻倍；M=16/32 召回已满 1.000，ef 主要表现为"延迟换不来更多召回"的浪费。它是召回与延迟的主要"交易旋钮"。
3. **边际递减**：`M=16, ef=50` 已经 1.000，再往上调收益几乎为零、成本却持续涨。**调优的目标不是召回 1.00，而是"用最低成本达到业务可接受的召回"**（比如 Recall@10 ≥ 0.95）。本例里 `M=8, ef=100`（0.980 / 2.41ms）就是性价比很高的组合。

> **与工业级的差距**：教学版在 2000 条小数据上召回也能到 1.000，趋势完全对。真正的差距在两点：一是**延迟**——C++ 实现的 hnswlib 同样参数下延迟是微秒级，比这个 Python 版快 1-2 个数量级；二是**扩展性**——数据量上到百万级后，教学版的简化邻居选择/修剪策略会让召回明显掉下来，而工业级仍稳定。所以理解原理用教学版，上线直接用 Chroma/Milvus/Qdrant 内置的 HNSW。

---

## 动手实验

### 🟢 青铜级：跑通 `hnsw_demo.py`

直接 `python hnsw_demo.py`，观察 `M × ef_search` 扫描表，确认你能读出上面三条规律。把输出贴到笔记里。

### 🟡 白银级：画召回-延迟曲线

把 `tune_experiment` 返回的结果画成两张图：(1) 固定 M，横轴 ef_search、纵轴召回；(2) 横轴延迟、纵轴召回（Pareto 前沿）。找出"性价比最高"的参数组合。

### 🔴 王者级：对比教学版与工业级

用 `pip install hnswlib`，在相同数据集上跑官方 HNSW，对比教学版和工业版在相同参数下的召回与延迟差距，思考：教学版哪里简化导致了这个差距？（提示：邻居选择策略、第 0 层 `2M` 连接、距离计算向量化）

---

## 踩坑记录 🕳️

### 坑 1：ef_search 设得比 top_k 还小

```python
# 想要 top_k=10，却设 ef_search=5
index.ef_search = 5
hits = index.search(query, top_k=10)   # 结果不足 10 条，甚至报错
```

**解决**：`ef_search` 必须 `>= top_k`，代码里用 `ef = max(self.ef_search, top_k)` 兜底。Chroma / Qdrant 也会强制这一约束。

### 坑 2：用强聚类数据做调优实验，ef 看不出差异

最初我用"20 个簇心 + 高斯噪声"造数据，结果 ef_search 从 50 调到 200 召回率纹丝不动。因为强聚类数据里，贪心搜索一旦进入正确簇就能找全近邻，ef 大小没区别。

**解决**：改用**连续分布**（均匀随机）数据，最近邻分散在空间中，ef 的调优才有区分度。真实 ANN benchmark（SIFT/GIST）都是连续分布，这也是为什么业界调参经验在连续数据上才成立。

### 坑 3：ef_construction 调小后，靠 ef_search 补不回来

为了建索引快，把 `ef_construction` 从 200 降到 50，心想"查询时 ef_search 调大点就行"。结果召回率怎么都上不去——因为建索引时邻居选得差，图本身的质量就烂了。

**解决**：`ef_construction` 是一次性投资，宁可建得慢点也要给够（200+）。它决定的索引质量是"上限"，`ef_search` 只能在这个上限内调节，无法突破。

### 坑 4：M 设太大导致内存爆炸

某次把 M 设成 128 想追求极致召回，结果百万级数据内存直接翻几倍，建索引也慢得不可接受。

**解决**：M 的收益边际递减明显。`M=16` 已经是甜点，`M=32` 用于高维/高召回场景，再大基本是浪费内存。第 0 层连接数通常是 `2M`，M 翻倍意味着第 0 层边数接近翻倍。

### 坑 5：教学版用 list 模拟优先队列，ef 失效

第一版 `_search_layer` 用 `list.sort()` 模拟堆，且没有严格维护结果集的 ef 上限，导致 ef_search 几乎不影响结果——搜索会把整个连通区域遍历完。

**解决**：改用 `heapq`，候选集用 min-heap、结果集用 max-heap（负距离）严格维护 ef 上限，终止条件用"候选最近 > 结果最远"。这和 HNSW 论文 Algorithm 2 一致，ef 才真正起作用。

---

## 副线笔记：个人知识库目录结构设计

今天主线讲 HNSW 的"分层索引"，副线正好类比到**个人知识库的目录结构**——一个好的目录结构，本质上就是给文档建了一棵"分层索引树"，检索时从粗到细，和 HNSW 从顶层向第 0 层贪心下降是同一个思想。

### 设计原则：领域 / 类型 / 时间 三维组织

```
knowledge-base/
├── 00-领域/                      ← 顶层 = HNSW 高层：粗分类，长距离跳
│   ├── ai-agent/                 ← 领域
│   │   ├── concepts/             ← 类型（概念/笔记）
│   │   ├── code/                 ← 类型（代码片段）
│   │   └── projects/             ← 类型（项目实战）
│   │       └── 2025-06/          ← 时间（按月归档）
│   ├── backend/
│   └── devops/
├── 01-每日/                      ← 按时间组织的流水笔记
│   └── 2025/
│       └── 06/
│           └── week05-day02.md
└── 99-归档/
```

### 为什么"好的目录结构本身就是索引"

| HNSW 分层 | 知识库目录 |
|----------|-----------|
| 顶层稀疏，长距离跳 | 顶层是"领域"大类，一眼定位到 ai-agent / backend |
| 中层中等密度 | 中层是"类型"（概念/代码/项目），收窄到具体形态 |
| 第 0 层稠密，精确定位 | 叶子是具体文件 + 时间，精确定位到某一篇 |
| 从顶层贪心向下 | 检索时从领域 → 类型 → 时间，逐层缩小 |

**关键洞察**：HNSW 之所以快，是因为分层让"长距离导航"和"精确定位"解耦。知识库也一样——如果目录只有一层、几百个文件平铺，找东西就要全扫（O(N)，相当于暴力搜索）；分了三层后，每层只在小范围里选，定位就变成 O(log N)。

### 实操建议

1. **顶层不超过 7 个大类**（米勒数字），否则"粗分类"就不粗了，失去索引意义。
2. **类型维度要稳定**（概念/代码/项目/归档），时间维度是辅助。频繁变动的分类体系等于没有索引。
3. **文件名自带元信息**：`week05-day02-hnsw.md` 比 `笔记1.md` 强百倍——文件名是第 0 层的"边"，命名好等于图连得好。
4. **配合 CLAUDE.md 的 `@` 引用**（明天 Day 03 内容）：目录是给人和 Agent 共用的索引，`@` 引用就是跨文件的"长距离边"。

> 一个反例：把所有 markdown 倒进一个 `notes/` 目录，靠全文搜索找东西——这等于放弃了目录这层索引，每次检索都退化为暴力搜索。能用，但慢，且容易漏。

---

## 今日产出检查清单

- [ ] 能用自己的话讲清 NSW 的两个缺陷和 HNSW 分层如何解决
- [ ] 说出 M / ef_construction / ef_search 各自影响什么、推荐范围、哪个能在线调
- [ ] 跑通 `hnsw_demo.py`，拿到 `M × ef_search` 扫描表
- [ ] 从实验结果里读出"调大 ef_search 召回升但延迟升"的趋势
- [ ] 理解教学版与工业级 hnswlib 的差距来源（邻居选择 / 修剪 / 向量化距离）
- [ ] 为自己的知识库设计一套 领域/类型/时间 三层目录结构

---

> **下一课预告：Day 03 — Chroma 深入：集合 / 元数据 / 持久化**。今天我们手写了 HNSW 摸清了底层，明天回到工程实践——把 Week 04 用过的 Chroma 用到极致：多集合管理、元数据过滤、批量写入性能、持久化与迁移，并配合 CLAUDE.md 的 `@` 多文件引用，让 Agent 也能跨文件"分层检索"你的知识库。
