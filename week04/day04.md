# Day 04 — RAG 完整流水线

## 学习目标

把前三天的所有模块串成一条完整流水线。上传文档 → 自动分块 → Embedding → 存库 → 用户提问 → 检索 → 拼接 Prompt → LLM 生成答案。

学完今天你能：
1. 写出完整的 RAG Pipeline 类
2. 设计一个好的 RAG Prompt 模板
3. 让答案带上引用来源
4. 处理"资料中找不到"的情况

---

## 一、Pipeline 总览

```
                    ┌──── 索引阶段（离线） ────┐
                    │                          │
   PDF/MD/TXT  →  Splitter  →  Embedding  →  VectorStore
                    │                          │
                    └──────────────────────────┘
                                               │
                    ┌──── 问答阶段（在线） ────┐
                    │                          │
   用户问题  →  Embedding  →  Retrieve  →  Prompt 模板  →  LLM  →  答案 + 引用
                    │                          │
                    └──────────────────────────┘
```

**关键区分：**
- **索引阶段**：一次性操作，上传文档时执行
- **问答阶段**：每次用户提问都执行，需要快

---

## 二、RAG Prompt 模板设计

这是 RAG 中最被低估的环节。**Prompt 模板好坏直接决定答案质量。**

### 2.1 基础模板

```python
RAG_PROMPT_TEMPLATE = """你是一个基于文档的问答助手。请严格根据以下参考资料回答用户问题。

## 规则
1. **只能**基于以下「参考资料」中的信息回答
2. 如果资料中没有相关信息，请明确说："抱歉，提供的资料中没有找到相关信息。"
3. 不要编造资料中没有的事实
4. 回答末尾列出引用的来源（用 [1] [2] 标记）

## 参考资料
{context}

## 用户问题
{question}

## 回答"""
```

### 2.2 为什么这样设计？

| 要素 | 作用 | 不写会怎样 |
|------|------|-----------|
| **只能基于资料** | 防止 LLM 用自己的知识回答 | 用户问"公司政策"时 LLM 瞎编 |
| **明确说找不到** | 防止 LLM 在没信息时强行编答案 | 资料没有的内容，LLM 凭空捏造 |
| **列出引用来源** | 让用户验证信息来源 | 答案无法核实真伪 |
| **{context} 前置** | 让 LLM 先读资料再答题 | 如果先看问题再看资料，可能先入为主 |

### 2.3 Prompt 模板管理

```python
"""prompt_templates.py — Prompt 模板管理"""

# 模板 1：标准 RAG（适合大多数场景）
STANDARD_RAG = """你是基于文档的问答助手。请严格根据参考资料回答。

## 参考资料
{context}

## 规则
- 只基于资料回答，资料没有的信息说"未找到"
- 回答末尾标注引用来源：[来源: {source}]

## 问题
{question}

## 回答"""

# 模板 2：多文档对比（适合对比分析）
COMPARISON_RAG = """你是文档分析专家。以下是从多份文档中检索到的相关内容。

## 资料
{context}

## 任务
对比分析上述资料，回答用户问题。如果各文档中的说法有冲突，请明确指出。

## 问题
{question}

## 分析"""

# 模板 3：摘要式（适合快速概览）
SUMMARY_RAG = """请根据以下资料，用不超过 200 字概括回答用户问题。列出关键信息点。

## 资料
{context}

## 问题
{question}

## 简短回答"""


def build_prompt(
    question: str,
    contexts: list[dict],
    template: str = "standard",
    history: list[dict] | None = None,
) -> str:
    """
    构建 RAG Prompt。

    参数:
        question: 用户问题
        contexts: [{"text": "...", "metadata": {"source": "a.pdf", "page": 3}}, ...]
        template: "standard" | "comparison" | "summary"
        history: [{"role": "user", "content": "..."}, ...]

    返回:
        完整的 Prompt 字符串
    """
    templates = {
        "standard": STANDARD_RAG,
        "comparison": COMPARISON_RAG,
        "summary": SUMMARY_RAG,
    }
    tpl = templates.get(template, STANDARD_RAG)

    # 格式化上下文（带来源标注）
    context_parts = []
    for i, ctx in enumerate(contexts):
        source = ctx["metadata"].get("source", "未知来源")
        page = ctx["metadata"].get("page", "")
        label = f"[{i + 1}] 来源: {source}"
        if page:
            label += f" 第{page}页"
        context_parts.append(f"{label}\n{ctx['text']}")

    context_str = "\n\n---\n\n".join(context_parts)

    prompt = tpl.format(context=context_str, question=question)

    return prompt
```

---

## 三、RAG Pipeline 完整实现

把 Day 01-03 的模块组装起来：

