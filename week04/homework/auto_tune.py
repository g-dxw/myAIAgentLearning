"""
RAG 自动调参闭环评测系统

自动评测 → 分析失败原因 → 调整参数 → 重新索引 → 再评测
循环直到准确率达到目标或达到最大迭代次数。
"""

import asyncio
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Optional

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

import core.config as config
from core.embedding import Embedding
from core.splitter import DocumentSplitter
from rag.vector_store import VectorStore
from rag.pipeline import RAGPipeline


# ═══════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════
TEST_CASES = [
    # ─── test_python_basics.md ───
    {"question": "Python 有哪些基本数据类型？", "source": "test_python_basics.md",
     "keywords": ["int", "float", "str", "bool"]},
    {"question": "Python 的 list 和 tuple 有什么区别？", "source": "test_python_basics.md",
     "keywords": ["可变", "不可变"]},
    {"question": "Python 中 *args 和 **kwargs 分别是什么？", "source": "test_python_basics.md",
     "keywords": ["*args", "**kwargs", "位置参数", "关键字参数"]},
    {"question": "Python 怎么定义一个带默认参数的函数？", "source": "test_python_basics.md",
     "keywords": ["def", "默认参数"]},
    {"question": "Python 面向对象编程中 __init__ 方法的作用是什么？", "source": "test_python_basics.md",
     "keywords": ["__init__", "构造函数", "初始化"]},
    {"question": "Python 的类方法装饰器 @classmethod 和 @staticmethod 有什么区别？", "source": "test_python_basics.md",
     "keywords": ["@classmethod", "@staticmethod", "类方法", "静态方法"]},
    {"question": "Python 中如何读写文件？推荐用什么语句？", "source": "test_python_basics.md",
     "keywords": ["open", "with"]},
    {"question": "Python 处理 JSON 数据用什么模块？", "source": "test_python_basics.md",
     "keywords": ["json", "json.dump", "json.load"]},
    {"question": "Python 中 try-except-finally 分别什么时候执行？", "source": "test_python_basics.md",
     "keywords": ["try", "except", "finally"]},
    {"question": "Python 如何创建和使用虚拟环境？", "source": "test_python_basics.md",
     "keywords": ["venv", "activate"]},
    {"question": "Python Lambda 表达式怎么写？", "source": "test_python_basics.md",
     "keywords": ["lambda", "匿名函数"]},

    # ─── test_fastapi_guide.md ───
    {"question": "FastAPI 是基于哪两个核心库构建的？", "source": "test_fastapi_guide.md",
     "keywords": ["Starlette", "Pydantic"]},
    {"question": "FastAPI 怎么启动开发服务器？", "source": "test_fastapi_guide.md",
     "keywords": ["uvicorn", "--reload"]},
    {"question": "FastAPI 支持哪些 HTTP 请求方法？", "source": "test_fastapi_guide.md",
     "keywords": ["GET", "POST", "PUT", "DELETE"]},
    {"question": "FastAPI 中如何用 Pydantic 定义请求体模型？", "source": "test_fastapi_guide.md",
     "keywords": ["BaseModel", "pydantic"]},
    {"question": "FastAPI 的依赖注入用什么函数？", "source": "test_fastapi_guide.md",
     "keywords": ["Depends", "依赖注入"]},
    {"question": "FastAPI 如何配置 CORS 中间件？", "source": "test_fastapi_guide.md",
     "keywords": ["CORSMiddleware", "跨域"]},
    {"question": "FastAPI 异步路由处理函数用什么关键字定义？", "source": "test_fastapi_guide.md",
     "keywords": ["async def"]},
    {"question": "FastAPI 怎么实现 SSE 流式响应？", "source": "test_fastapi_guide.md",
     "keywords": ["SSE", "Server-Sent Events", "StreamingResponse", "流式响应"]},
    {"question": "FastAPI 自动生成的 API 文档怎么访问？", "source": "test_fastapi_guide.md",
     "keywords": ["/docs", "/redoc", "Swagger", "ReDoc", "自动生成"]},
    {"question": "FastAPI 中如何定义路径参数和查询参数？", "source": "test_fastapi_guide.md",
     "keywords": ["路径参数", "查询参数"]},

    # ─── test_rag_introduction.md ───
    {"question": "RAG 的全称是什么？它解决 LLM 的哪些问题？", "source": "test_rag_introduction.md",
     "keywords": ["Retrieval-Augmented Generation", "检索增强生成", "幻觉"]},
    {"question": "RAG 的基本流程包含哪三个阶段？", "source": "test_rag_introduction.md",
     "keywords": ["索引", "检索", "生成"]},
    {"question": "RAG 系统中常用的 Embedding 模型有哪些？", "source": "test_rag_introduction.md",
     "keywords": ["text-embedding", "nomic-embed", "bge", "m3e", "OpenAI", "Embedding"]},
    {"question": "RAG 中向量相似度通常用什么方法计算？", "source": "test_rag_introduction.md",
     "keywords": ["余弦相似度", "cosine", "相似度", "向量"]},
    {"question": "Chroma 向量数据库使用什么索引算法？", "source": "test_rag_introduction.md",
     "keywords": ["HNSW"]},
    {"question": "RAG 中 chunk_size 推荐设置为多少？", "source": "test_rag_introduction.md",
     "keywords": ["500", "1000"]},
    {"question": "RAG 中 chunk_overlap 的作用是什么？", "source": "test_rag_introduction.md",
     "keywords": ["重叠", "overlap", "边界"]},
    {"question": "什么是 Query Rewriting？它在 RAG 中起什么作用？", "source": "test_rag_introduction.md",
     "keywords": ["查询改写", "Query Rewriting", "指代", "改写"]},
    {"question": "RAG 系统的评估指标有哪些？", "source": "test_rag_introduction.md",
     "keywords": ["召回率", "精确率", "忠实度", "MRR", "评估"]},
    {"question": "RAG 的标准 Prompt 结构包含哪些要素？", "source": "test_rag_introduction.md",
     "keywords": ["角色设定", "参考文档", "约束条件", "来源引用", "Prompt"]},
]


