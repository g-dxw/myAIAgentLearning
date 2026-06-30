"""
Agentic RAG Pipeline

Agent 自主决策检索流程：
1. 用原始问题检索
2. 评估检索结果质量（关键词覆盖率）
3. 如果质量不足，Agent 自主选择策略重试：
   a. 提取关键词重新检索
   b. 中英文翻译后检索
   c. 扩大 top_k
4. 最多重试 3 轮
5. 综合最佳结果生成答案
"""

import asyncio
import json
import re
from typing import List

import httpx

from core.embedding import Embedding
from rag.vector_store import VectorStore
from rag.retriever import Retriever
from rag.generator import Generator
import core.config as config


class AgenticRAGPipeline:
    """Agent 驱动的 RAG，自主评估检索质量并调整策略"""

    def __init__(self):
        self.embedding = Embedding()
        self.vector_store = VectorStore(config.CHROMA_PATH)
        self.retriever = Retriever(
            embedding=self.embedding,
            vector_store=self.vector_store
        )
        self.generator = Generator()
        self.max_retries = 3

    # ═══════════════════════════════════════════
    # Agent 工具集
    # ═══════════════════════════════════════════

    def _extract_keywords(self, question: str) -> list[str]:
        """从问题中提取关键词（中英文，保留技术术语）"""
        # 英文术语（保留 / - _ 等连接符，如 text/event-stream、--reload）
        en_terms = re.findall(r'[a-zA-Z][a-zA-Z0-9_/\-]+', question)
        # 过滤太短的词（<3字符）和常见停用词
        stop_words = {"the", "and", "for", "how", "what", "use", "using", "with", "from", "are", "was", "were"}
        en_words = [w for w in en_terms if len(w) >= 3 and w.lower() not in stop_words]

        # 中文词组（简单分词）
        cn_text = re.sub(r'[a-zA-Z0-9_\s\?\？\，\,\。\、\/\-]', '', question)
        cn_words = [cn_text[i:i+2] for i in range(len(cn_text)-1)] if len(cn_text) > 2 else [cn_text]
        cn_words = [w for w in cn_words if len(w) >= 2]

        keywords = list(set(en_words + cn_words))
        return keywords

    def _keyword_search(self, query: str, top_k: int = 15) -> list[dict]:
        """全文关键词搜索：遍历所有 chunk 做关键词匹配，罕见词权重更高"""
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        all_chunks = self.vector_store.get_all()

        # 计算每个关键词的文档频率（DF），罕见词权重更高
        df = {kw: 0 for kw in keywords}
        for chunk in all_chunks:
            text = chunk.get("text", "").lower()
            for kw in keywords:
                if kw.lower() in text:
                    df[kw] += 1

        # IDF 权重：出现越少的词权重越高
        total_docs = len(all_chunks)
        idf = {kw: (total_docs / (df[kw] + 1)) for kw in keywords}

        scored = []
        for chunk in all_chunks:
            text = chunk.get("text", "").lower()
            score = 0
            match_count = 0
            for kw in keywords:
                if kw.lower() in text:
                    score += idf[kw]  # 罕见词贡献更多分数
                    match_count += 1
            if match_count > 0:
                scored.append((score, match_count, chunk))

        # 按加权分数排序
        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, _, chunk in scored[:top_k]]

    def _hybrid_search(self, question: str, top_k: int = 15) -> list[dict]:
        """混合检索：向量检索 + 关键词搜索，合并去重"""
        # 向量检索
        emb = self.embedding.embed_text(question)
        vec_results = self.vector_store.query(emb, top_k=top_k)

        # 关键词搜索
        kw_results = self._keyword_search(question, top_k=top_k)

        # 合并去重（用 chunk id 做唯一键，避免同文档不同 chunk 被误判为重复）
        seen = set()
        merged = []
        for r in vec_results + kw_results:
            key = r.get("id", "")
            if not key:
                doc_id = r.get("metadata", {}).get("doc_id", "")
                idx = r.get("metadata", {}).get("index", "")
                key = doc_id + "_" + str(idx)
            if key not in seen:
                seen.add(key)
                merged.append(r)

        return merged[:top_k]

    def _evaluate_retrieval(self, question: str, results: list[dict]) -> dict:
        """评估检索结果质量"""
        if not results:
            return {"score": 0, "reason": "无结果", "need_retry": True}

        # 提取问题关键词
        keywords = self._extract_keywords(question)

        # 检查检索结果中关键词覆盖
        all_text = " ".join(r.get("text", "") for r in results)
        matched = [kw for kw in keywords if kw.lower() in all_text.lower()]
        coverage = len(matched) / len(keywords) if keywords else 0

        # 检查检索结果的平均距离（越小越相关）
        distances = [r.get("distance", 1.0) for r in results]
        avg_distance = sum(distances) / len(distances) if distances else 1.0

        # 综合评分
        score = coverage * 0.7 + (1 - min(avg_distance, 1)) * 0.3

        need_retry = coverage < 0.3 or score < 0.3

        return {
            "score": round(score, 3),
            "coverage": round(coverage, 3),
            "matched_keywords": matched,
            "total_keywords": len(keywords),
            "avg_distance": round(avg_distance, 3),
            "need_retry": need_retry,
            "reason": "覆盖率不足" if need_retry else "质量达标",
        }

    async def _translate_query(self, question: str) -> str:
        """中英文互译查询（扩大语义覆盖）"""
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', question))
        if has_chinese:
            prompt = "请将以下中文问题翻译成英文，只输出翻译结果，不要解释：\n" + question
        else:
            prompt = "Please translate the following English question to Chinese, output only the translation:\n" + question

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    config.LLM_BASE_URL + "/chat/completions",
                    headers={
                        "Authorization": "Bearer " + config.LLM_KEY,
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": config.LLM_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 128,
                        "temperature": 0.1,
                        "stream": False
                    }
                )
                if resp.status_code in (429, 403):
                    return ""
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            return ""

    def _expand_query(self, question: str) -> str:
        """规则化扩展查询：补充同义词"""
        expansions = {
            "虚拟环境": "venv virtualenv activate",
            "启动": "run start uvicorn",
            "服务器": "server",
            "文档": "docs documentation /docs /redoc Swagger ReDoc",
            "访问": "access url endpoint",
            "异步": "async def async",
            "关键字": "keyword def",
            "依赖注入": "Depends dependency injection",
            "中间件": "middleware CORS CORSMiddleware",
            "流式": "streaming SSE StreamingResponse text/event-stream",
            "SSE": "StreamingResponse text/event-stream Server-Sent Events",
            "相似度": "similarity cosine 余弦相似度",
            "索引算法": "HNSW index algorithm",
            "评估": "evaluation metrics 召回率 精确率 忠实度 MRR",
            "指标": "metrics recall precision faithfulness",
            "模型": "model embedding text-embedding nomic-embed bge m3e",
            "Embedding": "text-embedding nomic-embed bge-large-zh m3e",
            "改写": "rewriting query rewrite",
            "结构": "structure template",
            "参数": "parameter argument",
            "路径参数": "path parameter",
            "查询参数": "query parameter",
            "重叠": "overlap chunk_overlap boundary 边界",
            "chunk_overlap": "overlap 重叠 边界 boundary",
            "chunk_size": "chunk size 块大小 500 1000",
            "数据类型": "int float str bool list tuple dict",
        }
        result = question
        for cn, en in expansions.items():
            if cn in question:
                result += " " + en
        return result

    # ═══════════════════════════════════════════
    # Agent 主流程
    # ═══════════════════════════════════════════

    async def _agent_retrieve(self, question: str, top_k: int) -> dict:
        """Agent 自主检索：执行所有策略，合并所有结果"""
        log = []
        best_score = 0
        seen = set()
        merged = []

        # 策略列表（全部执行，选最好的）
        expanded = self._expand_query(question)
        strategies = [
            ("hybrid", question, top_k, "hybrid"),
            ("keyword", question, top_k, "keyword"),
            ("expanded_keyword", expanded, top_k, "keyword"),
            ("expanded_hybrid", expanded, top_k * 2, "hybrid"),
        ]

        for round_num, strategy in enumerate(strategies):
            strategy_name, query, k, search_type = strategy

            # 执行检索
            if search_type == "keyword":
                results = self._keyword_search(query, top_k=k)
            elif search_type == "hybrid":
                results = self._hybrid_search(query, top_k=k)
            else:
                query_emb = self.embedding.embed_text(query)
                results = self.vector_store.query(query_emb, top_k=k)

            # 评估
            evaluation = self._evaluate_retrieval(question, results)

            log.append({
                "round": round_num + 1,
                "strategy": strategy_name,
                "query": query[:60],
                "top_k": k,
                "score": evaluation["score"],
                "coverage": evaluation["coverage"],
            })

            # 合并所有策略的结果（去重，用 chunk id 做唯一键）
            for r in results:
                key = r.get("id", "")
                if not key:
                    doc_id = r.get("metadata", {}).get("doc_id", "")
                    idx = r.get("metadata", {}).get("index", "")
                    key = doc_id + "_" + str(idx)
                if key not in seen:
                    seen.add(key)
                    merged.append(r)

            if evaluation["score"] > best_score:
                best_score = evaluation["score"]

        # 按关键词匹配数重新排序（确保包含关键词的 chunk 排在前面）
        keywords = self._extract_keywords(self._expand_query(question))
        merged.sort(key=lambda r: sum(1 for kw in keywords if kw.lower() in r.get("text", "").lower()), reverse=True)

        return {
            "contexts": merged[:top_k],
            "best_score": best_score,
            "rounds": len(log),
            "log": log,
        }

    async def query(self, question: str, conv_id: str = None) -> dict:
        """Agentic RAG 问答"""
        # 1. Agent 自主检索
        retrieval_result = await self._agent_retrieve(question, config.RETRIEVAL_TOP_K)
        contexts = retrieval_result["contexts"]

        # 2. 生成答案
        result = await self.generator.generate(question, contexts)
        result["question"] = question
        result["agent_log"] = retrieval_result["log"]
        result["agent_rounds"] = retrieval_result["rounds"]
        result["retrieval_score"] = retrieval_result["best_score"]

        return result

    async def query_stream(self, question: str, conv_id: str = None):
        """Agentic RAG 流式问答"""
        # 1. Agent 自主检索
        retrieval_result = await self._agent_retrieve(question, config.RETRIEVAL_TOP_K)
        contexts = retrieval_result["contexts"]

        # 2. 流式生成
        async for token in self.generator.generate_stream(question, contexts):
            token["agent_rounds"] = retrieval_result["rounds"]
            yield token
