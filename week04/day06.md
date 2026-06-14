# Day 06 — 高级 RAG 模式 + 自定义 Slash Command

## 学习目标

掌握三种高级 RAG 模式，知道基础 RAG 什么时候不够用。副线重点：创建你的第一个 Claude Code 自定义 Slash Command。

学完今天你能：
1. 实现 Self-RAG：让 LLM 自己判断是否需要检索
2. 理解 Corrective RAG 的 fallback 机制
3. 把检索做成 Tool，实现 Agentic RAG
4. 创建 `/rag-index` 和 `/rag-ask` 两个 Slash Command

---

## 一、基础 RAG 的三个局限

```
局限 1: 无脑检索
  不管什么问题都检索 → 用户说"你好"，也去向量库里搜 → 浪费

局限 2: 结果不好不会调整
  检索结果跑偏了 → 基础 RAG 照样发给 LLM → 垃圾进垃圾出

局限 3: 单次检索
  查一次就生成答案 → 复杂问题需要"查A→发现缺B→再查B" → 做不到
```

---

## 二、Self-RAG（自反射 RAG）

### 2.1 核心思想

**让 LLM 自己判断：这个问题需要检索吗？检索结果好吗？**

```
传统 RAG:  问题 → [必检索] → 生成答案
Self-RAG:  问题 → LLM判断 → 不需要检索 → 直接回答
                     → 需要检索 → 检索 → LLM逐条评估
                         → 相关的 → 基于这类资料生成
                         → 不相关的 → 标记，不引用
```

### 2.2 实现

```python
"""advanced_rag.py — Self-RAG 实现"""

SELF_RAG_PROMPT = """你是智能问答助手。对于用户的问题，请先判断是否需要检索文档资料。

## 判断规则
- 如果问题是问候、闲聊、或你明确知道且不需要文档支持的 → 直接回答
- 如果问题涉及具体知识、数据、或需要文档验证 → 回答"NEED_RETRIEVAL"

## 用户问题
{question}

## 你的判断（直接回答 / NEED_RETRIEVAL）"""


async def self_rag_query(
    question: str,
    pipeline: "RAGPipeline",
    llm: "httpx.AsyncClient",
) -> dict:
    """Self-RAG: 先判断是否需要检索，再决定是否查库"""
    # Step 1: 判断是否需要检索
    resp = await llm.post("/api/chat", json={
        "model": "qwen2.5:1.5b",
        "messages": [{"role": "user", "content": SELF_RAG_PROMPT.format(question=question)}],
        "options": {"temperature": 0, "num_predict": 100},
        "stream": False,
    })
    judgment = resp.json()["message"]["content"].strip()

    # Step 2: 根据判断决定行为
    if "NEED_RETRIEVAL" in judgment:
        # 需要检索
        contexts = await pipeline.retrieve(question, top_k=5)

        # 逐条评估检索结果是否相关
        relevant = []
        for ctx in contexts:
            eval_prompt = f"问题: {question}\n片段: {ctx['text'][:200]}\n这个片段和问题相关吗？只回答 YES 或 NO。"
            eval_resp = await llm.post("/api/chat", json={
                "model": "qwen2.5:1.5b",
                "messages": [{"role": "user", "content": eval_prompt}],
                "options": {"temperature": 0, "num_predict": 5},
                "stream": False,
            })
            if "YES" in eval_resp.json()["message"]["content"].upper():
                relevant.append(ctx)

        if not relevant:
            return {"answer": "抱歉，文档中没有找到相关信息。", "sources": [], "mode": "self_rag_no_result"}

        return await pipeline.generate(question, relevant)
    else:
        # 不需要检索，直接回答
        resp = await llm.post("/api/chat", json={
            "model": "qwen2.5:1.5b",
            "messages": [{"role": "user", "content": question}],
            "options": {"temperature": 0.7, "num_predict": 500},
            "stream": False,
        })
        answer = resp.json()["message"]["content"]
        return {"answer": answer, "sources": [], "mode": "self_rag_direct"}
```

### 2.3 Self-RAG vs 基础 RAG

