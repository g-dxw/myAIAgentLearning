# Day 01 — 向量数据库原理 + ANN 索引算法

## 学习目标

Week 04 我们把 Chroma 当黑盒用过：`add` 塞向量、`query` 查相似、`delete` 删数据，调一下就出结果。但你有没有想过：百万级向量，它凭什么能在毫秒级返回 top-k？今天拆开黑盒，从「暴力搜索为什么慢」讲起，一路讲到 ANN（近似最近邻）的思想和三大索引算法族，最后用 numpy 手写一个简易 IVF，亲眼看「召回率 vs 速度」的取舍。

学完今天你能：
1. 说清楚暴力 KNN 的 O(n×d) 复杂度为什么在百万级数据上不可用
2. 解释 ANN 的核心取舍「用一点点精度换巨大速度」，并讲清召回率 Recall@k 的定义
3. 说出 IVF / HNSW / PQ 三大索引算法族的原理、召回率、内存、适用规模差异
4. 用 numpy 手写一个简易 IVF（KMeans 聚类 → 倒排 → 只搜 top-nprobe 个桶），并对比暴力搜索的召回率和速度

---

## 一、为什么不能暴力搜索：精确最近邻 KNN

### 1.1 什么是精确最近邻

给你一个查询向量 q 和一个含 n 个 d 维向量的库，要找最相似的 k 个——最朴素的做法就是**把 q 跟库里每个向量都算一遍距离，再排序取前 k**。这叫精确最近邻（Exact / Brute-force KNN），结果是 100% 正确的 ground truth。

```python
import numpy as np


def brute_search(query: np.ndarray, vectors: np.ndarray, top_k: int = 5) -> np.ndarray:
    """
    暴力搜索：计算 query 与所有向量的欧氏距离，返回 top_k 的索引。

    复杂度：O(n × d)，n 是向量数，d 是维度。
    query: (d,)  vectors: (n, d)
    """
    # 广播计算 query 到每个向量的欧氏距离
    diff = vectors - query                       # (n, d)
    dists = np.sqrt(np.sum(diff * diff, axis=1))  # (n,)
    # argpartition 比全排序快，适合只取 top-k
    top_idx = np.argpartition(dists, top_k)[:top_k]
    # 在 top_k 内部按距离升序排
    top_idx = top_idx[np.argsort(dists[top_idx])]
    return top_idx
```

### 1.2 复杂度问题

每次查询都要算 n 个 d 维向量的距离，复杂度是 **O(n × d)**。听起来还好？我们算笔账：

| 数据规模 n | 维度 d | 单次查询浮点运算量 | 单次查询耗时（估算） |
|-----------|--------|-------------------|---------------------|
| 1 万 | 768 | 7.68M | ~0.3 ms |
| 10 万 | 768 | 76.8M | ~3 ms |
| 100 万 | 768 | 768M | ~30 ms |
| 1000 万 | 768 | 7.68B | ~300 ms |
| 1 亿 | 768 | 76.8B | ~3 s |

> **直觉类比：** 在 1 亿本书里找最相关的 5 本，逐本翻一遍要 3 秒——用户根本等不了。真实场景里 RAG 知识库动辄百万级 chunk，暴力搜索直接劝退。这就是向量数据库存在的根本原因——它不能用暴力搜索。

### 1.3 实测：暴力搜索随规模线性增长

```python
import time


def benchmark_brute(n_list, d=768, top_k=5, repeat=10):
    """对不同规模 n 测暴力搜索平均耗时，验证 O(n) 线性增长。"""
    for n in n_list:
        vectors = np.random.randn(n, d).astype(np.float32)
        query = np.random.randn(d).astype(np.float32)
        _ = brute_search(query, vectors, top_k)  # 预热缓存
        t0 = time.perf_counter()
        for _ in range(repeat):
            brute_search(query, vectors, top_k)
        avg_ms = (time.perf_counter() - t0) / repeat * 1000
        print(f"n={n:>8,}  d={d}  平均耗时 {avg_ms:7.2f} ms")


if __name__ == "__main__":
    benchmark_brute([10_000, 100_000, 1_000_000])
```

