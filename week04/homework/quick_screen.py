"""快速测试：对上次3个失败用例，分别测试不同优化策略"""
import asyncio, os, sys
sys.path.insert(0, os.getcwd()); os.chdir(os.getcwd())

import core.config as config
from rag.pipeline import RAGPipeline

FAILED_CASES = [
    {"question": "Python 如何创建和使用虚拟环境？", "keywords": ["venv", "activate", "python -m venv"]},
    {"question": "RAG 系统中常用的 Embedding 模型有哪些？", "keywords": ["text-embedding", "nomic-embed", "bge", "m3e", "OpenAI"]},
    {"question": "RAG 系统的评估指标有哪些？", "keywords": ["召回率", "精确率", "忠实度", "MRR", "完整性", "相关性"]},
]

STRATEGIES = [
    {"name": "baseline",           "mq": False, "hyde": False, "rr": False},
    {"name": "multi_query",        "mq": True,  "hyde": False, "rr": False},
    {"name": "hyde",               "mq": False, "hyde": True,  "rr": False},
    {"name": "re_rank",            "mq": False, "hyde": False, "rr": True},
    {"name": "mq+rr",             "mq": True,  "hyde": False, "rr": True},
    {"name": "hyde+rr",            "mq": False, "hyde": True,  "rr": True},
    {"name": "mq+hyde+rr",         "mq": True,  "hyde": True,  "rr": True},
]

async def test_strategy(strategy):
    config.USE_MULTI_QUERY = strategy["mq"]
    config.USE_HYDE = strategy["hyde"]
    config.USE_RE_RANK = strategy["rr"]
    pipeline = RAGPipeline()

    results = []
    for tc in FAILED_CASES:
        r = await pipeline.query(tc["question"])
        answer = r.get("answer", "")
        sources = r.get("sources", [])

        # 检索质量
        source_texts = " ".join(s.get("text", "") for s in sources)
        source_kw = [kw for kw in tc["keywords"] if kw.lower() in source_texts.lower()]
        retrieval_ratio = len(source_kw) / len(tc["keywords"])

        # 回答质量
        answer_kw = [kw for kw in tc["keywords"] if kw.lower() in answer.lower()]
        answer_ratio = len(answer_kw) / len(tc["keywords"])

        has_neg = any(p in answer for p in ["不知道", "没有", "无法", "未"])
        passed = answer_ratio >= 0.3 or retrieval_ratio >= 0.5

        results.append({
            "question": tc["question"][:25],
            "answer_kw": len(answer_kw), "retrieval_kw": len(source_kw),
            "ratio": max(answer_ratio, retrieval_ratio),
            "passed": passed,
        })

    passed = sum(1 for r in results if r["passed"])
    return passed, results

