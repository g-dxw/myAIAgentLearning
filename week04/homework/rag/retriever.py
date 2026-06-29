import json
from typing import List

import httpx

from core.embedding import Embedding
from rag.vector_store import VectorStore
import core.config as config


class Retriever:
    def __init__(self, embedding: Embedding = None, vector_store: VectorStore = None):
        self.embedding = embedding or Embedding(
            model=config.EMBED_MODEL,
            base_url=config.EMBED_BASE_URL
        )
        self.vector_store = vector_store or VectorStore(config.CHROMA_PATH)

    # ═══════════════════════════════════════════════════════
    # 基础检索
    # ═══════════════════════════════════════════════════════
    async def retrieve(self, question: str, top_k: int = 5) -> list[dict]:
        """基础检索：Embedding -> VectorStore.query"""
        query_embedding = self.embedding.embed_text(question)
        results = self.vector_store.query(query_embedding, top_k=top_k)
        return results

    # ═══════════════════════════════════════════════════════
    # 1. Query Rewriting（查询改写）
    # ═══════════════════════════════════════════════════════
    async def rewrite_query(self, question: str, history: list[dict] = None) -> str:
        """Query Rewriting：补全指代。如果history存在，用LLM改写问题，否则返回原问题"""
        if not history:
            return question

        messages = []
        for turn in history:
            q = turn.get("question", "")
            a = turn.get("answer", "")
            if q:
                messages.append({"role": "user", "content": q})
            if a:
                messages.append({"role": "assistant", "content": a})

        rewrite_prompt = (
            "请根据以下对话历史，将用户最新的问题进行改写，使其含义更完整、清晰，"
            "补全其中的指代和省略内容。只输出改写后的问题，不要添加任何解释。\n\n"
            "用户最新问题：" + question + "\n\n"
            "改写后的问题："
        )
        messages.append({"role": "user", "content": rewrite_prompt})

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    config.LLM_BASE_URL + "/chat/completions",
                    headers={
                        "Authorization": "Bearer " + config.LLM_KEY,
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": config.LLM_MODEL,
                        "messages": messages,
                        "max_tokens": 256,
                        "temperature": 0.3,
                        "stream": False
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                rewritten = data["choices"][0]["message"]["content"].strip()
                return rewritten if rewritten else question
        except Exception:
            return question

    # ═══════════════════════════════════════════════════════
    # 2. Multi-Query（多查询扩展）
    # ═══════════════════════════════════════════════════════
    async def generate_multi_queries(self, question: str, n: int = 3) -> list[str]:
        """用LLM生成多个查询变体，覆盖不同表述角度"""
        prompt = (
            "你是一个搜索优化专家。请针对以下用户问题，生成 " + str(n) + " 个不同的查询变体。"
            "每个变体用不同角度或不同关键词表达同一个问题，以提高检索召回率。"
            "只输出查询变体，每行一个，不要编号和解释。\n\n"
            "用户问题：" + question + "\n\n"
            "查询变体："
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    config.LLM_BASE_URL + "/chat/completions",
                    headers={
                        "Authorization": "Bearer " + config.LLM_KEY,
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": config.LLM_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 256,
                        "temperature": 0.5,
                        "stream": False
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                queries = [line.strip() for line in content.split("\n") if line.strip()]
                # 去重并保留原问题
                unique = [question]
                for q in queries:
                    if q not in unique and len(unique) < n + 1:
                        unique.append(q)
                return unique
        except Exception:
            return [question]

    async def retrieve_multi_query(self, question: str, top_k: int = 5, n_queries: int = 3) -> list[dict]:
        """Multi-Query检索：生成多个查询变体，分别检索，合并去重"""
        queries = await self.generate_multi_queries(question, n=n_queries)
        all_results = []
        seen_ids = set()

        for q in queries:
            q_emb = self.embedding.embed_text(q)
            results = self.vector_store.query(q_emb, top_k=top_k)
            for r in results:
                doc_id = r.get("metadata", {}).get("doc_id", "")
                idx = r.get("metadata", {}).get("index", "")
                key = doc_id + "_" + str(idx)
                if key not in seen_ids:
                    seen_ids.add(key)
                    all_results.append(r)

        # 按距离排序取前 top_k
        all_results.sort(key=lambda x: x.get("distance", float("inf")))
        return all_results[:top_k]

    # ═══════════════════════════════════════════════════════
    # 3. HyDE（假设文档嵌入）
    # ═══════════════════════════════════════════════════════
    async def generate_hypothetical_answer(self, question: str) -> str:
        """HyDE：用LLM生成假设答案"""
        import asyncio as _asyncio
        prompt = (
            "请根据你的知识，直接回答以下问题。回答要详细、完整，包含所有关键信息。"
            "这个回答将用于帮助检索相关文档，所以请尽可能具体。\n\n"
            "问题：" + question + "\n\n"
            "回答："
        )
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        config.LLM_BASE_URL + "/chat/completions",
                        headers={
                            "Authorization": "Bearer " + config.LLM_KEY,
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": config.LLM_MODEL,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 512,
                            "temperature": 0.5,
                            "stream": False
                        }
                    )
                    if resp.status_code == 429 or resp.status_code == 403:
                        await _asyncio.sleep(5 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
            except (httpx.HTTPStatusError, httpx.ConnectError):
                if attempt < 2:
                    await _asyncio.sleep(5 * (attempt + 1))
                    continue
            except Exception:
                break
        return ""

    async def retrieve_hyde(self, question: str, top_k: int = 5) -> list[dict]:
        """HyDE检索：生成假设答案，用假设答案做Embedding检索"""
        hypo = await self.generate_hypothetical_answer(question)
        if not hypo:
            return await self.retrieve(question, top_k=top_k)

        # 用假设答案做embedding
        hypo_embedding = self.embedding.embed_text(hypo)
        results = self.vector_store.query(hypo_embedding, top_k=top_k)

        # 同时用原问题也检索一次，合并结果
        original_results = await self.retrieve(question, top_k=top_k)

        seen_ids = set()
        merged = []
        for r in results + original_results:
            doc_id = r.get("metadata", {}).get("doc_id", "")
            idx = r.get("metadata", {}).get("index", "")
            key = doc_id + "_" + str(idx)
            if key not in seen_ids:
                seen_ids.add(key)
                merged.append(r)

        merged.sort(key=lambda x: x.get("distance", float("inf")))
        return merged[:top_k]

    # ═══════════════════════════════════════════════════════
    # 4. Re-ranking（重排序）
    # ═══════════════════════════════════════════════════════
    def re_rank(self, question: str, results: list[dict]) -> list[dict]:
        """轻量级Re-ranking：基于关键词匹配+文本长度对结果重新排序"""
        question_words = set(question.lower().split())
        scored = []

        for r in results:
            text = r.get("text", "").lower()
            # 关键词匹配得分
            match_count = sum(1 for w in question_words if w in text and len(w) > 1)
            # 长度得分（适度偏好中等长度）
            length_score = min(len(text) / 500, 2.0)
            # 原始向量距离得分（越小越好，取倒数）
            distance = r.get("distance", 1.0)
            distance_score = 1.0 / (distance + 0.1)

            # 综合得分
            total_score = match_count * 0.3 + length_score * 0.2 + distance_score * 0.5
            scored.append((total_score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored]

    # ═══════════════════════════════════════════════════════
    # 高级检索：组合多种优化策略
    # ═══════════════════════════════════════════════════════
    async def retrieve_advanced(
        self,
        question: str,
        top_k: int = 5,
        use_multi_query: bool = False,
        use_hyde: bool = False,
        use_re_rank: bool = False,
    ) -> list[dict]:
        """
        高级检索接口，支持组合多种优化策略：
        - multi_query: 生成多个查询变体扩大召回
        - hyde: 用假设答案做embedding检索
        - re_rank: 检索后重排序
        """
        if use_multi_query and use_hyde:
            # Multi-Query + HyDE 组合：每个查询变体都用HyDE
            queries = await self.generate_multi_queries(question, n=2)
            all_results = []
            seen_ids = set()
            for q in queries:
                hypo = await self.generate_hypothetical_answer(q)
                q_text = hypo if hypo else q
                q_emb = self.embedding.embed_text(q_text)
                results = self.vector_store.query(q_emb, top_k=top_k)
                for r in results:
                    doc_id = r.get("metadata", {}).get("doc_id", "")
                    idx = r.get("metadata", {}).get("index", "")
                    key = doc_id + "_" + str(idx)
                    if key not in seen_ids:
                        seen_ids.add(key)
                        all_results.append(r)
            all_results.sort(key=lambda x: x.get("distance", float("inf")))
            results = all_results[:top_k]
        elif use_multi_query:
            results = await self.retrieve_multi_query(question, top_k=top_k, n_queries=3)
        elif use_hyde:
            results = await self.retrieve_hyde(question, top_k=top_k)
        else:
            results = await self.retrieve(question, top_k=top_k)

        if use_re_rank:
            results = self.re_rank(question, results)

        return results