跑下来你会发现：n 从 1 万涨到 100 万，耗时线性涨 100 倍。**线性复杂度在小数据上没感觉，一到百万级就原形毕露。**

---

## 二、ANN 近似最近邻：用精度换速度

### 2.1 核心思想：别全搜，只搜"有希望"的

暴力搜索慢，是因为它把每个向量都算了一遍。但仔细想：top-k 结果几乎肯定分布在查询点附近的某个区域，离查询点很远的向量根本不可能进 top-k——**算它们纯属浪费**。

ANN（Approximate Nearest Neighbor，近似最近邻）的核心思想就是：**先快速排除掉绝大多数不可能的向量，只在一小部分"候选"里精确计算。** 用一点点精度（漏掉极少数真近邻）换巨大的速度提升。

### 2.2 精确 vs 近似的取舍

| 维度 | 精确 KNN（暴力） | ANN（近似） |
|------|-----------------|------------|
| 结果正确性 | 100% 正确 | 大部分正确，可能漏几个 |
| 复杂度 | O(n × d) | O(log n × d) ~ O(√n × d) |
| 百万级查询耗时 | ~30 ms | ~0.5–2 ms |
| 内存 | 存原始向量即可 | 额外索引结构（图/倒排表/码本） |
| 适用场景 | 数据小、要绝对准 | 生产级语义搜索、推荐 |

### 2.3 召回率 Recall：衡量 ANN 好不好的核心指标

ANN 不保证 100% 正确，那怎么评价它好不好？用**召回率 Recall**：

```
Recall@k = | ANN 返回的 top-k  ∩  真实 top-k | / k
```

即：ANN 返回的 k 个结果里，有几个是真实 top-k。比如真实 top-10 是 {A,B,C,D,E,F,G,H,I,J}，ANN 返回了 {A,B,C,D,E,F,G,H,K,L}，其中前 8 个命中，那么 `Recall@10 = 8/10 = 0.8`。

| Recall | 含义 | 评价 |
|--------|------|------|
| 1.0 | 完全命中 | 和暴力搜索一样准（那就没必要用 ANN 了） |
| 0.95+ | 几乎全中 | 生产可用，RAG 场景一般要求 ≥0.95 |
| 0.8~0.9 | 漏一些 | 速度更快，看场景取舍 |
| <0.8 | 漏得多 | 通常不可接受，需调参或换算法 |

> **关键认知：** 在 RAG 场景，召回率 0.95 和 1.0 用户几乎无感知差异（反正后面还有 LLM 生成 + Re-rank），但 0.95 的查询速度快十倍。这就是 ANN 价值所在——**用感知不到的精度损失换巨大的性能**。

---

## 三、三大索引算法族：IVF / HNSW / PQ

主流向量数据库（Chroma / Milvus / Qdrant / Pinecone / FAISS）底层索引几乎都来自这三大家族。

### 3.1 IVF：倒排文件（Inverted File）

**思想：** 先用 KMeans 把所有向量聚成 `nlist` 个簇，每个簇有一个聚类中心。查询时，先算 query 到所有中心的距离，只挑最近的 `nprobe` 个簇，再在这几个簇里做暴力搜索。

```
建库阶段：
  1. KMeans 聚类 → 得到 nlist 个中心
  2. 每个向量归到最近的中心 → 形成 nlist 个倒排桶（每桶存该簇的向量 ID）

查询阶段：
  1. query vs nlist 个中心 → 选最近的 nprobe 个桶
  2. 只在这 nprobe 个桶里暴力搜 top-k
```

| 参数 | 含义 | 调大 | 调小 |
|------|------|------|------|
| `nlist` | 聚类中心数（桶数） | 桶更细、每桶向量少、查询快；但建库慢 | 桶粗、每桶向量多、查询慢 |
| `nprobe` | 查询时搜几个桶 | 召回高、查询慢 | 召回低、查询快 |