# ═══════════════════════════════════════════════
# 评测函数
# ═══════════════════════════════════════════════
NEGATIVE_PHRASES = ["不知道", "没有找到", "没有提及", "没有提供", "没有相关",
                     "无法回答", "无法提供", "未找到", "未提及", "未详细"]


def judge_answer(question: str, answer: str, keywords: list) -> dict:
    """评判回答质量"""
    if not answer or len(answer.strip()) < 5:
        return {"passed": False, "reason": "回答为空", "matched": [], "score": 0}

    answer_lower = answer.lower()
    matched = [kw for kw in keywords if kw.lower() in answer_lower]
    ratio = len(matched) / len(keywords) if keywords else 0
    has_neg = any(p in answer for p in NEGATIVE_PHRASES)

    if ratio >= 0.5 and not has_neg:
        return {"passed": True, "reason": "匹配充分", "matched": matched,
                "score": min(100, int(60 + ratio * 40)), "kw_ratio": ratio}
    elif ratio >= 0.3 and not has_neg:
        return {"passed": True, "reason": "部分匹配", "matched": matched,
                "score": int(50 + ratio * 50), "kw_ratio": ratio}
    elif ratio >= 0.3 and has_neg:
        score = int(40 + ratio * 40)
        return {"passed": score >= 60, "reason": "保守但有关键词",
                "matched": matched, "score": score, "kw_ratio": ratio}
    elif has_neg:
        return {"passed": False, "reason": "说不知道", "matched": matched,
                "score": 15, "kw_ratio": ratio}
    else:
        score = int(ratio * 50)
        return {"passed": score >= 60, "reason": "匹配率低",
                "matched": matched, "score": score, "kw_ratio": ratio}


