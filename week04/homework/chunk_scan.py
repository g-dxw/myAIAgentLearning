import asyncio, gc, os, shutil, sys
sys.path.insert(0, os.getcwd()); os.chdir(os.getcwd())

from core.splitter import DocumentSplitter
from core.embedding import Embedding
from rag.vector_store import VectorStore
import core.config as config

CHUNK_SIZES = [2000, 3000, 5000, 8000]

async def test_chunk_size(cs):
    config.CHUNK_SIZE = cs
    config.CHUNK_OVERLAP = min(cs // 5, 500)
    config.RETRIEVAL_TOP_K = 15

    if os.path.exists(config.CHROMA_PATH):
        shutil.rmtree(config.CHROMA_PATH)

    splitter = DocumentSplitter(chunk_size=cs, chunk_overlap=config.CHUNK_OVERLAP, strategy="recursive")
    embedding = Embedding()
    vs = VectorStore(config.CHROMA_PATH)

    total = 0
    for fname in sorted(os.listdir("uploads")):
        fpath = os.path.join("uploads", fname)
        if not os.path.isfile(fpath): continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in [".md", ".txt"]: continue
        chunks = splitter.split(fpath)
        texts = [c["text"] for c in chunks]
        embs = await embedding.embed_batch_async(texts, concurrency=8)
        count = vs.add_chunks(fname.replace(".", "_"), chunks, embs)
        total += count

    # 快速检索测试（只测之前失败的9个用例）
    FAIL_QS = [
        ("Python 如何创建和使用虚拟环境？", ["venv", "activate"]),
        ("FastAPI 怎么启动开发服务器？", ["uvicorn", "--reload"]),
        ("FastAPI 异步路由处理函数用什么关键字定义？", ["async def"]),
        ("FastAPI 怎么实现 SSE 流式响应？", ["StreamingResponse", "text/event-stream"]),
        ("FastAPI 自动生成的 API 文档怎么访问？", ["/docs", "/redoc"]),
        ("FastAPI 中如何定义路径参数和查询参数？", ["路径参数", "查询参数"]),
        ("RAG 系统中常用的 Embedding 模型有哪些？", ["text-embedding", "nomic-embed", "bge"]),
        ("RAG 中向量相似度通常用什么方法计算？", ["余弦相似度", "cosine"]),
        ("RAG 系统的评估指标有哪些？", ["召回率", "精确率", "忠实度"]),
    ]

    passed = 0
    for q, kws in FAIL_QS:
        emb = embedding.embed_text(q)
        results = vs.query(emb, top_k=15)
        texts = " ".join(r.get("text", "") for r in results)
        matched = sum(1 for kw in kws if kw.lower() in texts.lower())
        if matched >= len(kws) * 0.3:
            passed += 1

    print("chunk_size={}: {} chunks, failed_q_pass={}/9".format(cs, total, passed))
    return cs, total, passed

async def main():
    for cs in CHUNK_SIZES:
        await test_chunk_size(cs)
        gc.collect()

asyncio.run(main())