经验值：`nlist ≈ 4~16 × √n`，`nprobe ≈ nlist × 1%~10%`。这就是「召回 vs 速度」最直接的旋钮。

### 3.2 HNSW：分层可导航小世界图（Hierarchical Navigable Small World）

**思想：** 把向量组织成一张多层图。最上层稀疏（少数节点、长距离边，负责快速跨区域跳），最下层稠密（所有节点、短距离边，负责精确定位）。查询时从顶层入口节点贪心跳到 query 附近，逐层往下细化。

```
Layer 2 (最稀疏):  ●─────────────●──────────────●        ← 长距离边，快速跨区域
Layer 1:           ●─────●────●───────●─────●              ← 中等密度
Layer 0 (最稠密):  ●─●─●─●─●─●─●─●─●─●─●─●─●─●            ← 所有节点，精确定位
```

HNSW 是目前综合性能最好的算法（高召回 + 快查询），Chroma / Qdrant 默认就用它。Day 02 会深入讲它的 `M`、`ef_construction`、`ef_search` 参数，今天先有个思想层面的认识。

### 3.3 PQ：乘积量化（Product Quantization）

**思想：** 把高维向量切成 `m` 段，每段独立做 KMeans 量化成 `2^bits` 个码字。原始 d 维浮点向量被压缩成 m 个 8-bit 整数（码本索引），内存压缩 8~32 倍。

```
原始向量 (d=768, float32, 3072 字节)
   ↓ 切成 m=8 段，每段 96 维
段1 段2 段3 段4 段5 段6 段7 段8
 ↓   ↓   ↓   ↓   ↓   ↓   ↓   ↓     每段独立 KMeans (256 个码字)
码  码  码  码  码  码  码  码      每段存 1 byte 码本索引
   ↓
压缩向量 (m=8, uint8, 8 字节)       压缩比 384×
```

PQ 通常和 IVF 组合成 **IVF-PQ**：先用 IVF 选桶（粗量化），再在桶内用 PQ 压缩向量做距离近似（细量化）。这样既快又省内存，适合亿级数据。

### 3.4 三大算法对比

| 算法 | 原理 | 召回率 | 内存 | 查询速度 | 适用规模 |
|------|------|--------|------|----------|----------|
| **IVF** | 聚类倒排，只搜 nprobe 个桶 | 中高（0.9~0.98） | 中（存原始向量+倒排表） | 快 | 百万~千万 |
| **HNSW** | 多层图贪心导航 | 高（0.95~0.99） | 高（存图边） | 很快 | 百万~亿 |
| **PQ** | 分段量化压缩 | 中（0.85~0.95） | 极低（压缩 8~32×） | 很快 | 亿~十亿 |
| **IVF-PQ** | IVF 粗量化 + PQ 细量化 | 中高（0.9~0.97） | 极低 | 快 | 亿~十亿 |

> **选型直觉：** 数据 < 千万、要最高召回 → HNSW；数据上亿、内存吃紧 → IVF-PQ；想要简单可控、中等规模 → IVF。生产库一般让 HNSW 和 IVF-PQ 二选一。

---

## 四、距离度量深入：余弦 / L2 / 点积

### 4.1 三种距离的数学定义

给定两个 d 维向量 A=(a₁,...,a_d) 和 B=(b₁,...,b_d)：

**余弦相似度（Cosine Similarity）**——只看方向：
```
cos(A, B) = (A · B) / (‖A‖ × ‖B‖)   ∈ [-1, 1]
```

**欧氏距离（L2 Distance）**——看绝对位置：
```
L2(A, B) = √( Σ (aᵢ - bᵢ)² )        ∈ [0, +∞)
```

**点积 / 内积（Inner Product）**——同时看方向和模长：
```
IP(A, B) = Σ aᵢ × bᵢ                ∈ (-∞, +∞)
```

### 4.2 一个关键等价：归一化后 L2 和余弦等价

