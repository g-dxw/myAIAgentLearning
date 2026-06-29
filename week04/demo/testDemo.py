import random
from vector_store import VectorStore
# 初始化
store = VectorStore("./test_db")


# 模拟 10 条数据
chunks = [{'text': f'这是第{i}条测试文本'} for i in range(10)]

# 模拟 768 维向量
embeddings = [[random.random() for _ in range(768)] for _ in range(10)]

store.add_chunks('test', chunks, embeddings)

print(f'入库: {store.count()} 条')


# 随机查询
query_vec = [random.random() for _ in range(768)]
results = store.query(query_vec, top_k=3)

for r in results:
    print(f"[{r['similarity']:.3f}] {r['text']}")

# 删除
# store.delete_document('test')
# print(f'删除后: {store.count()} 条')