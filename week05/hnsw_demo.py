"""
hnsw_demo.py — HNSW 算法简化实现 + 参数调优实验

本文件演示：
1. 用 numpy 从零实现一个简化版 HNSW（分层可导航小世界图 + 贪心搜索）
2. 参数调优实验：扫描 M ∈ {8,16,32}、ef_search ∈ {50,100,200}，测量召回率与延迟

注意：这是「教学版」实现，重点是讲清分层贪心搜索的思想，不是生产级性能。
生产级请直接使用 Chroma / Milvus / Qdrant 内置的 HNSW（底层是 hnswlib / 自研 C++ 实现）。

依赖：numpy
运行：python hnsw_demo.py
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ============================================================
# 第一部分：距离工具
# ============================================================

def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """余弦距离 = 1 - 余弦相似度，取值范围 [0, 2]，越小越相似。"""
    denom = np.linalg.norm(a) * np.linalg.norm(b) + 1e-12
    return 1.0 - float(np.dot(a, b) / denom)


# ============================================================
# 第二部分：简化版 HNSW 索引
# ============================================================

@dataclass
class HNSWIndex:
    """
    简化版 HNSW 索引。

    参数:
        dim: 向量维度
        M: 每个节点在每层的最大连接数。越大召回越高、内存越大。经验值 16-48
        ef_construction: 建索引时的搜索宽度。越大索引质量越好、建得越慢。经验值 200-500
        ef_search: 查询时的搜索宽度。越大召回越高、查询越慢。经验值 >= top_k
        mL: 层级分配系数，默认 1/ln(M)，控制节点落到高层的概率
    """

    dim: int
    M: int = 16
    ef_construction: int = 200
    ef_search: int = 50
    mL: float = 0.0

    # 多层图：layers[level] = {node_id: [neighbor_ids]}
    layers: list[dict[int, list[int]]] = field(default_factory=list)
    # 向量存储：node_id -> 向量
    vectors: dict[int, np.ndarray] = field(default_factory=dict)
    # 每个节点的最高层级
    node_level: dict[int, int] = field(default_factory=dict)
    # 全局入口点（处于最高层的某个节点）
    entry_point: Optional[int] = None
    max_level: int = -1
    _next_id: int = 0

    def __post_init__(self) -> None:
        if self.M < 2:
            raise ValueError("M 至少为 2，否则无法构成图")
        if self.mL == 0.0:
            # 标准做法：mL = 1/ln(M)，让层级按指数衰减
            self.mL = 1.0 / np.log(self.M)

    # ---------- 层级分配 ----------

    def _random_level(self) -> int:
        """
        按指数衰减概率分配层级：层号越大，落到该层的概率越低。
        这正是 HNSW「上层稀疏、下层稠密」的来源。
        """
        return int(-np.log(np.random.random() + 1e-12) * self.mL)

    # ---------- 单层搜索核心 ----------

    def _search_layer(
        self,
        query: np.ndarray,
        entry_points: list[int],
        ef: int,
        layer: int,
    ) -> list[tuple[float, int]]:
        """
        在单层图上做 best-first 搜索，维护大小为 ef 的结果集（对应 HNSW 论文 Algorithm 2）。

        - C: 候选 min-heap，按距离升序，决定下一个要展开的节点
        - W: 结果 max-heap（用负距离模拟），容量 ef，始终保留目前最近的 ef 个
        - 终止条件: 当候选集里最近的点都比结果集里最远的点还远时停止
          （说明所有更优的候选都已展开完，再扩也不会更好）

        参数:
            query: 查询向量
            entry_points: 该层的入口节点列表
            ef: 搜索宽度（结果集大小上限），越大召回越高、延迟越高
            layer: 搜索的层号

        返回: [(距离, 节点id), ...]，长度 <= ef，按距离升序
        """
        visited: set[int] = set(entry_points)
        C: list[tuple[float, int]] = []  # 候选 min-heap: (dist, node)
        W: list[tuple[float, int]] = []  # 结果 max-heap: (-dist, node)
        for ep in entry_points:
            d = cosine_distance(query, self.vectors[ep])
            heapq.heappush(C, (d, ep))
            heapq.heappush(W, (-d, ep))

        while C:
            c_dist, c = heapq.heappop(C)
            # 候选最近点已比结果集最远点还远 -> 停止
            if c_dist > -W[0][0]:
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
                        heapq.heappop(W)  # 丢弃最远点，保持 ef 上限
        return sorted((-neg, node) for neg, node in W)

    def _greedy_descend(self, query: np.ndarray, entry: int, layer: int) -> int:
        """贪心下降一层：在该层用 ef=1 找最近节点，作为下一层入口。"""
        res = self._search_layer(query, [entry], ef=1, layer=layer)
        return res[0][1] if res else entry

    def _select_neighbors(
        self, query: np.ndarray, entry: int, m: int, layer: int
    ) -> list[int]:
        """建索引时选 m 个邻居（简化版：取距离最近的 m 个）。"""
        found = self._search_layer(query, [entry], ef=self.ef_construction, layer=layer)
        found.sort()
        return [n for _, n in found[:m]]

    def _prune(self, node: int, layer: int) -> None:
        """修剪节点的邻居列表到 M 个，保留距离最近的（简化策略）。"""
        neighbors = self.layers[layer].get(node, [])
        if len(neighbors) <= self.M:
            return
        vec = self.vectors[node]
        ranked = sorted(
            neighbors, key=lambda nb: cosine_distance(vec, self.vectors[nb])
        )
        self.layers[layer][node] = ranked[: self.M]

    # ---------- 插入 ----------

    def add(self, vec: np.ndarray) -> int:
        """插入一个向量，返回分配的 node_id。"""
        node_id = self._next_id
        self._next_id += 1
        self.vectors[node_id] = vec
        level = self._random_level()
        self.node_level[node_id] = level

        # 按需扩展图层数
        while len(self.layers) <= level:
            self.layers.append({})

        # 第一个节点：成为入口，各层都没有邻居
        if self.entry_point is None:
            for l in range(level + 1):
                self.layers[l][node_id] = []
            self.entry_point = node_id
            self.max_level = level
            return node_id

        ep = self.entry_point
        # 1) 从最高层贪心下降到 level+1 层：只定位、不连接（长距离跳）
        for l in range(self.max_level, level, -1):
            ep = self._greedy_descend(vec, ep, layer=l)

        # 2) 在 min(level, max_level) ~ 0 层：插入节点并与邻居双向连接
        for l in range(min(level, self.max_level), -1, -1):
            neighbors = self._select_neighbors(vec, ep, self.M, layer=l)
            self.layers[l][node_id] = list(neighbors)
            for nb in neighbors:
                self.layers[l].setdefault(nb, []).append(node_id)
                self._prune(nb, l)  # 保持邻居数 <= M
            if neighbors:
                ep = neighbors[0]  # 下一层从最近邻居继续搜

        # 3) 若新节点层级更高，它在高层是稀疏孤立点，更新全局入口
        if level > self.max_level:
            for l in range(self.max_level + 1, level + 1):
                self.layers[l][node_id] = []
            self.max_level = level
            self.entry_point = node_id
        return node_id

    # ---------- 查询 ----------

    def search(self, query: np.ndarray, top_k: int = 10) -> list[tuple[int, float]]:
        """
        查询 top_k 最近邻。

        流程: 从最高层用 ef=1 快速定位 -> 第 0 层用 ef_search 精搜 -> 取 top_k
        返回: [(node_id, 距离), ...]，按距离升序
        """
        if self.entry_point is None:
            return []
        ep = self.entry_point
        # 顶层快速下降（长距离跳，ef=1）
        for l in range(self.max_level, 0, -1):
            ep = self._greedy_descend(query, ep, layer=l)
        # 第 0 层精搜（ef_search 控制召回与延迟的平衡）
        ef = max(self.ef_search, top_k)
        results = self._search_layer(query, [ep], ef=ef, layer=0)
        results.sort()
        return [(n, d) for d, n in results[:top_k]]


# ============================================================
# 第三部分：参数调优实验
# ============================================================

def build_dataset(n: int = 2000, dim: int = 32, seed: int = 42) -> np.ndarray:
    """
    生成连续分布的向量数据集（均匀随机），用于评估召回率。

    为什么用连续分布而不是强聚类数据？
    - 真实 ANN benchmark（SIFT / GIST 等）数据是连续分布的，最近邻分散在空间中，
      这样 ef_search 的调优才有区分度。
    - 强聚类数据太"容易"：贪心搜索一进簇就能找到全部近邻，ef 大小看不出差异，
      无法体现参数调优的价值。
    """
    rng = np.random.default_rng(seed)
    return rng.uniform(-1, 1, size=(n, dim)).astype(np.float64)


def brute_force_topk(data: np.ndarray, query: np.ndarray, top_k: int = 10) -> set[int]:
    """暴力搜索，作为召回率评估的 ground truth。"""
    norms = np.linalg.norm(data, axis=1) * np.linalg.norm(query) + 1e-12
    dists = 1.0 - np.dot(data, query) / norms
    idx = np.argsort(dists)[:top_k]
    return set(idx.tolist())


def recall_at_k(retrieved: set[int], ground_truth: set[int]) -> float:
    """召回率 = 交集大小 / ground_truth 大小。"""
    if not ground_truth:
        return 0.0
    return len(retrieved & ground_truth) / len(ground_truth)


def tune_experiment(n: int = 2000, dim: int = 32, n_queries: int = 30) -> list[dict]:
    """
    参数调优实验：扫描 M 和 ef_search，测量召回率与延迟。

    返回: [{M, ef, recall, latency_ms, build_s}, ...]
    """
    data = build_dataset(n=n, dim=dim)
    # 用前 n_queries 条当查询（它们也已在索引中，这里只做召回对比）
    queries = data[:n_queries]
    print(f"数据集: {data.shape}  查询数: {n_queries}")
    print(f"{'M':>4} {'ef':>5} {'召回率':>8} {'延迟(ms)':>10} {'建索引(s)':>10}")
    print("-" * 45)

    rows: list[dict] = []
    for M in [8, 16, 32]:
        index = HNSWIndex(dim=dim, M=M, ef_construction=200)
        t0 = time.time()
        for vec in data:
            index.add(vec)
        build_s = time.time() - t0

        for ef in [50, 100, 200]:
            index.ef_search = ef
            recalls, latencies = [], []
            for q in queries:
                gt = brute_force_topk(data, q, top_k=10)
                t0 = time.time()
                hits = index.search(q, top_k=10)
                latencies.append((time.time() - t0) * 1000)
                retrieved = {n_id for n_id, _ in hits}
                recalls.append(recall_at_k(retrieved, gt))
            row = {
                "M": M,
                "ef": ef,
                "recall": float(np.mean(recalls)),
                "latency_ms": float(np.mean(latencies)),
                "build_s": build_s,
            }
            rows.append(row)
            print(
                f"{M:>4} {ef:>5} {row['recall']:>8.3f} "
                f"{row['latency_ms']:>10.2f} {build_s:>10.2f}"
            )
    return rows


# ============================================================
# 第四部分：单层贪心搜索可视化演示
# ============================================================

def demo_single_layer_greedy():
    """演示单层图上的贪心搜索过程（对应 day02.md 第二章 NSW 部分）。"""
    rng = np.random.default_rng(0)
    data = rng.normal(size=(20, 4))
    index = HNSWIndex(dim=4, M=4, ef_construction=50)
    for v in data:
        index.add(v)

    query = rng.normal(size=4)
    print("\n[单层贪心搜索演示] 20 个点，M=4")
    print(f"入口点: node {index.entry_point} (最高层 {index.max_level})")
    hits = index.search(query, top_k=5)
    print("top 5 结果:")
    for nid, dist in hits:
        print(f"  node {nid:>2}  距离={dist:.4f}")


if __name__ == "__main__":
    print("=" * 50)
    print("HNSW 简化版演示 + 参数调优实验")
    print("=" * 50)
    demo_single_layer_greedy()
    print("\n" + "=" * 50)
    print("参数调优实验：扫描 M × ef_search")
    print("=" * 50)
    tune_experiment()