如果把向量都归一化到单位长度（‖A‖=‖B‖=1），那么：
```
L2(A, B)² = ‖A‖² + ‖B‖² - 2(A·B) = 2 - 2(A·B) = 2 - 2·cos(A, B)
```
即 **归一化后，L2 最小 ⇔ 余弦最大 ⇔ 点积最大**，三者排序结果完全一致。所以很多库（包括 Chroma）内部对归一化向量用 L2 索引，等价于做余弦相似度——既省了归一化计算又快。

### 4.3 三种度量对比

| 度量 | 关注 | 是否归一化敏感 | 值域 | 典型场景 |
|------|------|----------------|------|----------|
| 余弦相似度 | 方向（语义取向） | 否（自带归一化） | [-1, 1] | 文本语义搜索、RAG |
| 欧氏距离 L2 | 绝对位置 | 是 | [0, ∞) | 图像匹配、地理位置 |
| 点积 IP | 方向 + 模长 | 是 | (-∞, ∞) | 推荐系统、最大边际排序 |

### 4.4 什么时候用哪个

```python
def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度：语义搜索首选，对向量长度不敏感。"""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def l2_dist(a: np.ndarray, b: np.ndarray) -> float:
    """欧氏距离：关心绝对位置时用，如图像/坐标。"""
    return float(np.sqrt(np.sum((a - b) ** 2)))


def inner_product(a: np.ndarray, b: np.ndarray) -> float:
    """内积/点积：向量已归一化时等价余弦；推荐系统常用（模长含信息）。"""
    return float(np.dot(a, b))
```

| 你的场景 | 推荐度量 | 理由 |
|----------|----------|------|
| RAG / 文本语义搜索 | 余弦 | 文本长度不影响语义，归一化更稳 |
| 图像以图搜图 | L2 | 像素绝对差异有意义 |
| 推荐系统（用户/物品向量） | 点积 | 向量模长编码"热门度/活跃度" |
| 向量已 L2 归一化 | 三者等价，用 L2 最快 | 库内部索引优化 |

> **坑提醒：** 混用度量是新人最常翻的车——入库用余弦、查询用 L2，结果全错。**入库和查询必须用同一种度量，且整个库统一。**

---

## 五、用 numpy 手写一个简易 IVF

光讲原理不直观，我们用 numpy 从零搓一个 IVF，亲眼看「聚类 → 倒排 → 只搜 nprobe 个桶」全过程，并和暴力搜索对比召回率与速度。完整可运行版本见今日产出 `ann_benchmark.py`。

### 5.1 建库：KMeans 聚类 + 倒排

```python
import numpy as np


class SimpleIVF:
    """用 numpy 手写的简易 IVF 索引，演示原理用（非生产级）。"""

    def __init__(self, nlist: int = 100, seed: int = 1234):
        self.nlist = nlist
        self.seed = seed
        self.centroids = None       # (nlist, d) 聚类中心
        self.inverted_lists = None  # {簇ID: 向量索引数组} 倒排桶

    def _kmeans(self, vectors: np.ndarray, k: int, iters: int = 20):
        """简易 KMeans：随机初始化中心 → 反复分配 + 更新中心（固定种子可复现）。"""
        rng = np.random.default_rng(self.seed)
        n = vectors.shape[0]
        idx = rng.choice(n, k, replace=False)
        centroids = vectors[idx].copy()
        for _ in range(iters):
            # 分配：用 ‖x-c‖² = ‖x‖²+‖c‖²-2x·c 简化，避免开方
            dists = (np.sum(vectors ** 2, axis=1, keepdims=True)
                     + np.sum(centroids ** 2, axis=1)
                     - 2 * vectors @ centroids.T)
            assign = np.argmin(dists, axis=1)
            # 更新中心（空簇保留旧中心）
            for j in range(k):
                if np.any(assign == j):
                    centroids[j] = vectors[assign == j].mean(axis=0)
        # 最终分配
        dists = (np.sum(vectors ** 2, axis=1, keepdims=True)
                 + np.sum(centroids ** 2, axis=1)
                 - 2 * vectors @ centroids.T)
        return centroids, np.argmin(dists, axis=1)

    def build(self, vectors: np.ndarray):
        """建库：聚类 + 构造倒排桶。"""
        k = min(self.nlist, vectors.shape[0])
        self.centroids, assign = self._kmeans(vectors, k)
        self.inverted_lists = {j: np.where(assign == j)[0] for j in range(k)}

    def search(self, query: np.ndarray, vectors: np.ndarray,
               top_k: int = 5, nprobe: int = 8) -> np.ndarray:
        """查询：先选 nprobe 个最近桶，再在桶内暴力搜 top_k。"""
        # 1. query vs 所有中心 → 选最近的 nprobe 个桶
        c_dist = np.sum((self.centroids - query) ** 2, axis=1)
        nprobe = min(nprobe, len(self.inverted_lists))
        probe_buckets = np.argpartition(c_dist, nprobe - 1)[:nprobe]
        # 2. 收集候选向量（只在这几个桶里）
        cand_idx = np.concatenate([self.inverted_lists[b] for b in probe_buckets])
        cand_vecs = vectors[cand_idx]
        # 3. 候选集内暴力搜 top_k
        d = np.sum((cand_vecs - query) ** 2, axis=1)
        k = min(top_k, len(cand_idx))
        local_top = np.argpartition(d, k - 1)[:k]
        return cand_idx[local_top[np.argsort(d[local_top])]]
```

