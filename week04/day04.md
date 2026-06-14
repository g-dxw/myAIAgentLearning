# Day 04 — RAG 完整流水线

## 今日目标
把前三天串成一条完整流水线：上传文档 → 自动分割 → Embed → 存库 → 提问 → 检索 → 拼接 Prompt → 生成答案。

---

- [ ] 今日学了什么
  - [ ] RAG Pipeline 主流程：
    ```
    文档 → splitter.split() → embedding.embed_batch()
    → vector_store.add() → [存储完成]
    
    用户提问 → embedding.embed_text(query)
    → vector_store.query() → 检索结果
    → prompt_template.render(query, contexts) → LLM.generate()
    → [返回答案 + 引用来源]
    ```
  - [ ] RAG Prompt 模板设计三要素：
    - [ ] **注入检索上下文**：把检索到的文本块格式化塞进 system prompt
    - [ ] **约束指令**："只基于以下资料回答，如果资料中没有相关信息，请明确说'资料中未找到'"
    - [ ] **引用要求**：让模型在答案末尾列出引用的文档和段落
  - [ ] Prompt 模板示例：
    ```
    ## 参考资料
    {context}
    
    ## 规则
    - 只能基于上述资料回答
    - 如果资料中没有相关信息，说"抱歉，资料中未找到相关内容"
    - 回答末尾列出引用的资料来源
    
    ## 用户问题
    {question}
    ```
  - [ ] 对话历史管理：
    - [ ] 多轮对话时，历史消息也要传给 LLM
    - [ ] 每次新问题重新检索（不是用上一次的检索结果）
  - [ ] 来源引用格式：`[1] 来源：xxx.pdf 第3页`

- [ ] 写了什么代码
  ```
  week04/day04/rag_pipeline.py     — 完整 RAG 流水线（从上传到回答）
  week04/day04/prompt_templates.py — Prompt 模板管理（可切换不同模板）
  ```

  `rag_pipeline.py` 最小接口：
  ```python
  class RAGPipeline:
      async def index_document(self, file_path, file_type): ...
      async def query(self, question, conversation_id=None): ...
      async def query_stream(self, question, conversation_id=None): ...  # 生成器
  ```

- [ ] 踩了什么坑 / 怎么解决的

- [ ] 明天计划

---

## 副线笔记

把你的 RAG Prompt 设计思路和 Claude Code 处理上下文的方式对比——它怎么区分"项目代码"和"对话历史"？

> 提示：Claude Code 的 system prompt 里有一个 `<project-context>` 区域——它和你的 RAG Prompt 里的 `{context}` 占位符是不是同一回事？