```python
"""rag_pipeline.py — RAG 完整流水线"""
from pathlib import Path

import httpx

from core.config import (
    LLM_BASE_URL, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE,
    EMBED_BASE_URL, EMBED_MODEL,
    CHUNK_SIZE, CHUNK_OVERLAP, RETRIEVAL_TOP_K,
)
from core.embedding import embed_text
from core.splitter import DocumentSplitter
from vector_store import VectorStore
from prompt_templates import build_prompt


class RAGPipeline:
    """
    RAG 完整流水线。

    用法:
        pipeline = RAGPipeline()
        # 索引
        result = await pipeline.index_document("doc.pdf")
        # 问答
        answer = await pipeline.query("文档讲了什么？")
    """

    def __init__(self):
        self.splitter = DocumentSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        self.vector_store = VectorStore("./chroma_db")
        self._llm: httpx.AsyncClient | None = None
        self._embed: httpx.AsyncClient | None = None

    async def _get_llm(self) -> httpx.AsyncClient:
        """获取 LLM HTTP 客户端"""
        if self._llm is None:
            self._llm = httpx.AsyncClient(
                base_url=LLM_BASE_URL,
                timeout=120,
            )
        return self._llm

    async def _get_embed(self) -> httpx.AsyncClient:
        """获取 Embedding HTTP 客户端"""
        if self._embed is None:
            self._embed = httpx.AsyncClient(
                base_url=EMBED_BASE_URL,
                timeout=60,
            )
        return self._embed

    async def close(self):
        """释放 HTTP 客户端"""
        if self._llm:
            await self._llm.aclose()
        if self._embed:
            await self._embed.aclose()

    # ─── 索引阶段 ───

    async def index_document(self, file_path: str) -> dict:
        """
        索引一份文档：加载 → 分割 → Embedding → 存库。

        返回: {"doc_id": "xxx", "filename": "xxx", "chunk_count": 42}
        """
        filename = Path(file_path).name
        doc_id = f"doc_{abs(hash(filename)) % 1000000:06d}"

        # Step 1: 加载 + 分割
        chunks = self.splitter.split(file_path)
        if not chunks:
            return {"doc_id": doc_id, "filename": filename, "chunk_count": 0, "error": "无可提取文本"}

        # Step 2: Embedding（逐条）
        embed_client = await self._get_embed()
        embeddings = []
        for chunk in chunks:
            emb = await embed_text(embed_client, chunk["text"])
            embeddings.append(emb)

        # Step 3: 存库
        count = self.vector_store.add_chunks(doc_id, chunks, embeddings)

        return {
            "doc_id": doc_id,
            "filename": filename,
            "chunk_count": count,
            "avg_chunk_size": sum(len(c["text"]) for c in chunks) // max(count, 1),
        }

    # ─── 问答阶段 ───

    async def query(
        self,
        question: str,
        top_k: int = RETRIEVAL_TOP_K,
        template: str = "standard",
    ) -> dict:
        """
        RAG 问答（非流式）。

        返回: {"answer": "...", "sources": [...], "usage": {...}}
        """
        # Step 1: 问题向量化
        embed_client = await self._get_embed()
        q_embedding = await embed_text(embed_client, question)

        # Step 2: 检索
        contexts = self.vector_store.query(q_embedding, top_k=top_k)

        if not contexts:
            return {
                "answer": "抱歉，提供的资料中没有找到相关信息。",
                "sources": [],
                "usage": {},
            }

        # Step 3: 构建 Prompt
        prompt = build_prompt(question, contexts, template=template)

        # Step 4: 调 LLM
        llm = await self._get_llm()
        resp = await llm.post("/api/chat", json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": question},
            ],
            "options": {
                "temperature": LLM_TEMPERATURE,
                "num_predict": LLM_MAX_TOKENS,
            },
        })
        resp.raise_for_status()
        data = resp.json()

        # Step 5: 提取结果
        answer = data["message"]["content"]
        sources = [
            {
                "source": ctx["metadata"].get("source", "未知"),
                "page": ctx["metadata"].get("page", ""),
                "similarity": ctx["similarity"],
                "text_preview": ctx["text"][:200],
            }
            for ctx in contexts
        ]
        usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
        }

        return {"answer": answer, "sources": sources, "usage": usage}

    # ─── SSE 流式问答 ───

    async def query_stream(self, question: str, top_k: int = RETRIEVAL_TOP_K):
        """RAG 问答（SSE 流式）—— 逐 token 返回"""
        import json

        embed_client = await self._get_embed()
        q_embedding = await embed_text(embed_client, question)
        contexts = self.vector_store.query(q_embedding, top_k=top_k)

        if not contexts:
            yield f"data: {json.dumps({'type': 'answer', 'text': '抱歉，资料中未找到相关信息。'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        prompt = build_prompt(question, contexts)

        llm = await self._get_llm()
        async with llm.stream("POST", "/api/chat", json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": question},
            ],
            "stream": True,
            "options": {
                "temperature": LLM_TEMPERATURE,
                "num_predict": LLM_MAX_TOKENS,
            },
        }) as resp:
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                # Ollama 流式: 每行一个 JSON
                try:
                    chunk = json.loads(line)
                    text = chunk.get("message", {}).get("content", "")
                    if text:
                        yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
                    if chunk.get("done"):
                        # 流结束，发来源
                        sources = [
                            {
                                "source": ctx["metadata"].get("source", "未知"),
                                "page": ctx["metadata"].get("page", ""),
                                "similarity": ctx["similarity"],
                            }
                            for ctx in contexts
                        ]
                        yield f"data: {json.dumps({'type': 'sources', 'data': sources})}\n\n"
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                except json.JSONDecodeError:
                    continue


# ===== 使用示例 =====

async def main():
    pipeline = RAGPipeline()

    # 索引一个文档
    result = await pipeline.index_document("test_docs/sample.md")
    print(f"索引完成: {result}")

    # 提问
    answer = await pipeline.query("这篇文章主要讲了什么？")
    print(f"\n回答: {answer['answer']}")
    print(f"\n来源:")
    for s in answer["sources"]:
        print(f"  [{s['similarity']:.3f}] {s['source']} 第{s['page']}页")

    # 流式（验证用）
    print("\n=== 流式输出 ===")
    async for event in pipeline.query_stream("这篇文章的主要结论是什么？"):
        print(event)

    await pipeline.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## 四、对话历史管理

RAG 中处理多轮对话需要额外注意：

```
用户: "RAG 的 chunk_size 应该设多大？"
Agent: "建议 500-800 字符..."
用户: "那 overlap 呢？"  ← 问题不独立，需要结合上一轮
```

**解决方法：用 LLM 做查询重写，把指代补全。**

```python
HISTORY_REWRITE_PROMPT = """结合对话历史，把用户的问题改写为独立、完整的检索查询。

## 对话历史
{history}

## 当前问题
{question}

## 改写后的问题（可以独立用于检索）"""