### 5.2 对比：召回率 + 速度

```python
def recall_at_k(ann_result: np.ndarray, gt_result: np.ndarray, k: int) -> float:
    """计算 Recall@k：ANN 结果与真实 top-k 的交集占比。"""
    return len(set(ann_result.tolist()) & set(gt_result.tolist())) / k


def make_clustered_data(n, d, n_clusters, sigma=0.3, seed=42):
    """生成有簇结构的数据：n_clusters 个中心，向量 = 中心 + 高斯噪声。"""
    rng = np.random.default_rng(seed)
    centers = rng.standard_normal((n_clusters, d)).astype(np.float32)
    assign = rng.integers(0, n_clusters, size=n)
    return (centers[assign] + sigma * rng.standard_normal((n, d))).astype(np.float32)


def run_benchmark(n: int = 100_000, d: int = 128, top_k: int = 10,
                  nlist: int = 100, sigma: float = 0.3):
    """对比暴力搜索 vs IVF：速度 + 召回率。"""
    # 数据库用有簇结构数据；查询用随机点（真实近邻跨多簇，nprobe 才有渐变）
    vectors = make_clustered_data(n, d, nlist, sigma)
    queries = np.random.default_rng(7).standard_normal((100, d)).astype(np.float32)

    ivf = SimpleIVF(nlist=nlist)
    ivf.build(vectors)

    import time
    # 暴力搜索（ground truth）
    t0 = time.perf_counter()
    gt = [brute_search(q, vectors, top_k) for q in queries]
    brute_ms = (time.perf_counter() - t0) / len(queries) * 1000

    # IVF 搜索（不同 nprobe）
    for nprobe in [1, 5, 10, 20, 50]:
        recalls, t0 = [], time.perf_counter()
        for i, q in enumerate(queries):
            ann = ivf.search(q, vectors, top_k, nprobe)
            recalls.append(recall_at_k(ann, gt[i], top_k))
        ivf_ms = (time.perf_counter() - t0) / len(queries) * 1000
        print(f"nprobe={nprobe:>2}  召回率={np.mean(recalls):.3f}  "
              f"耗时={ivf_ms:6.2f}ms  加速={brute_ms / ivf_ms:.1f}x")

    print(f"\n暴力搜索（ground truth）  耗时={brute_ms:6.2f}ms  召回率=1.000")
```

典型输出（n=10万, d=128, nlist=100, sigma=0.3）：