| 场景 | 基础 RAG | Self-RAG |
|------|---------|----------|
| "你好" | 检索 → 生成答案（浪费） | 判断不需要 → 直接回复 |
| "请假流程是什么" | 检索 → 可能有无关结果 | 检索 → 过滤无关结果 → 只用相关的 |
| "总结这个文档" | 检索全部 → 全塞给 LLM | 检索 → 逐条评估 → 过滤 |

**Self-RAG 的价值：节省不必要的检索 + 过滤低质量结果。**

---

## 三、Corrective RAG（修正 RAG）

### 3.1 核心思想

**检索结果不好时自动 fallback。**

```
检索 → LLM 评估质量
  ├─ 质量 OK → 正常生成
  └─ 质量差 → 改写 query 重新检索
              → 还不行 → fallback 到 Web 搜索 / 直接说不知道
```

### 3.2 实现核心

```python
async def corrective_rag_query(
    question: str,
    pipeline: "RAGPipeline",
    llm: "httpx.AsyncClient",
    max_retries: int = 2,
) -> dict:
    """Corrective RAG: 检索质量不好时自动修正重试"""
    current_question = question

    for attempt in range(max_retries + 1):
        # 检索
        contexts = await pipeline.retrieve(current_question, top_k=5)

        if not contexts:
            # 没有任何结果
            if attempt < max_retries:
                # 尝试改写问题重试
                current_question = await rewrite_query_for_retry(question, llm)
                continue
            return {"answer": "抱歉，多次检索均未找到相关信息。", "sources": []}

        # 评估检索质量
        quality = await evaluate_retrieval_quality(question, contexts, llm)

        if quality["score"] >= 0.6:
            # 质量 OK，正常生成
            return await pipeline.generate(question, contexts)

        if attempt < max_retries:
            # 质量不够，改写后重试
            current_question = quality.get("suggested_query", current_question)
        else:
            # 最后一次，勉强基于现有结果生成
            return await pipeline.generate(question, contexts)

    return {"answer": "检索质量不佳，无法提供可靠答案。", "sources": []}
```

---

## 四、Agentic RAG（Agent 驱动 RAG）

### 4.1 核心思想

**把检索做成 Tool，让 Agent 决定什么时候查、查什么、查几轮。** 这是最灵活的 RAG 模式，也最接近 Claude Code 的工作方式。

```
while True:
    LLM 决策:
    ├─ "我需要查 RAG chunk_size 的内容" → 调 search_documents("chunk_size 配置")
    │                                       → 结果追加 → 继续循环
    ├─ "我还需要查 overlap 的配置"        → 调 search_documents("overlap 推荐值")
    │                                       → 结果追加 → 继续循环
    └─ "信息够了，可以回答了"              → 生成最终答案 → break
```

### 4.2 把检索封装成 Tool

```python
# 定义一个 search_documents tool（OpenAI 格式）
SEARCH_DOCUMENTS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_documents",
        "description": "在已索引的文档中检索与查询相关的内容。返回最相关的文本块和来源信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索查询，使用关键词而非完整句子效果更好",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量，默认 5",
                },
            },
            "required": ["query"],
        },
    },
}


async def search_documents_handler(
    query: str,
    top_k: int = 5,
    pipeline: "RAGPipeline" = None,
) -> dict:
    """工具处理函数：检索文档并返回格式化结果"""
    contexts = await pipeline.retrieve(query, top_k=top_k)

    results = []
    for ctx in contexts:
        results.append({
            "source": ctx["metadata"].get("source", "未知"),
            "page": ctx["metadata"].get("page", ""),
            "text": ctx["text"][:300],
            "similarity": ctx["similarity"],
        })

    return {"query": query, "total_found": len(results), "results": results}
```

### 4.3 三种模式对比

| 维度 | 基础 RAG | Self-RAG | Agentic RAG |
|------|---------|----------|-------------|
| 检索时机 | 每次必检索 | LLM 判断是否检索 | LLM 决定何时检索 |
| 检索次数 | 1 次 | 1 次 | 多轮，不限次数 |
| 复杂度 | 低 | 中 | 高 |
| 延迟 | 低 | 中（+判断） | 高（多轮 LLM 调用） |
| 适用场景 | 单文档问答 | 多文档质量参差 | 复杂推理任务 |

---

## 五、副线专项：自定义 Slash Command

### 5.1 Claude Code 的 Slash Command 机制