async def rewrite_with_history(
    question: str,
    history: list[dict],
    llm: httpx.AsyncClient,
) -> str:
    """结合历史改写问题，使检索更精准"""
    if not history:
        return question

    history_str = "\n".join(
        f"{msg['role']}: {msg['content']}" for msg in history[-6:]  # 最近 6 条
    )
    prompt = HISTORY_REWRITE_PROMPT.format(history=history_str, question=question)

    resp = await llm.post("/api/chat", json={
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.3, "num_predict": 200},
        "stream": False,
    })
    data = resp.json()
    return data["message"]["content"].strip()
```

---

## 五、动手实验

### 🟢 青铜级：索引一个 Markdown 文件并提问

准备一个 Markdown 文件（如 README.md），跑通 index → query 全流程。

### 🟡 白银级：对比不同 Prompt 模板的效果

用同一个问题 + 同样的检索结果，分别用 `STANDARD_RAG` 和 `COMPARISON_RAG` 模板，看 LLM 回答有什么不同。

### 🔴 王者级：实现多轮对话 RAG

用 `rewrite_with_history` 补全指代，再检索，验证多轮对话时检索质量是否提升。

---

## 六、踩坑记录 🕳️

### 坑 1：检索结果为空

```python
contexts = store.query(q_embedding, top_k=5)
# 结果: []  ← 相似度太低或库是空的

# 必须处理空结果
if not contexts:
    return {"answer": "抱歉，资料中未找到相关信息。"}
```

### 坑 2：context 拼接后超长

```python
# 5 个 chunk × 800 字符 = 4000 字符 → 约 1000 tokens
# 再加上 system prompt、历史消息 → 可能超出窗口

# 解决：限制拼接后的总长度
MAX_CONTEXT_CHARS = 6000
context_str = ""
for ctx in contexts:
    if len(context_str) + len(ctx["text"]) > MAX_CONTEXT_CHARS:
        break
    context_str += ctx["text"] + "\n\n"
```

### 坑 3：LLM 不遵守"只能基于资料"

即使 Prompt 里写了，某些 LLM 仍然会用自己的知识补充。解决方法：**用更强的模型**，或**追加强调**：

```python
# 在 context 后加上
"⚠️ 再次强调：以下资料是你能使用的全部信息。如果资料不包含答案，请直接说不知道。"
```

### 坑 4：Streaming 模式下服务器中断

SSE 流式调用在生成长文本时可能因为 timeout 断开。httpx 的 `timeout` 要设得足够高（120s 以上）。

---

## 七、副线笔记

### RAG Prompt vs Claude Code 的 System Prompt

对比你写的 RAG Prompt 和 Claude Code 的 system prompt：

| 要素 | RAG Prompt | Claude Code System Prompt |
|------|-----------|--------------------------|
| 角色定义 | "你是文档问答助手" | "你是 Claude Code..." |
| 约束 | "只能基于资料" | "只能读项目文件" |
| 工具 | (无) | grep / Read / Edit |
| 输出格式 | "标注引用来源" | "标注文件路径 + 行号" |

你会发现 Claude Code 本质上就是一个 **Agentic RAG 系统**——检索工具 + 约束 prompt + 生成能力。

---

## 今日产出检查清单

- [ ] 跑通了 index_document → query 完整流程
- [ ] 答案包含来源引用
- [ ] 问"资料中没有的内容"时，回复"未找到"
- [ ] 理解三个 Prompt 模板的差异
- [ ] (可选) 实现了流式问答
- [ ] (可选) 实现了多轮对话检索

---

> **下一课预告：Day 05 — 检索质量优化**。用 Query Rewriting、Re-ranking、Multi-Query、HyDE 四种方法提升检索精度。
