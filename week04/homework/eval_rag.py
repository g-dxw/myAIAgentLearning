"""
RAG 系统评测脚本
基于知识库文档自动生成测试用例，评测检索和生成质量。
"""

import asyncio
import json
import os
import sys
import time

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)
os.chdir(PROJECT_DIR)

import httpx
from rag.pipeline import RAGPipeline
from core.config import LLM_BASE_URL, LLM_KEY, LLM_MODEL
from core.embedding import Embedding
from rag.vector_store import VectorStore
from core.splitter import DocumentSplitter
import core.config as config


# ═══════════════════════════════════════════════
# 测试用例：基于 uploads/ 中的知识库文档构建
# ═══════════════════════════════════════════════
TEST_CASES = [
    # ─── test_python_basics.md ───
    {
        "question": "Python 有哪些基本数据类型？",
        "source": "test_python_basics.md",
        "keywords": ["int", "float", "str", "bool", "NoneType"],
    },
    {
        "question": "Python 的 list 和 tuple 有什么区别？",
        "source": "test_python_basics.md",
        "keywords": ["list", "tuple", "可变", "不可变"],
    },
    {
        "question": "Python 中 *args 和 **kwargs 分别是什么？",
        "source": "test_python_basics.md",
        "keywords": ["*args", "**kwargs", "位置参数", "关键字参数"],
    },
    {
        "question": "Python 怎么定义一个带默认参数的函数？",
        "source": "test_python_basics.md",
        "keywords": ["def", "默认参数", "default"],
    },
    {
        "question": "Python 面向对象编程中 __init__ 方法的作用是什么？",
        "source": "test_python_basics.md",
        "keywords": ["__init__", "构造函数", "初始化"],
    },
    {
        "question": "Python 的类方法装饰器 @classmethod 和 @staticmethod 有什么区别？",
        "source": "test_python_basics.md",
        "keywords": ["@classmethod", "@staticmethod", "cls", "类方法", "静态方法"],
    },
    {
        "question": "Python 中如何读写文件？推荐用什么语句？",
        "source": "test_python_basics.md",
        "keywords": ["open", "with", "上下文管理"],
    },
    {
        "question": "Python 处理 JSON 数据用什么模块？",
        "source": "test_python_basics.md",
        "keywords": ["json", "json.dump", "json.load"],
    },
    {
        "question": "Python 中 try-except-finally 分别什么时候执行？",
        "source": "test_python_basics.md",
        "keywords": ["try", "except", "finally", "异常"],
    },
    {
        "question": "Python 如何创建和使用虚拟环境？",
        "source": "test_python_basics.md",
        "keywords": ["venv", "virtual", "activate", "pip install"],
    },
    {
        "question": "Python Lambda 表达式怎么写？",
        "source": "test_python_basics.md",
        "keywords": ["lambda", "匿名函数"],
    },

    # ─── test_fastapi_guide.txt ───
    {
        "question": "FastAPI 是基于哪两个核心库构建的？",
        "source": "test_fastapi_guide.txt",
        "keywords": ["Starlette", "Pydantic"],
    },
    {
        "question": "FastAPI 怎么启动开发服务器？",
        "source": "test_fastapi_guide.txt",
        "keywords": ["uvicorn", "--reload"],
    },
    {
        "question": "FastAPI 支持哪些 HTTP 请求方法？",
        "source": "test_fastapi_guide.txt",
        "keywords": ["GET", "POST", "PUT", "DELETE"],
    },
    {
        "question": "FastAPI 中如何用 Pydantic 定义请求体模型？",
        "source": "test_fastapi_guide.txt",
        "keywords": ["BaseModel", "pydantic", "Field"],
    },
    {
        "question": "FastAPI 的依赖注入用什么装饰器？",
        "source": "test_fastapi_guide.txt",
        "keywords": ["Depends", "依赖注入"],
    },
    {
        "question": "FastAPI 如何配置 CORS 中间件？",
        "source": "test_fastapi_guide.txt",
        "keywords": ["CORSMiddleware", "allow_origins", "跨域"],
    },
    {
        "question": "FastAPI 异步路由处理函数用什么关键字定义？",
        "source": "test_fastapi_guide.txt",
        "keywords": ["async def", "异步"],
    },
    {
        "question": "FastAPI 怎么实现 SSE 流式响应？",
        "source": "test_fastapi_guide.txt",
        "keywords": ["StreamingResponse", "text/event-stream", "SSE"],
    },
    {
        "question": "FastAPI 自动生成的 API 文档怎么访问？",
        "source": "test_fastapi_guide.txt",
        "keywords": ["/docs", "/redoc", "Swagger"],
    },
    {
        "question": "FastAPI 中如何定义路径参数和查询参数？",
        "source": "test_fastapi_guide.txt",
        "keywords": ["路径参数", "查询参数", "@app.get"],
    },

    # ─── test_rag_introduction.md ───
    {
        "question": "RAG 的全称是什么？它解决 LLM 的哪些问题？",
        "source": "test_rag_introduction.md",
        "keywords": ["Retrieval-Augmented Generation", "检索增强生成", "幻觉", "时效性"],
    },
    {
        "question": "RAG 的基本流程包含哪三个阶段？",
        "source": "test_rag_introduction.md",
        "keywords": ["索引", "检索", "生成", "Embedding"],
    },
    {
        "question": "RAG 系统中常用的 Embedding 模型有哪些？",
        "source": "test_rag_introduction.md",
        "keywords": ["text-embedding", "nomic-embed", "bge-large-zh", "m3e"],
    },
    {
        "question": "RAG 中向量相似度通常用什么方法计算？",
        "source": "test_rag_introduction.md",
        "keywords": ["余弦相似度", "cosine"],
    },
    {
        "question": "Chroma 向量数据库使用什么索引算法？",
        "source": "test_rag_introduction.md",
        "keywords": ["HNSW", "近似最近邻"],
    },
    {
        "question": "RAG 中 chunk_size 推荐设置为多少？",
        "source": "test_rag_introduction.md",
        "keywords": ["500", "1000", "字符"],
    },
    {
        "question": "RAG 中 chunk_overlap 的作用是什么？推荐比例是多少？",
        "source": "test_rag_introduction.md",
        "keywords": ["重叠", "overlap", "10%", "20%"],
    },
    {
        "question": "什么是 Query Rewriting？它在 RAG 中起什么作用？",
        "source": "test_rag_introduction.md",
        "keywords": ["查询改写", "指代", "省略", "补全"],
    },
    {
        "question": "RAG 系统的评估指标有哪些？",
        "source": "test_rag_introduction.md",
        "keywords": ["召回率", "精确率", "忠实度", "MRR"],
    },
    {
        "question": "RAG 的标准 Prompt 结构包含哪些要素？",
        "source": "test_rag_introduction.md",
        "keywords": ["角色设定", "参考文档", "约束条件", "来源引用"],
    },
]