Slash Command 是你放在 `.claude/commands/` 目录下的 Markdown 文件。文件名就是命令名：

```
.claude/commands/
├── rag-index.md     → 在 Claude Code 里输入 /rag-index 触发
└── rag-ask.md       → 输入 /rag-ask 触发
```

文件内容是给 Claude Code 的指令。当用户执行 `/rag-ask xxx` 时，`$ARGUMENTS` 被替换为 `xxx`。

### 5.2 `/rag-index` — 索引文档命令

创建 `.claude/commands/rag-index.md`：

```markdown
请执行以下操作来索引文档：

1. 读取文件 $ARGUMENTS
2. 分析文件类型（PDF/Markdown/TXT/HTML）
3. 使用项目中的 DocumentSplitter 将文档分割为 chunks
   - chunk_size=800, chunk_overlap=100
4. 对每个 chunk 调用 Embedding API（Ollama nomic-embed-text）
5. 将所有 chunk + 向量存入 Chroma（路径: ./chroma_db）
6. 返回统计信息：
   - 文件名
   - 文档类型
   - chunk 数量
   - 平均 chunk 大小
   - 入库耗时

注意：
- 使用 core/splitter.py 中的 DocumentSplitter
- 使用 core/embedding.py 中的 embed_text
- 使用 rag/vector_store.py 中的 VectorStore
- 如果文件不存在，报错提示
- 如果 Chroma 未初始化，自动初始化
```

### 5.3 `/rag-ask` — RAG 问答命令

创建 `.claude/commands/rag-ask.md`：

```markdown
请基于已索引的文档回答以下问题：$ARGUMENTS

执行步骤：
1. 将问题 $ARGUMENTS 转为 Embedding 向量
2. 从 Chroma 检索 top 5 相关内容
3. 使用 STANDARD_RAG Prompt 模板构建 Prompt
4. 调用 LLM 生成答案
5. 回答时标注引用来源（文件名 + 页码 + 相似度）

注意：
- 如果向量库为空，提示"请先用 /rag-index 索引文档"
- 如果检索到的结果相似度都低于 0.3，提示"资料中未找到相关信息"
- 答案必须基于检索到的文档内容，不要编造
```

### 5.4 模板变量速查

| 变量 | 说明 | 示例 |
|------|------|------|
| `$ARGUMENTS` | 用户输入的全部参数 | `/rag-ask hello world` → `hello world` |
| `$SELECTED_TEXT` | 用户在 IDE 中选中的文本 | 选中的代码或文档内容 |

### 5.5 验证命令

```bash
# 在 Claude Code 对话中输入：
/rag-index path/to/document.pdf
/rag-ask 这篇文档主要讲了什么？
```

---

## 六、动手实验

### 🟢 青铜级：测试 Self-RAG

用几个测试问题对比基础 RAG 和 Self-RAG 的检索次数和答案质量。

### 🟡 白银级：创建 Slash Command

在 `.claude/commands/` 下创建 `rag-index.md` 和 `rag-ask.md`，用 `/rag-ask` 对 Day 04 索引的文档提问。

### 🔴 王者级：实现 Agentic RAG

把 `search_documents` 工具注册到 Day 03 (Week 03) 的 Agent Loop 中，让 Agent 自主检索多轮后再回答。

---

## 七、副线笔记

### 本周 Slash Command 带来的改变

```
不用 Slash Command 时:
  每次要索引文档 → 复制代码 → 修改路径 → 运行 → 手动检查

用了 /rag-index 后:
  /rag-index path/to/doc.pdf → 自动完成 → 报告结果
```

**想一想：** 还有哪些重复操作可以封装成 Slash Command？Day 07 的项目构建、代码审查、测试运行？

---

## 今日产出检查清单

- [ ] 理解 Self-RAG / Corrective RAG / Agentic RAG 三种模式的差异
- [ ] 实现了至少一种高级 RAG 模式
- [ ] 创建了 `.claude/commands/rag-index.md`
- [ ] 创建了 `.claude/commands/rag-ask.md`
- [ ] 用 `/rag-ask` 成功完成了一次 RAG 问答

---

> **下一课预告：Day 07 — 综合实战：文档问答系统**。把本周所有模块组装成完整的 FastAPI 后端 + Web UI。