```
nprobe= 1  召回率=0.377  耗时=  4.76ms  加速= 8.3x
nprobe= 5  召回率=0.727  耗时= 12.73ms  加速= 3.1x
nprobe=10  召回率=0.922  耗时= 18.83ms  加速= 2.1x
nprobe=20  召回率=1.000  耗时= 24.87ms  加速= 1.6x
nprobe=50  召回率=1.000  耗时= 39.76ms  加速= 1.0x

暴力搜索（ground truth）  耗时= 39.50ms  召回率=1.000
```

看这张表就懂 ANN 的精髓了：`nprobe` 从 1 涨到 50，召回率从 0.38 涨到 1.0，加速比从 8.3× 降到 1.0×——**召回和速度是一条斜线，nprobe 就是你在斜线上选的点**。RAG 场景通常选 `nprobe=10` 附近，召回约 0.92、加速约 2 倍；想更稳就提到 `nprobe=20`（召回 1.0）。注意 `nprobe=50` 时几乎搜了半个库，加速比降到 1.0×，退化为暴力搜索——这正是后面「坑 1」的现场。这里加速比只有几倍，是因为 n=10万、暴力本身才 ~40ms；数据量越大（百万级），加速比越能到 10× 以上。

---

## 动手实验

### 🟢 青铜级：跑通 ann_benchmark.py

把今日产出 `ann_benchmark.py` 跑起来，观察不同 `nprobe` 下召回率和速度的变化曲线，理解「召回 vs 速度」的取舍。

```bash
python week05/ann_benchmark.py
```

### 🟡 白银级：调参对比

修改 `ann_benchmark.py` 里的 `nlist`（比如 50 / 200 / 500）和 `nprobe`，记录「nlist × nprobe → 召回率 + 速度」表格，找出 n=10万 数据下的甜点参数组合。

### 🔴 王者级：距离度量切换 + Recall 曲线

1. 把暴力搜索的 ground truth 换成余弦相似度（先对向量 L2 归一化），让 IVF 也按余弦检索，验证「归一化后 L2 ⇔ 余弦」的等价性。
2. 用 matplotlib 画出 Recall@10 和查询耗时随 `nprobe` 变化的双轴曲线，直观看到「召回上升、速度下降」的权衡拐点。

---

## 踩坑记录 🕳️

### 坑 1：nprobe 设太大，IVF 退化成暴力搜索

`nprobe` 调到等于 `nlist`，意味着搜所有桶 = 全量暴力搜索，ANN 的加速完全消失，还多花了选桶的开销。

**解决：** `nprobe` 一般取 `nlist` 的 1%~10%。先用青铜级实验扫一遍 `nprobe`，挑召回率到 0.95 附近的最小值，这就是性价比最高的点。

### 坑 2：建库和查询用了不同的距离度量

入库用 L2 建索引，查询却按余弦排序，召回率会莫名其妙掉一截甚至结果错乱——因为索引结构和排序标准不一致。

**解决：** 整个库统一一种度量。用余弦就先对所有向量 L2 归一化，再统一用 L2 距离建索引和查询（归一化后两者等价，且 L2 索引更快）。

### 坑 3：KMeans 空簇导致索引崩

数据分布不均或初始中心选得差时，某些簇可能一个向量都没有（空簇），访问空桶会报 `IndexError` 或返回空结果。

**解决：** 手写 KMeans 时对空簇做兜底——保留旧中心，或从最大簇里分裂一个新中心。生产库（FAISS / Milvus）内部已处理，但自己实现时一定要加。

### 坑 4：召回率只看平均值，忽略长尾

平均 Recall@10 = 0.96 看着不错，但可能 90% 的查询召回 1.0、10% 的查询召回 0.4——长尾查询体验很差。

**解决：** 评估时除了看均值，还要看 P50 / P95 / P99 召回率，盯住最差的 5% 查询。RAG 场景尤其怕长尾，用户遇到一次「搜不到」就会怀疑整个系统。

### 坑 5：测试数据用均匀分布，掩盖了真实问题

`np.random.randn` 生成的是高斯分布，聚类效果出奇地好；但真实 Embedding 往往有簇结构、长尾分布，同样参数下召回可能掉很多。

