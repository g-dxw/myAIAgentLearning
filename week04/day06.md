# Day 06 — 高级 RAG 模式 + 自定义 Slash Command

## 今日目标
掌握三种高级 RAG 模式，知道什么时候基础 RAG 不够用。副线：创建你的第一个 Claude Code 自定义 Slash Command。

---

- [ ] 今日学了什么
  - [ ] 基础 RAG 的三个局限：
    - [ ] 不管问题是什么都检索（浪费）
    - [ ] 检索结果不好时不会调整（死板）
    - [ ] 检索是一次性的（不会多轮迭代）

  ### 1. Self-RAG（自反射 RAG）
  - [ ] 核心：让 LLM 判断"是否需要检索" + "检索结果是否相关"
  - [ ] 流程：
    ```
    用户提问 → LLM 判断："这个问题需要检索吗？"
    ├── 不需要 → 直接回答
    └── 需要 → 检索 → LLM 逐条判断检索结果是否相关
                  ├── 相关 → 基于这条资料回答
                  └── 不相关 → 标记为不相关，不引用
    ```
  - [ ] 关键：在 system prompt 里加判断 token（类似 Tool Use 的 `tool_choice`）

  ### 2. Corrective RAG（修正 RAG）
  - [ ] 核心：检索结果不行时自动 fallback
  - [ ] 流程：
    ```
    检索 → LLM 评估检索质量
    ├── 质量 OK → 正常生成
    └── 质量差 → 改写 query 重新检索 / fallback 到 Web 搜索
    ```
  - [ ] 适用场景：文档库不全，需要外部知识补充

  ### 3. Agentic RAG（Agent 驱动 RAG）
  - [ ] 核心：把检索做成一个 Tool，让 Agent 决定什么时候查、查什么、查几次
  - [ ] 流程：Agent Loop + `search_documents` tool
    ```
    while True:
        LLM 决定下一步 → 
        ├── 需要检索 → 调用 search_documents(query, top_k)
        │               → 结果追加到 messages → 继续
        ├── 回答完毕 → break
        └── 需要更多信息 → 调用 search_documents(改写后的query)
    ```
  - [ ] 和 Self-RAG 的区别：Agentic RAG 可以多轮检索，Self-RAG 是单轮评估

  - [ ] 什么时候用高级模式：
    | 场景 | 推荐模式 |
    |------|---------|
    | 单文档问答，资料齐全 | 基础 RAG |
    | 多文档，质量参差不齐 | Self-RAG |
    | 文档不全，需外部知识 | Corrective RAG |
    | 复杂推理，需多轮查询 | Agentic RAG |

- [ ] 写了什么代码
  ```
  week04/day06/advanced_rag.py    — Self-RAG / Corrective RAG / Agentic RAG 实现
  ```

---

## 副线专项：自定义 Slash Command

> 这是 Week 04 副线的重点产出——把本周的 RAG 流程封装成可复用的命令。

- [ ] 今日学了什么
  - [ ] Claude Code 的 Slash Command 机制
  - [ ] 命令文件放在 `.claude/commands/` 目录下
  - [ ] 文件名 = 命令名：`.claude/commands/rag-qa.md` → 可通过 `/rag-qa` 调用
  - [ ] 模板变量：
    - `$ARGUMENTS`：用户输入 `/rag-qa hello world` → `hello world`
    - `$SELECTED_TEXT`：用户在 IDE 中选中的文本
  - [ ] 命令内容：一段给 Claude Code 的指令模板，会被注入到对话中

- [ ] 写了什么
  ```
  .claude/commands/rag-index.md   — 索引文档命令
  .claude/commands/rag-ask.md     — RAG 问答命令
  ```

  `rag-index.md` 示例思路：
  ```markdown
  请读取文件 $ARGUMENTS，将其分割成 chunks，
  调用 Embedding API 生成向量，存入 Chroma 向量库。
  完成后报告：文件类型、chunk 数量、入库耗时。
  ```

  `rag-ask.md` 示例思路：
  ```markdown
  基于 $ARGUMENTS 这个问题，请：
  1. 生成查询向量
  2. 从 Chroma 检索 top 5 相关内容
  3. 用 RAG Prompt 模板拼接上下文
  4. 调用 LLM 生成答案（标注引用来源）
  ```

- [ ] 踩了什么坑 / 怎么解决的

- [ ] 明天计划：Day 07 综合实战，把本周所有模块组装成完整的文档问答系统

---

## 副线笔记

你创建了几个自定义 Slash Command？实际用了之后感觉哪个最有用？

> 下一步预告：Week 05 会学 Claude Code 的 Hook 机制，可以在"文件保存后自动索引"、"提交前自动问答验证"等时刻自动触发命令。