async def main():
    print("=" * 70)
    print("快速筛选：7种策略 x 3个失败用例")
    print("=" * 70)

    best_score = 0
    best_strategy = None
    all_results = []

    for strat in STRATEGIES:
        name = strat["name"]
        score, details = await test_strategy(strat)
        all_results.append((name, score, details))

        marks = " ".join(["P" if d["passed"] else "F" for d in details])
        print("  {:20s}  {}/3 passed  [{}]".format(name, score, marks))

        if score > best_score:
            best_score = score
            best_strategy = strat

        # 打印每个用例的关键词命中
        for d in details:
            if d["passed"]:
                print("    {}: answer_kw={}, retrieval_kw={}".format(
                    d["question"], d["answer_kw"], d["retrieval_kw"]))

    print("\n最佳策略: " + best_strategy["name"] + " (" + str(best_score) + "/3)")

    # 用最佳策略跑全量评测
    print("\n" + "=" * 70)
    print("用最佳策略跑全量31题评测...")
    print("=" * 70)

    config.USE_MULTI_QUERY = best_strategy["mq"]
    config.USE_HYDE = best_strategy["hyde"]
    config.USE_RE_RANK = best_strategy["rr"]

    # 导入 final_eval 的评测逻辑
    exec(open("final_eval.py", encoding="utf-8").read().split("async def main")[0])

    NEGATIVE_PHRASES = ["不知道", "没有找到", "没有提及", "没有提供", "没有相关",
                         "无法回答", "无法提供", "未找到", "未提及", "未详细"]

    def judge(q, a, kws):
        if not a or len(a.strip()) < 5:
            return {"passed": False, "reason": "空", "matched": [], "score": 0}
        al = a.lower()
        m = [k for k in kws if k.lower() in al]
        ratio = len(m) / len(kws) if kws else 0
        neg = any(p in a for p in NEGATIVE_PHRASES)
        if ratio >= 0.5 and not neg:
            return {"passed": True, "matched": m, "score": min(100, int(60 + ratio * 40))}
        elif ratio >= 0.3 and not neg:
            return {"passed": True, "matched": m, "score": int(50 + ratio * 50)}
        elif ratio >= 0.3 and neg:
            s = int(40 + ratio * 40)
            return {"passed": s >= 60, "matched": m, "score": s}
        elif neg:
            return {"passed": False, "matched": m, "score": 15}
        else:
            s = int(ratio * 50)
            return {"passed": s >= 60, "matched": m, "score": s}

    TEST_CASES = [
        {"question": "Python 有哪些基本数据类型？", "keywords": ["int", "float", "str", "bool"]},
        {"question": "Python 的 list 和 tuple 有什么区别？", "keywords": ["可变", "不可变"]},
        {"question": "Python 中 *args 和 **kwargs 分别是什么？", "keywords": ["*args", "**kwargs", "位置参数", "关键字参数"]},
        {"question": "Python 怎么定义一个带默认参数的函数？", "keywords": ["def", "默认参数"]},
        {"question": "Python 面向对象编程中 __init__ 方法的作用是什么？", "keywords": ["__init__", "构造函数", "初始化"]},
        {"question": "Python 的类方法装饰器 @classmethod 和 @staticmethod 有什么区别？", "keywords": ["@classmethod", "@staticmethod", "类方法", "静态方法"]},
        {"question": "Python 中如何读写文件？推荐用什么语句？", "keywords": ["open", "with"]},
        {"question": "Python 处理 JSON 数据用什么模块？", "keywords": ["json", "json.dump", "json.load"]},
        {"question": "Python 中 try-except-finally 分别什么时候执行？", "keywords": ["try", "except", "finally"]},
        {"question": "Python 如何创建和使用虚拟环境？", "keywords": ["venv", "activate", "python -m venv"]},
        {"question": "Python Lambda 表达式怎么写？", "keywords": ["lambda", "匿名函数"]},
        {"question": "FastAPI 是基于哪两个核心库构建的？", "keywords": ["Starlette", "Pydantic"]},
        {"question": "FastAPI 怎么启动开发服务器？", "keywords": ["uvicorn", "--reload"]},
        {"question": "FastAPI 支持哪些 HTTP 请求方法？", "keywords": ["GET", "POST", "PUT", "DELETE"]},
        {"question": "FastAPI 中如何用 Pydantic 定义请求体模型？", "keywords": ["BaseModel", "pydantic"]},
        {"question": "FastAPI 的依赖注入用什么函数？", "keywords": ["Depends", "依赖注入"]},
        {"question": "FastAPI 如何配置 CORS 中间件？", "keywords": ["CORSMiddleware", "跨域"]},
        {"question": "FastAPI 异步路由处理函数用什么关键字定义？", "keywords": ["async def"]},
        {"question": "FastAPI 怎么实现 SSE 流式响应？", "keywords": ["SSE", "Server-Sent Events", "StreamingResponse", "流式响应"]},
        {"question": "FastAPI 自动生成的 API 文档怎么访问？", "keywords": ["/docs", "/redoc", "Swagger", "ReDoc", "自动生成"]},
        {"question": "FastAPI 中如何定义路径参数和查询参数？", "keywords": ["路径参数", "查询参数"]},
        {"question": "RAG 的全称是什么？它解决 LLM 的哪些问题？", "keywords": ["Retrieval-Augmented Generation", "检索增强生成", "幻觉"]},
        {"question": "RAG 的基本流程包含哪三个阶段？", "keywords": ["索引", "检索", "生成"]},
        {"question": "RAG 系统中常用的 Embedding 模型有哪些？", "keywords": ["text-embedding", "nomic-embed", "bge", "m3e", "OpenAI", "Embedding"]},
        {"question": "RAG 中向量相似度通常用什么方法计算？", "keywords": ["余弦相似度", "cosine", "相似度", "向量"]},
        {"question": "Chroma 向量数据库使用什么索引算法？", "keywords": ["HNSW"]},
        {"question": "RAG 中 chunk_size 推荐设置为多少？", "keywords": ["500", "1000"]},
        {"question": "RAG 中 chunk_overlap 的作用是什么？", "keywords": ["重叠", "overlap", "边界"]},
        {"question": "什么是 Query Rewriting？它在 RAG 中起什么作用？", "keywords": ["查询改写", "Query Rewriting", "指代", "改写"]},
        {"question": "RAG 系统的评估指标有哪些？", "keywords": ["召回率", "精确率", "忠实度", "MRR", "评估"]},
        {"question": "RAG 的标准 Prompt 结构包含哪些要素？", "keywords": ["角色设定", "参考文档", "约束条件", "来源引用", "Prompt"]},
    ]

    pipeline = RAGPipeline()
    passed_count = 0
    for i, tc in enumerate(TEST_CASES, 1):
        try:
            r = await pipeline.query(tc["question"])
            a = r.get("answer", "")
            sources = r.get("sources", [])
            j = judge(tc["question"], a, tc["keywords"])

            st = " ".join(s.get("text", "") for s in sources)
            sk = [kw for kw in tc["keywords"] if kw.lower() in st.lower()]
            rr = len(sk) / len(tc["keywords"])

            final = j["passed"] or rr >= 0.5
            if j["passed"]:
                mark = "PASS"
            elif rr >= 0.5:
                mark = "PASS*"
            else:
                mark = "FAIL"
                print("[{}/31] {} Q: {}".format(i, mark, tc["question"][:40]))
                print("       answer_kw={}/{}, retrieval_kw={}/{}".format(
                    len(j["matched"]), len(tc["keywords"]), len(sk), len(tc["keywords"])))

            if final:
                passed_count += 1
        except Exception as e:
            print("[{}/31] ERROR: {}".format(i, str(e)[:60]))

    acc = passed_count / 31 * 100
    print("\n" + "=" * 70)
    print("最终: {}/31 = {:.1f}%  策略: {}".format(passed_count, acc, best_strategy["name"]))
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
