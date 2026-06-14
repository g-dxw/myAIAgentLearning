# Day 05 — 检索质量优化

## 今日目标
检索质量是 RAG 的瓶颈——今天掌握四种主流优化方法，知道什么时候用哪种。

---

- [ ] 今日学了什么
  - [ ] 检索质量差的四类表现：
    - [ ] 检索结果和问题无关（语义漂移）
    - [ ] 关键信息没被检索到（漏检）
    - [ ] 检索结果太泛（缺乏精确性）
    - [ ] 用户问题本身不完整（指代不明）
  - [ ] 四种优化方法：

  ### 1. Query Rewriting（查询重写）
  - [ ] 用 LLM 改写用户问题：补全指代、扩展同义词、拆解复杂问题
  - [ ] 例："他昨天说了什么？"→"关于上周五的会议，张三说了什么？"
  - [ ] 实现：写一个 rewrite prompt，检索前先调 LLM 改一遍

  ### 2. Re-ranking（重排序）
  - [ ] 为什么需要：Embedding 检索是粗筛，可能漏掉"用词不同但语义相关"的结果
  - [ ] Cross-Encoder 做精排：把 query + 每个 chunk 成对输入，输出相关性分数
  - [ ] 方案：BGE-Reranker（HuggingFace）、Cohere Rerank API
  - [ ] 流程：粗检索 top 20 → Re-ranker 打分 → 取 top 5

  ### 3. Multi-Query（多路查询）
  - [ ] 把一个问题拆成多个子查询，并行检索后合并去重
  - [ ] 例："RAG 有哪些优化方法？"→ "RAG 检索优化" "RAG 重排序方法" "RAG 查询增强"
  - [ ] 合并策略：RRF（Reciprocal Rank Fusion）

  ### 4. HyDE（假设文档嵌入）
  - [ ] 先用 LLM 生成一个假设答案，用答案的向量去检索
  - [ ] 原理：假设答案和真实资料语义更接近（都在"答案空间"）
  - [ ] 代价：多一次 LLM 调用，延迟翻倍

  - [ ] 检索评估指标：
    - [ ] **Recall@K**：前 K 个结果中包含正确答案的比例
    - [ ] **MRR**（Mean Reciprocal Rank）：第一个正确答案的排名倒数的均值
    - [ ] 用人工标注的 ground truth 跑评估脚本

  - [ ] 决策树：什么时候用哪种优化？
    ```
    问题不清晰 → Query Rewriting
    检索结果太多（top_k 大）→ Re-ranking
    问题复杂多面 → Multi-Query
    用户问题和资料用词差异大 → HyDE
    ```

- [ ] 写了什么代码
  ```
  week04/day05/retrieval_optimizer.py  — 四种优化方法实现
  week04/day05/retrieval_eval.py       — 检索效果评估（Recall@K / MRR）
  ```

- [ ] 踩了什么坑 / 怎么解决的

- [ ] 明天计划

---

## 副线笔记

Claude Code 在搜索代码时，它的检索策略有哪些？它是怎么做到精准定位的？

> 提示：试着让 Claude Code "找到处理用户登录的代码"，观察它是用 grep 还是语义理解？如果有多种方式，它怎么排优先级？