**解决：** 用真实业务 Embedding 做基准测试，别拿随机数据自欺欺人。本地验证可以用随机数据，上线前必须换真实数据复测。

---

## 副线笔记

### CLAUDE.md 进阶：从单文件升级到分层知识库

Week 04 我们提过 Claude Code 会读 `CLAUDE.md` 当「人工指定的检索优先级」。随着项目变大，单文件 `CLAUDE.md` 会塞成大杂烩——FastAPI 约定、前端规范、数据库规则全堆一起，既难维护，Claude 每次还得多读无用内容。

**进阶做法：分层组织。** 项目根放一个全局 `CLAUDE.md` 写通用规则，每个子目录再放各自的 `CLAUDE.md` 写局部约定，Claude Code 会**就近读取**——处理某目录的文件时，自动把从根到该目录路径上所有 `CLAUDE.md` 合并进上下文。

```
myAIAgentLearning/
├── CLAUDE.md                  # 全局：项目概述、通用编码规范、Git 约定
├── week04/
│   ├── CLAUDE.md              # 局部：RAG 模块约定、Chroma 用法、splitter 规则
│   └── homework/
│       └── CLAUDE.md          # 更局部：这个 homework 的 API 响应格式、路由前缀
└── week05/
    ├── CLAUDE.md              # 局部：向量库模块约定、索引默认 HNSW、距离度量统一用余弦
    └── ann_benchmark.py
```

### 各层该写什么

| 层级 | 位置 | 写什么 | 示例 |
|------|------|--------|------|
| 全局 | 项目根 `CLAUDE.md` | 项目概述、技术栈、通用规范、跨模块约定 | "Python 3.11，用 ruff 格式化；统一 APIResponse 响应" |
| 模块 | 子目录 `CLAUDE.md` | 该模块的领域规则、依赖、注意事项 | "week05 所有向量统一 L2 归一化 + 余弦度量" |
| 子模块 | 更深目录 `CLAUDE.md` | 极局部的实现约定 | "homework 的路由前缀统一 /api/v1" |

### 分层组织的好处

1. **就近原则：** Claude 处理 `week05/ann_benchmark.py` 时自动带上 `week05/CLAUDE.md`，不用你手动 `@` 引用，上下文精准又不冗余。
2. **职责隔离：** 前端规则不污染后端目录，每个 `CLAUDE.md` 只管自己那层，单文件不会膨胀失控。
3. **可演进：** 新加一个模块就新建它的 `CLAUDE.md`，老模块规则不受影响；删除模块连同规则一起清理，干净利落。
4. **团队协作友好：** 不同人负责不同模块时，各改各的 `CLAUDE.md`，减少冲突。

> **今日观察任务：** 给你的 `week05/` 目录新建一个 `CLAUDE.md`，写上「本周所有向量统一用余弦相似度、索引默认 HNSW、`ann_benchmark.py` 跑通后结果记进 README」。然后让 Claude Code 在 week05 下干活，看它是不是自动遵守了你写的局部规则。

---

## 今日产出检查清单

- [ ] 能说出暴力 KNN 的 O(n×d) 复杂度，以及百万级数据为什么不可用
- [ ] 能解释 ANN「用精度换速度」的取舍，并能定义召回率 Recall@k
- [ ] 能说清 IVF / HNSW / PQ 三大算法族的原理与适用规模差异
- [ ] 能区分余弦 / L2 / 点积三种度量，知道 RAG 该用哪个、为什么归一化后三者等价
- [ ] 跑通了 `ann_benchmark.py`，看到不同 `nprobe` 下召回率与速度的权衡
- [ ] 给 `week05/` 新建了分层 `CLAUDE.md`，并验证 Claude Code 就近读取生效

---

> **下一课预告：Day 02 — HNSW 算法深入 + 参数调优**。今天只讲了 HNSW 的思想，明天我们钻进它的多层图结构，动手调 `M` / `ef_construction` / `ef_search` 三个核心参数，用可视化看「图是怎么长出来的、参数怎么影响召回与建库速度」。
