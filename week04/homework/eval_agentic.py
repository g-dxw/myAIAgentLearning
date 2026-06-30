"""Agentic RAG 检索评测：对比基础 RAG vs Agentic RAG 在 9 个失败用例上的表现"""
import asyncio, os, sys, time
sys.path.insert(0, os.getcwd()); os.chdir(os.getcwd())

import core.config as config
config.CHUNK_SIZE = 1500
config.CHUNK_OVERLAP = 200
config.RETRIEVAL_TOP_K = 15

from core.embedding import Embedding
from rag.vector_store import VectorStore
from rag.agentic_pipeline import AgenticRAGPipeline

# 之前失败的 9 个用例
FAIL_CASES = [
    {"q": "Python 如何创建和使用虚拟环境？", "kws": ["venv", "activate", "pip install"]},
    {"q": "FastAPI 怎么启动开发服务器？", "kws": ["uvicorn", "--reload"]},
    {"q": "FastAPI 异步路由处理函数用什么关键字定义？", "kws": ["async def"]},
    {"q": "FastAPI 怎么实现 SSE 流式响应？", "kws": ["StreamingResponse", "text/event-stream"]},
    {"q": "FastAPI 自动生成的 API 文档怎么访问？", "kws": ["/docs", "/redoc"]},
    {"q": "FastAPI 中如何定义路径参数和查询参数？", "kws": ["路径参数", "查询参数"]},
    {"q": "RAG 系统中常用的 Embedding 模型有哪些？", "kws": ["text-embedding", "nomic-embed", "bge"]},
    {"q": "RAG 中向量相似度通常用什么方法计算？", "kws": ["余弦相似度", "cosine"]},
    {"q": "RAG 系统的评估指标有哪些？", "kws": ["召回率", "精确率", "忠实度"]},
]

async def main():
    embedding = Embedding()
    vs = VectorStore(config.CHROMA_PATH)
    agentic = AgenticRAGPipeline()

    print("=" * 65)
    print("Agentic RAG vs 基础 RAG 检索对比 (9个失败用例)")
    print("=" * 65)

    base_pass = 0
    agent_pass = 0

    for i, tc in enumerate(FAIL_CASES, 1):
        q = tc["q"]
        kws = tc["kws"]

        # 基础检索
        emb = embedding.embed_text(q)
        base_results = vs.query(emb, top_k=15)
        base_text = " ".join(r.get("text", "") for r in base_results)
        base_matched = [kw for kw in kws if kw.lower() in base_text.lower()]
        base_ratio = len(base_matched) / len(kws)
        base_ok = base_ratio >= 0.3

        # Agentic 检索
        agent_result = await agentic._agent_retrieve(q, 15)
        agent_results = agent_result["contexts"]
        agent_text = " ".join(r.get("text", "") for r in agent_results)
        agent_matched = [kw for kw in kws if kw.lower() in agent_text.lower()]
        agent_ratio = len(agent_matched) / len(kws)
        agent_ok = agent_ratio >= 0.3

        if base_ok: base_pass += 1
        if agent_ok: agent_pass += 1

        mark_b = "PASS" if base_ok else "FAIL"
        mark_a = "PASS" if agent_ok else "FAIL"
        arrow = "<<<" if agent_ok and not base_ok else ""

        print("[{}] Q: {}".format(i, q[:35]))
        print("    基础: {} ({}/{})  Agentic: {} ({}/{}) rounds={} {} {}".format(
            mark_b, len(base_matched), len(kws),
            mark_a, len(agent_matched), len(kws),
            agent_result["rounds"], agent_result["best_score"], arrow))

        # 打印 Agent 日志
        for log in agent_result["log"]:
            print("      R{}: {} score={} cov={}".format(
                log["round"], log["strategy"], log["score"], log["coverage"]))

    print("\n" + "=" * 65)
    print("基础 RAG: {}/9 = {:.0f}%".format(base_pass, base_pass/9*100))
    print("Agentic RAG: {}/9 = {:.0f}%".format(agent_pass, agent_pass/9*100))
    print("提升: +{} 个用例".format(agent_pass - base_pass))
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
