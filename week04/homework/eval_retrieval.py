"""
纯检索质量评测（Recall@K + MRR）
不依赖 LLM 生成，只评测检索环节是否召回相关 chunk。
结果 100% 稳定可复现。
"""
import asyncio, os, sys, time
sys.path.insert(0, os.getcwd()); os.chdir(os.getcwd())

import core.config as config
config.CHUNK_SIZE = 1500
config.CHUNK_OVERLAP = 200
config.RETRIEVAL_TOP_K = 15
config.USE_MULTI_QUERY = False
config.USE_HYDE = False
config.USE_RE_RANK = False

from core.embedding import Embedding
from rag.vector_store import VectorStore
from rag.retriever import Retriever

# 测试用例：每个问题 + 期望命中的文档来源 + 关键词
TEST_CASES = [
    # ─── Python ───
    {"q": "Python 有哪些基本数据类型？", "src": "test_python_basics.md",
     "kws": ["int", "float", "str", "bool", "NoneType"]},
    {"q": "Python 的 list 和 tuple 有什么区别？", "src": "test_python_basics.md",
     "kws": ["可变", "不可变"]},
    {"q": "Python 中 *args 和 **kwargs 分别是什么？", "src": "test_python_basics.md",
     "kws": ["*args", "**kwargs", "位置参数", "关键字参数"]},
    {"q": "Python 怎么定义一个带默认参数的函数？", "src": "test_python_basics.md",
     "kws": ["def", "默认参数", "default"]},
    {"q": "Python 面向对象编程中 __init__ 方法的作用是什么？", "src": "test_python_basics.md",
     "kws": ["__init__", "构造函数", "初始化"]},
    {"q": "Python 的类方法装饰器 @classmethod 和 @staticmethod 有什么区别？", "src": "test_python_basics.md",
     "kws": ["@classmethod", "@staticmethod", "类方法", "静态方法"]},
    {"q": "Python 中如何读写文件？推荐用什么语句？", "src": "test_python_basics.md",
     "kws": ["open", "with"]},
    {"q": "Python 处理 JSON 数据用什么模块？", "src": "test_python_basics.md",
     "kws": ["json", "dump", "load"]},
    {"q": "Python 中 try-except-finally 分别什么时候执行？", "src": "test_python_basics.md",
     "kws": ["try", "except", "finally"]},
    {"q": "Python 如何创建和使用虚拟环境？", "src": "test_python_basics.md",
     "kws": ["venv", "activate", "pip install"]},
    {"q": "Python Lambda 表达式怎么写？", "src": "test_python_basics.md",
     "kws": ["lambda", "匿名函数"]},
    # ─── FastAPI ───
    {"q": "FastAPI 是基于哪两个核心库构建的？", "src": "test_fastapi_guide.md",
     "kws": ["Starlette", "Pydantic"]},
    {"q": "FastAPI 怎么启动开发服务器？", "src": "test_fastapi_guide.md",
     "kws": ["uvicorn", "--reload"]},
    {"q": "FastAPI 支持哪些 HTTP 请求方法？", "src": "test_fastapi_guide.md",
     "kws": ["GET", "POST", "PUT", "DELETE"]},
    {"q": "FastAPI 中如何用 Pydantic 定义请求体模型？", "src": "test_fastapi_guide.md",
     "kws": ["BaseModel", "pydantic"]},
    {"q": "FastAPI 的依赖注入用什么函数？", "src": "test_fastapi_guide.md",
     "kws": ["Depends", "依赖注入"]},
    {"q": "FastAPI 如何配置 CORS 中间件？", "src": "test_fastapi_guide.md",
     "kws": ["CORSMiddleware", "allow_origins"]},
    {"q": "FastAPI 异步路由处理函数用什么关键字定义？", "src": "test_fastapi_guide.md",
     "kws": ["async def"]},
    {"q": "FastAPI 怎么实现 SSE 流式响应？", "src": "test_fastapi_guide.md",
     "kws": ["StreamingResponse", "text/event-stream"]},
    {"q": "FastAPI 自动生成的 API 文档怎么访问？", "src": "test_fastapi_guide.md",
     "kws": ["/docs", "/redoc"]},
    {"q": "FastAPI 中如何定义路径参数和查询参数？", "src": "test_fastapi_guide.md",
     "kws": ["路径参数", "查询参数"]},
    # ─── RAG ───
    {"q": "RAG 的全称是什么？它解决 LLM 的哪些问题？", "src": "test_rag_introduction.md",
     "kws": ["Retrieval-Augmented Generation", "检索增强生成", "幻觉"]},
    {"q": "RAG 的基本流程包含哪三个阶段？", "src": "test_rag_introduction.md",
     "kws": ["索引", "检索", "生成"]},
    {"q": "RAG 系统中常用的 Embedding 模型有哪些？", "src": "test_rag_introduction.md",
     "kws": ["text-embedding", "nomic-embed", "bge-large-zh", "m3e"]},
    {"q": "RAG 中向量相似度通常用什么方法计算？", "src": "test_rag_introduction.md",
     "kws": ["余弦相似度", "cosine"]},
    {"q": "Chroma 向量数据库使用什么索引算法？", "src": "test_rag_introduction.md",
     "kws": ["HNSW"]},
    {"q": "RAG 中 chunk_size 推荐设置为多少？", "src": "test_rag_introduction.md",
     "kws": ["500", "1000"]},
    {"q": "RAG 中 chunk_overlap 的作用是什么？", "src": "test_rag_introduction.md",
     "kws": ["重叠", "overlap"]},
    {"q": "什么是 Query Rewriting？它在 RAG 中起什么作用？", "src": "test_rag_introduction.md",
     "kws": ["查询改写", "指代"]},
    {"q": "RAG 系统的评估指标有哪些？", "src": "test_rag_introduction.md",
     "kws": ["召回率", "精确率", "忠实度", "MRR"]},
    {"q": "RAG 的标准 Prompt 结构包含哪些要素？", "src": "test_rag_introduction.md",
     "kws": ["角色设定", "参考文档", "约束条件"]},
]