async def run_evaluation(pipeline: RAGPipeline, verbose: bool = True) -> dict:
    """运行评测，返回详细结果"""
    results = []
    for i, tc in enumerate(TEST_CASES, 1):
        q = tc["question"]
        try:
            result = await pipeline.query(q)
            answer = result.get("answer", "")
            judge = judge_answer(q, answer, tc["keywords"])

            if verbose:
                mark = "PASS" if judge["passed"] else "FAIL"
                print("[{}/31] {} Q: {}".format(i, mark, q[:50]))
                if not judge["passed"]:
                    print("       原因: {} | 匹配: {}/{} | {}".format(
                        judge["reason"], len(judge["matched"]), len(tc["keywords"]),
                        judge.get("kw_ratio", 0)))

            results.append({
                "question": q, "source": tc["source"],
                "answer": answer[:200], **judge,
                "elapsed": result.get("elapsed", 0),
            })
        except Exception as e:
            if verbose:
                print("[{}/31] ERROR Q: {} -> {}".format(i, q[:50], str(e)[:80]))
            results.append({
                "question": q, "source": tc["source"], "answer": "",
                "passed": False, "reason": str(e), "matched": [],
                "score": 0, "kw_ratio": 0, "elapsed": 0,
            })

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    accuracy = passed / total * 100 if total > 0 else 0
    avg_score = sum(r["score"] for r in results) / total if total > 0 else 0

    # 按来源分类
    by_source = {}
    for r in results:
        src = r["source"]
        if src not in by_source:
            by_source[src] = {"passed": 0, "total": 0}
        by_source[src]["total"] += 1
        if r["passed"]:
            by_source[src]["passed"] += 1

    # 失败分析
    failed_neg = sum(1 for r in results if not r["passed"] and any(p in r.get("answer", "") for p in NEGATIVE_PHRASES))
    failed_low_kw = sum(1 for r in results if not r["passed"] and r.get("kw_ratio", 0) < 0.3)

    return {
        "total": total, "passed": passed, "accuracy": round(accuracy, 1),
        "avg_score": round(avg_score, 1),
        "by_source": by_source,
        "failed_negative": failed_neg,  # LLM 说"不知道"
        "failed_low_kw": failed_low_kw,  # 关键词匹配太低
        "details": results,
    }


# ═══════════════════════════════════════════════
# 自动调参策略
# ═══════════════════════════════════════════════
PARAM_GRID = [
    # (chunk_size, chunk_overlap, top_k, description)
    (1500, 200, 15, "基础配置"),
    (2000, 300, 15, "增大chunk"),
    (2000, 300, 20, "增大chunk+top_k"),
    (3000, 400, 20, "更大chunk"),
    (3000, 400, 30, "更大chunk+更多top_k"),
    (1500, 200, 30, "小chunk+大量召回"),
    (2000, 400, 25, "大overlap"),
    (4000, 500, 30, "最大chunk+最大召回"),
]


async def reindex_with_params(chunk_size: int, chunk_overlap: int) -> int:
    """用给定参数重新索引，返回 chunk 数量"""
    # 强制删除旧向量库（Windows 下需要重试）
    import gc
    for attempt in range(5):
        try:
            if os.path.exists(config.CHROMA_PATH):
                gc.collect()
                shutil.rmtree(config.CHROMA_PATH)
            break
        except PermissionError:
            gc.collect()
            await asyncio.sleep(2)

    splitter = DocumentSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap, strategy="recursive")
    embedding = Embedding()
    vs = VectorStore(config.CHROMA_PATH)

    total = 0
    for fname in sorted(os.listdir("uploads")):
        fpath = os.path.join("uploads", fname)
        if not os.path.isfile(fpath):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in [".md", ".txt", ".html"]:
            continue
        chunks = splitter.split(fpath)
        texts = [c["text"] for c in chunks]
        embeddings = await embedding.embed_batch_async(texts, concurrency=8)
        doc_id = fname.replace(".", "_")
        count = vs.add_chunks(doc_id, chunks, embeddings)
        total += count

    return total