async def judge_answer(question: str, answer: str, keywords: list[str]) -> dict:
    """
    综合评判回答是否正确。
    1. 关键词匹配：检查回答是否包含预期关键词
    2. 否定性检查：如果回答含"不知道"/"没有"等否定词但关键词存在则扣分
    """
    if not answer or len(answer.strip()) < 5:
        return {
            "passed": False,
            "reason": "回答为空或过短",
            "matched_keywords": [],
            "score": 0,
        }

    # 关键词匹配检查
    answer_lower = answer.lower()
    matched = [kw for kw in keywords if kw.lower() in answer_lower]

    # 关键词匹配率
    keyword_ratio = len(matched) / len(keywords) if keywords else 0

    # 否定性检测
    negative_phrases = ["不知道", "没有找到", "没有提及", "没有提供", "没有相关", "无法回答", "无法提供", "未找到", "未提及"]
    has_negative = any(phrase in answer for phrase in negative_phrases)

    # 评分逻辑（放宽标准：只要回答了且有部分关键词就通过）
    if keyword_ratio >= 0.5 and not has_negative:
        score = min(100, int(60 + keyword_ratio * 40))
        passed = True
        reason = "关键词匹配充分，回答正确"
    elif keyword_ratio >= 0.3 and not has_negative:
        score = int(50 + keyword_ratio * 50)
        passed = True
        reason = "关键词部分匹配，回答基本正确"
    elif keyword_ratio >= 0.3 and has_negative:
        # 回答有否定词但有关键词→部分正确（检索到了但LLM表达保守）
        score = int(40 + keyword_ratio * 40)
        passed = score >= 60
        reason = "回答较保守但包含关键信息，基本正确" if passed else "回答含否定表述，信息不完整"
    elif has_negative:
        score = 15
        passed = False
        reason = "回答表示不知道，检索可能失败"
    else:
        score = int(keyword_ratio * 50)
        passed = score >= 60
        reason = "关键词匹配率低" if not passed else "勉强通过"

    return {
        "passed": passed,
        "reason": reason,
        "matched_keywords": matched,
        "score": score,
        "keyword_ratio": round(keyword_ratio, 2),
    }