async def main():
    embedding = Embedding()
    vs = VectorStore(config.CHROMA_PATH)
    retriever = Retriever(embedding=embedding, vector_store=vs)

    print("=" * 65)
    print("检索质量评测 (Recall@15 + MRR)")
    print("参数: chunk_size=1500, overlap=200, top_k=15")
    print("=" * 65)

    results = []
    all_rr = []  # MRR 计算用

    for i, tc in enumerate(TEST_CASES, 1):
        q = tc["q"]
        kws = tc["kws"]
        src = tc["src"]

        # 检索
        query_emb = embedding.embed_text(q)
        retrieved = vs.query(query_emb, top_k=config.RETRIEVAL_TOP_K)

        # 检查每个关键词是否在检索结果中出现
        retrieved_text = " ".join(r.get("text", "") for r in retrieved)
        matched_kws = [kw for kw in kws if kw.lower() in retrieved_text.lower()]
        recall = len(matched_kws) / len(kws) if kws else 0

        # 计算 MRR（第一个包含任何关键词的结果的排名倒数）
        rr = 0
        for rank, r in enumerate(retrieved, 1):
            text = r.get("text", "").lower()
            if any(kw.lower() in text for kw in kws):
                rr = 1.0 / rank
                break
        all_rr.append(rr)

        # 检查来源是否正确
        correct_src = any(r.get("metadata", {}).get("doc_id", "") == src.replace(".", "_") for r in retrieved)

        passed = recall >= 0.3
        mark = "PASS" if passed else "FAIL"
        print("[{:2d}/31] {} Q: {}".format(i, mark, q[:38]))
        if not passed:
            print("        recall={:.0f}% ({}/{}) MRR={:.2f} src={}".format(
                recall*100, len(matched_kws), len(kws), rr, "Y" if correct_src else "N"))

        results.append({
            "passed": passed, "recall": recall, "rr": rr,
            "matched": len(matched_kws), "total_kws": len(kws), "correct_src": correct_src,
        })

    # 统计
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    accuracy = passed / total * 100
    avg_recall = sum(r["recall"] for r in results) / total * 100
    mrr = sum(all_rr) / len(all_rr)
    src_correct = sum(1 for r in results if r["correct_src"])

    print("\n" + "=" * 65)
    print("检索评测结果")
    print("=" * 65)
    print("  Recall 通过率: {}/{} = {:.1f}%".format(passed, total, accuracy))
    print("  平均 Recall:  {:.1f}%".format(avg_recall))
    print("  MRR:          {:.3f}".format(mrr))
    print("  来源准确率:   {}/{} = {:.1f}%".format(src_correct, total, src_correct/total*100))

    if accuracy >= 98:
        print("\n达标! 检索通过率 >= 98%")
    else:
        print("\n距 98% 还差 {:.1f}%".format(98 - accuracy))


if __name__ == "__main__":
    asyncio.run(main())
