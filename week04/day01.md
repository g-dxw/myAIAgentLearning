# Day 01 — RAG 基础概念 + Embedding 入门

## 今日目标
理解 RAG 是什么、解决什么问题。手调 Embedding API，直观感受"语义相近 → 向量相近"。

---

- [ ] 今日学了什么
  - [ ] RAG 是什么：Retrieval Augmented Generation 的三个关键词
  - [ ] RAG 解决什么问题：知识截止、幻觉、私有知识无法利用
  - [ ] RAG 五步流程：Load → Split → Embed → Store → Retrieve → Generate
  - [ ] Embedding 本质：把文本映射到高维向量空间，语义相近的文本向量也相近
  - [ ] 余弦相似度公式：`cos(θ) = A·B / (|A|·|B|)`
  - [ ] 用 `httpx` 调 Ollama Embedding API：`POST /api/embeddings`
  - [ ] 用 `httpx` 调 OpenAI 格式 Embedding API：`POST /v1/embeddings`
  - [ ] 手写余弦相似度函数，验证 "猫和狗" vs "猫和汽车" 的相似度差异
  - [ ] Embedding 维度概念：nomic-embed-text 是 768 维，text-embedding-3-small 可调

- [ ] 写了什么代码
  ```
  week04/day01/embedding_demo.py  — 调 Ollama Embedding API + 手算余弦相似度
  ```

  建议代码里验证这几种对比：
  - "猫" vs "狗" → 相似度高
  - "猫" vs "汽车" → 相似度低
  - "今天天气真好" vs "今天是个晴天" → 语义相近
  - "今天天气真好" vs "Python 是一门编程语言" → 语义无关

- [ ] 踩了什么坑 / 怎么解决的

- [ ] 明天计划

---

## 副线笔记

Claude Code 的 CLAUDE.md 本质上是不是一种 RAG？它是怎么"检索"你的项目上下文的？

> 提示：想一想 CLAUDE.md 和代码文件——谁是 query，谁是被检索的 document？Claude Code 每次对话开始时会读取哪些文件？这和 RAG 的检索阶段有什么异同？