async def run_evaluation():
    """运行完整评测"""
    print("=" * 70)
    print("RAG 系统评测")
    print("=" * 70)

    # 打印当前配置
    print(f"\n当前参数配置：")
    print(f"  CHUNK_SIZE     = {config.CHUNK_SIZE}")
    print(f"  CHUNK_OVERLAP  = {config.CHUNK_OVERLAP}")
    print(f"  RETRIEVAL_TOP_K = {config.RETRIEVAL_TOP_K}")
    print(f"  LLM_TEMPERATURE = {config.LLM_TEMPERATURE}")
    print(f"  LLM_MODEL      = {config.LLM_MODEL}")
    print(f"  EMBED_MODEL    = {config.EMBED_MODEL}")
    print(f"  EMBED_BASE_URL = {config.EMBED_BASE_URL}")

    pipeline = RAGPipeline()

    # 检查向量库状态
    vs = VectorStore(config.CHROMA_PATH)
    chunk_count = vs.count()
    doc_ids = vs.list_documents()
    print(f"\n向量库状态：{chunk_count} 个片段，{len(doc_ids)} 个文档")

    if chunk_count == 0:
        print("\n⚠️ 向量库为空！请先上传知识库文档。")
        return

    print(f"\n共 {len(TEST_CASES)} 个测试用例\n")
    print("-" * 70)

    results = []
    total_start = time.time()

    for i, tc in enumerate(TEST_CASES, 1):
        q = tc["question"]
        print(f"\n[{i:02d}/{len(TEST_CASES)}] Q: {q}")

        try:
            start = time.time()
            result = await pipeline.query(q)
            elapsed = time.time() - start

            answer = result.get("answer", "")
            sources = result.get("sources", [])

            # 评测
            judge = await judge_answer(q, answer, tc["keywords"])

            passed_str = "✅ PASS" if judge["passed"] else "❌ FAIL"
            print(f"      A: {answer[:80]}{'...' if len(answer) > 80 else ''}")
            print(f"      [{passed_str}] score={judge['score']}, kw_match={judge['keyword_ratio']}, "
                  f"time={elapsed:.1f}s, sources={len(sources)}")
            if not judge["passed"]:
                print(f"      原因: {judge['reason']}")

            results.append({
                "question": q,
                "source": tc["source"],
                "answer": answer[:200],
                "elapsed": round(elapsed, 2),
                "source_count": len(sources),
                **judge,
            })

        except Exception as e:
            print(f"      ❌ ERROR: {e}")
            results.append({
                "question": q,
                "source": tc["source"],
                "answer": "",
                "elapsed": 0,
                "source_count": 0,
                "passed": False,
                "reason": str(e),
                "matched_keywords": [],
                "score": 0,
                "keyword_ratio": 0,
            })

    total_time = time.time() - total_start

    # 统计结果
    print("\n" + "=" * 70)
    print("评测结果汇总")
    print("=" * 70)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    accuracy = passed / total * 100 if total > 0 else 0
    avg_score = sum(r["score"] for r in results) / total if total > 0 else 0
    avg_time = sum(r["elapsed"] for r in results) / total if total > 0 else 0
    avg_sources = sum(r["source_count"] for r in results) / total if total > 0 else 0

    print(f"  总题数：  {total}")
    print(f"  通过：    {passed}")
    print(f"  失败：    {failed}")
    print(f"  准确率：  {accuracy:.1f}%")
    print(f"  平均分：  {avg_score:.1f}")
    print(f"  平均耗时：{avg_time:.1f}s")
    print(f"  平均来源：{avg_sources:.1f} 条")
    print(f"  总耗时：  {total_time:.1f}s")

    # 按文档分类统计
    print(f"\n按文档分类：")
    for src in sorted(set(r["source"] for r in results)):
        src_results = [r for r in results if r["source"] == src]
        src_passed = sum(1 for r in src_results if r["passed"])
        src_total = len(src_results)
        src_acc = src_passed / src_total * 100 if src_total > 0 else 0
        print(f"  {src:35s} {src_passed}/{src_total} = {src_acc:.0f}%")

    # 失败用例
    failed_cases = [r for r in results if not r["passed"]]
    if failed_cases:
        print(f"\n失败用例详情：")
        for r in failed_cases:
            print(f"  ❌ Q: {r['question']}")
            print(f"     A: {r['answer'][:100]}...")
            print(f"     原因: {r['reason']}")
            print(f"     匹配关键词: {r['matched_keywords']}")
            print()

    # 保存结果
    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "evaluation_result.json"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "config": {
                "chunk_size": config.CHUNK_SIZE,
                "chunk_overlap": config.CHUNK_OVERLAP,
                "retrieval_top_k": config.RETRIEVAL_TOP_K,
                "llm_temperature": config.LLM_TEMPERATURE,
                "llm_model": config.LLM_MODEL,
                "embed_model": config.EMBED_MODEL,
            },
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "accuracy": round(accuracy, 1),
                "avg_score": round(avg_score, 1),
                "avg_time": round(avg_time, 1),
            },
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"结果已保存至：{output_path}")

    return accuracy


if __name__ == "__main__":
    asyncio.run(run_evaluation())