async def auto_tune(target_accuracy: float = 90.0, max_iterations: int = 8):
    """自动调参闭环"""
    print("=" * 70)
    print("RAG 自动调参闭环评测系统")
    print("目标准确率: {}%  最大迭代: {}".format(target_accuracy, max_iterations))
    print("=" * 70)

    best_accuracy = 0
    best_params = None
    history = []

    for iteration in range(1, max_iterations + 1):
        print("\n" + "=" * 70)
        print("第 {} 轮迭代".format(iteration))
        print("=" * 70)

        # 选择参数（第一轮用默认，后续根据失败分析选择）
        if iteration == 1:
            chunk_size, chunk_overlap, top_k, desc = PARAM_GRID[0]
        elif iteration - 1 < len(PARAM_GRID):
            chunk_size, chunk_overlap, top_k, desc = PARAM_GRID[iteration - 1]
        else:
            # 超过网格后，使用历史最佳参数的微调
            if best_params:
                chunk_size = best_params["chunk_size"]
                chunk_overlap = best_params["chunk_overlap"]
                top_k = min(50, best_params["top_k"] + 5)
                desc = "基于最佳参数微调 top_k={}".format(top_k)
            else:
                break

        # 应用参数
        print("参数: chunk_size={}, chunk_overlap={}, top_k={} ({})".format(
            chunk_size, chunk_overlap, top_k, desc))

        config.CHUNK_SIZE = chunk_size
        config.CHUNK_OVERLAP = chunk_overlap
        config.RETRIEVAL_TOP_K = top_k

        # 重新索引
        print("正在重新索引...")
        t0 = time.time()
        chunk_count = await reindex_with_params(chunk_size, chunk_overlap)
        index_time = time.time() - t0
        print("索引完成: {} 个片段, 耗时 {:.1f}s".format(chunk_count, index_time))

        # 运行评测
        print("正在评测...")
        t0 = time.time()
        pipeline = RAGPipeline()
        eval_result = await run_evaluation(pipeline, verbose=True)
        eval_time = time.time() - t0

        accuracy = eval_result["accuracy"]
        print("\n--- 第 {} 轮结果 ---".format(iteration))
        print("准确率: {:.1f}%  平均分: {:.1f}  评测耗时: {:.1f}s".format(
            accuracy, eval_result["avg_score"], eval_time))
        for src, info in eval_result["by_source"].items():
            acc = info["passed"] / info["total"] * 100 if info["total"] > 0 else 0
            print("  {}: {}/{} = {:.0f}%".format(src, info["passed"], info["total"], acc))
        print("失败分析: LLM说不知道={}  关键词匹配低={}".format(
            eval_result["failed_negative"], eval_result["failed_low_kw"]))

        # 记录历史
        record = {
            "iteration": iteration,
            "chunk_size": chunk_size, "chunk_overlap": chunk_overlap,
            "top_k": top_k, "chunk_count": chunk_count,
            "accuracy": accuracy, "avg_score": eval_result["avg_score"],
            "eval_time": round(eval_time), "index_time": round(index_time),
            "desc": desc,
        }
        history.append(record)

        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_params = record.copy()
            print(">>> 新最佳! 准确率 {:.1f}%".format(best_accuracy))

        # 达标则退出
        if accuracy >= target_accuracy:
            print("\n" + "=" * 70)
            print("达标! 准确率 {:.1f}% >= 目标 {:.1f}%".format(accuracy, target_accuracy))
            print("=" * 70)
            break
        else:
            print("未达标，继续下一轮...")

    # 最终汇总
    print("\n" + "=" * 70)
    print("自动调参完成")
    print("=" * 70)
    print("最佳参数: chunk_size={}, chunk_overlap={}, top_k={}".format(
        best_params["chunk_size"], best_params["chunk_overlap"], best_params["top_k"]))
    print("最佳准确率: {:.1f}%".format(best_accuracy))
    print("\n迭代历史:")
    for h in history:
        marker = " <<< BEST" if h["accuracy"] == best_accuracy else ""
        print("  #{}: {:.1f}% (chunk={}, overlap={}, top_k={}, chunks={}){}".format(
            h["iteration"], h["accuracy"], h["chunk_size"], h["chunk_overlap"],
            h["top_k"], h["chunk_count"], marker))

    # 保存结果
    output = {
        "target": target_accuracy,
        "best_params": best_params,
        "best_accuracy": best_accuracy,
        "history": history,
    }
    output_path = os.path.join(PROJECT_DIR, "auto_tune_result.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\n结果已保存至: " + output_path)

    # 应用最佳参数到 config
    if best_params:
        print("\n正在应用最佳参数到 config.py ...")
        apply_best_params(best_params)


def apply_best_params(params: dict):
    """将最佳参数写回 config.py"""
    config_path = os.path.join(PROJECT_DIR, "core", "config.py")
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 替换参数值
    import re
    content = re.sub(
        r'CHUNK_SIZE = int\(os\.getenv\("CHUNK_SIZE",\s*"\d+"\)\)',
        'CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "{}"))'.format(params["chunk_size"]),
        content
    )
    content = re.sub(
        r'CHUNK_OVERLAP = int\(os\.getenv\("CHUNK_OVERLAP",\s*"\d+"\)\)',
        'CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "{}"))'.format(params["chunk_overlap"]),
        content
    )
    content = re.sub(
        r'RETRIEVAL_TOP_K = int\(os\.getenv\("RETRIEVAL_TOP_K",\s*"\d+"\)\)',
        'RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "{}"))'.format(params["top_k"]),
        content
    )

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("参数已写入 config.py")


if __name__ == "__main__":
    asyncio.run(auto_tune(target_accuracy=90.0, max_iterations=8))
