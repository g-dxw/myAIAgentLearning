"""
ann_benchmark.py — Week 05 Day 01 产出文件

主题：向量数据库原理 + ANN 索引算法
内容：
  1. 暴力搜索（精确 KNN）随规模线性增长的实测
  2. 手写简易 IVF（KMeans 聚类 → 倒排 → 只搜 top-nprobe 个桶）
  3. 暴力搜索 vs IVF 的召回率 + 速度对比
  4. 距离度量对比（L2 / 余弦 / 点积）+ 归一化后三者等价的验证

运行：
    python week05/ann_benchmark.py

依赖：numpy（matplotlib 为可选，用于王者级画图）
"""

import time
import numpy as np


# =====================================================================
# 一、距离度量
# =====================================================================

def l2_dist(a: np.ndarray, b: np.ndarray) -> float:
    """欧氏距离 L2：关心绝对位置，如图像/坐标。值越小越相似。"""
    return float(np.sqrt(np.sum((a - b) ** 2)))


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度：只看方向，对向量长度不敏感。值越大越相似。"""
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def inner_product(a: np.ndarray, b: np.ndarray) -> float:
    """内积/点积：方向 + 模长。向量已归一化时等价余弦。"""
    return float(np.dot(a, b))


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """对向量做 L2 归一化（缩放到单位长度）。兼容 1-D 单向量和 2-D 批量。"""
    axis = 1 if vectors.ndim == 2 else 0
    norms = np.linalg.norm(vectors, axis=axis, keepdims=True)
    norms[norms == 0] = 1.0  # 零向量兜底，避免除零
    return vectors / norms


# =====================================================================
# 二、暴力搜索（精确 KNN）—— ground truth
# =====================================================================

def brute_search_l2(query: np.ndarray, vectors: np.ndarray, top_k: int = 5) -> np.ndarray:
    """
    暴力搜索（L2 欧氏距离）：计算 query 与所有向量的距离，返回 top_k 索引。

    复杂度：O(n × d)，n 是向量数，d 是维度。
    query: (d,)  vectors: (n, d)
    """
    diff = vectors - query                          # (n, d)
    dists = np.sqrt(np.sum(diff * diff, axis=1))    # (n,) 欧氏距离
    top_idx = np.argpartition(dists, top_k)[:top_k]
    # 在 top_k 内部按距离升序排
    return top_idx[np.argsort(dists[top_idx])]


def brute_search_cosine(query: np.ndarray, vectors: np.ndarray, top_k: int = 5) -> np.ndarray:
    """暴力搜索（余弦相似度）：返回相似度最高的 top_k 索引。"""
    sims = vectors @ query / (
        np.linalg.norm(vectors, axis=1) * np.linalg.norm(query) + 1e-12
    )
    # 取相似度最大的 top_k（argpartition 取最大的 k 个 → 用负号转最小）
    top_idx = np.argpartition(-sims, top_k)[:top_k]
    return top_idx[np.argsort(-sims[top_idx])]


# =====================================================================
# 三、手写简易 IVF（Inverted File）
# =====================================================================

class SimpleIVF:
    """
    用 numpy 手写的简易 IVF 索引，演示原理用（非生产级）。

    建库：KMeans 聚类得到 nlist 个中心 → 每个向量归到最近中心 → 形成倒排桶。
    查询：query vs 所有中心选最近 nprobe 个桶 → 只在这些桶内暴力搜 top_k。
    """

    def __init__(self, nlist: int = 100, seed: int = 1234):
        self.nlist = nlist
        self.seed = seed
        self.centroids = None        # (nlist, d) 聚类中心
        self.inverted_lists = None   # {簇ID: 向量索引数组} 倒排桶

    def _kmeans(self, vectors: np.ndarray, k: int, iters: int = 20):
        """
        简易 KMeans：随机初始化中心 → 反复「分配 + 更新中心」。

        用 ‖x-c‖² = ‖x‖² + ‖c‖² - 2·x·c 简化距离计算，避免开方。
        空簇兜底：保留旧中心，避免后续访问空桶报错。
        用独立 RNG（固定种子）保证建库结果可复现。
        """
        rng = np.random.default_rng(self.seed)
        n = vectors.shape[0]
        idx = rng.choice(n, k, replace=False)
        centroids = vectors[idx].copy()
        for _ in range(iters):
            # 分配：每个向量归到最近的中心
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
        """
        查询：先选 nprobe 个最近桶，再在桶内暴力搜 top_k。

        nprobe 越大 → 召回越高、速度越慢（nprobe=nlist 即退化为暴力搜索）。
        """
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


# =====================================================================
# 四、评估指标
# =====================================================================

def recall_at_k(ann_result: np.ndarray, gt_result: np.ndarray, k: int) -> float:
    """
    计算 Recall@k：ANN 返回结果与真实 top-k 的交集占比。

    Recall@k = | ANN top-k ∩ 真实 top-k | / k
    """
    return len(set(ann_result.tolist()) & set(gt_result.tolist())) / k


def percentile(values: list[float], p: float) -> float:
    """简易分位数：p 取 0~100。用于看长尾（P50/P95/P99）。"""
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(np.ceil(p / 100 * len(s))) - 1
    return float(s[max(idx, 0)])


# =====================================================================
# 五、基准测试
# =====================================================================

def make_clustered_data(n: int, d: int, n_clusters: int, sigma: float = 0.3,
                        seed: int = 42) -> np.ndarray:
    """
    生成有簇结构的数据：n_clusters 个中心，每个向量 = 某中心 + 高斯噪声。

    用簇结构数据而非纯随机高斯，是因为纯高斯在 128 维下受「维度灾难」影响，
    近邻几乎等距，IVF 召回曲线被压缩在低端，看不出 nprobe 的渐变效果。
    有簇结构时，随机查询点的真实近邻会跨多个簇，nprobe 才能体现「召回渐变」。
    """
    rng = np.random.default_rng(seed)
    centers = rng.standard_normal((n_clusters, d)).astype(np.float32)
    assign = rng.integers(0, n_clusters, size=n)
    vectors = centers[assign] + sigma * rng.standard_normal((n, d))
    return vectors.astype(np.float32)


def benchmark_brute(n_list, d=768, top_k=5, repeat=10):
    """对不同规模 n 测暴力搜索平均耗时，验证 O(n) 线性增长。"""
    print("=" * 64)
    print("实验 1：暴力搜索随数据规模线性增长（O(n × d)）")
    print("=" * 64)
    print(f"{'n':>10} {'d':>6} {'平均耗时(ms)':>14}")
    print("-" * 64)
    for n in n_list:
        vectors = np.random.randn(n, d).astype(np.float32)
        query = np.random.randn(d).astype(np.float32)
        _ = brute_search_l2(query, vectors, top_k)  # 预热缓存
        t0 = time.perf_counter()
        for _ in range(repeat):
            brute_search_l2(query, vectors, top_k)
        avg_ms = (time.perf_counter() - t0) / repeat * 1000
        print(f"{n:>10,} {d:>6} {avg_ms:>14.2f}")
    print("→ n 翻 10 倍，耗时也约翻 10 倍，这就是线性复杂度。\n")


def benchmark_ivf(n: int = 100_000, d: int = 128, top_k: int = 10,
                  nlist: int = 100, sigma: float = 0.3, nprobes=None):
    """
    对比暴力搜索 vs IVF：召回率 + 速度 + 长尾（P50/P95/P99）。

    参数：
      n: 向量数；d: 维度；top_k: 取前 k 个近邻
      nlist: 聚类中心数（桶数）；sigma: 簇内噪声标准差
      nprobes: 要扫描的 nprobe 列表
    """
    if nprobes is None:
        nprobes = [1, 5, 10, 20, 50]
    # 数据库用有簇结构的数据（让 IVF 能演示清晰召回曲线）
    vectors = make_clustered_data(n, d, nlist, sigma, seed=42)
    # 查询用随机点（落在簇之间，真实近邻跨多簇，nprobe 才有渐变效果）
    q_rng = np.random.default_rng(7)
    queries = q_rng.standard_normal((100, d)).astype(np.float32)

    print("=" * 64)
    print(f"实验 2：暴力搜索 vs IVF（n={n:,}, d={d}, top_k={top_k}, nlist={nlist}）")
    print("=" * 64)

    # 建库
    t0 = time.perf_counter()
    ivf = SimpleIVF(nlist=nlist)
    ivf.build(vectors)
    print(f"建库耗时: {time.perf_counter() - t0:.2f}s")

    # 暴力搜索（ground truth）
    t0 = time.perf_counter()
    gt = [brute_search_l2(q, vectors, top_k) for q in queries]
    brute_ms = (time.perf_counter() - t0) / len(queries) * 1000

    print(f"\n{'nprobe':>7} {'召回均值':>8} {'P50':>7} {'P95':>7} {'P99':>7} "
          f"{'耗时(ms)':>10} {'加速':>7}")
    print("-" * 64)

    for nprobe in nprobes:
        recalls, t0 = [], time.perf_counter()
        for i, q in enumerate(queries):
            ann = ivf.search(q, vectors, top_k, nprobe)
            recalls.append(recall_at_k(ann, gt[i], top_k))
        ivf_ms = (time.perf_counter() - t0) / len(queries) * 1000
        speedup = brute_ms / ivf_ms if ivf_ms > 0 else float("inf")
        print(f"{nprobe:>7} {np.mean(recalls):>8.3f} "
              f"{percentile(recalls, 50):>7.3f} {percentile(recalls, 95):>7.3f} "
              f"{percentile(recalls, 99):>7.3f} {ivf_ms:>10.2f} {speedup:>6.1f}x")

    print("-" * 64)
    print(f"{'暴力':>7} {'1.000':>8} {'1.000':>7} {'1.000':>7} {'1.000':>7} "
          f"{brute_ms:>10.2f} {'1.0':>7}x")
    print("→ nprobe 越大召回越高但越慢；RAG 场景挑召回≈0.95 的最小 nprobe 性价比最高。\n")


def verify_distance_equivalence(d: int = 128, n: int = 50_000, top_k: int = 10):
    """
    验证「归一化后 L2 ⇔ 余弦 ⇔ 点积」三者排序等价。

    做法：对同一批归一化向量分别用 L2 / 余弦 / 点积取 top-k，比较结果是否一致。
    """
    np.random.seed(7)
    vectors = l2_normalize(np.random.randn(n, d).astype(np.float32))
    query = l2_normalize(np.random.randn(d).astype(np.float32))

    top_l2 = brute_search_l2(query, vectors, top_k)
    top_cos = brute_search_cosine(query, vectors, top_k)
    # 点积 top-k（归一化后点积 = 余弦，直接取最大）
    sims_ip = vectors @ query
    top_ip = np.argpartition(-sims_ip, top_k)[:top_k]
    top_ip = top_ip[np.argsort(-sims_ip[top_ip])]

    set_l2, set_cos, set_ip = set(top_l2.tolist()), set(top_cos.tolist()), set(top_ip.tolist())

    print("=" * 64)
    print(f"实验 3：归一化后三种度量排序等价性验证（n={n:,}, d={d}, top_k={top_k}）")
    print("=" * 64)
    print(f"L2   top-k: {sorted(top_l2.tolist())}")
    print(f"余弦 top-k: {sorted(top_cos.tolist())}")
    print(f"点积 top-k: {sorted(top_ip.tolist())}")
    print(f"L2 ∩ 余弦 = {len(set_l2 & set_cos)}/{top_k}")
    print(f"L2 ∩ 点积 = {len(set_l2 & set_ip)}/{top_k}")
    print(f"余弦 ∩ 点积 = {len(set_cos & set_ip)}/{top_k}")
    print("→ 归一化后三者 top-k 完全一致，库内部可用 L2 索引等价实现余弦检索。\n")


# =====================================================================
# 主入口
# =====================================================================

if __name__ == "__main__":
    print("Week 05 Day 01 — 向量数据库原理 + ANN 索引算法 基准测试\n")

    # 实验 1：暴力搜索随规模线性增长
    benchmark_brute([10_000, 100_000, 1_000_000], d=768, top_k=5)

    # 实验 2：暴力 vs IVF（召回率 + 速度 + 长尾）
    benchmark_ivf(n=100_000, d=128, top_k=10, nlist=100)

    # 实验 3：归一化后三种度量等价性验证
    verify_distance_equivalence(d=128, n=50_000, top_k=10)

    print("=" * 64)
    print("提示：")
    print("  - 白银级：改 benchmark_ivf 的 nlist (50/200/500) 与 nprobes 找甜点参数")
    print("  - 王者级：用 matplotlib 画 Recall@10 / 耗时 vs nprobe 双轴曲线")
    print("=" * 64)
