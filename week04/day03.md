# Day 03 — 向量数据库 + 检索

## 今日目标
把 Embedding 向量存进向量库，实现基础的语义检索和混合检索。

---

- [ ] 今日学了什么
  - [ ] 三种向量存储方案对比：
    - [ ] **Chroma**：Python 原生，零配置，适合本地原型开发
    - [ ] **FAISS**：Meta 出品，C++ 内核，高性能内存检索
    - [ ] **Milvus / Qdrant**：生产级分布式，支持水平扩展
    - [ ] 本周选 Chroma——安装最简单，单机足够跑通
  - [ ] 向量入库流程：
    1. 文本 → `embed_text()` → 向量
    2. `collection.add(ids=..., embeddings=..., metadatas=..., documents=...)`
    3. Chroma 内部建索引（默认 HNSW）
  - [ ] 检索方式：
    - [ ] **语义检索**：`collection.query(query_embeddings=..., n_results=5)` → 按余弦相似度排序
    - [ ] **关键词检索**：用 BM25 算法对文档做词频匹配（Chroma 不内置，需手动实现或用 whoosh）
    - [ ] **混合检索**：语义 + 关键词结果做加权合并（RRF: Reciprocal Rank Fusion）
  - [ ] 检索参数：
    - [ ] `top_k`：返回几条结果。太小漏信息，太大塞进 Prompt 浪费 token
    - [ ] 相似度阈值：低于 0.3 的结果可以直接丢弃
    - [ ] `where` 过滤：按 metadata 缩小范围（如只查某个文档）
  - [ ] Chroma 持久化：`chromadb.PersistentClient(path=...)`

- [ ] 写了什么代码
  ```
  week04/day03/vector_store.py     — Chroma 封装：init / add / query / delete
  week04/day03/hybrid_search.py    — BM25 + 语义检索 + RRF 融合
  ```

  `vector_store.py` 最小接口：
  ```python
  class VectorStore:
      async def add_document(self, doc_id, chunks, embeddings, metadatas): ...
      async def query(self, query_embedding, top_k=5, where=None): ...
      async def delete_document(self, doc_id): ...
  ```

- [ ] 踩了什么坑 / 怎么解决的

- [ ] 明天计划

---

## 副线笔记

对比 Claude Code 的项目索引检索和你手写的向量检索，差异在哪？

> 提示：用 `@filename` 引用文件时 Claude Code 是怎么定位的？它用的是什么检索方式——纯文本匹配、语义检索、还是两者结合？
