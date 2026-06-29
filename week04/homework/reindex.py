import asyncio
import os
import shutil

from core.splitter import DocumentSplitter
from core.embedding import Embedding
from rag.vector_store import VectorStore
from core.config import CHROMA_PATH, CHUNK_SIZE, CHUNK_OVERLAP


async def reindex():
    # 清空旧向量库
    if os.path.exists(CHROMA_PATH):
        shutil.rmtree(CHROMA_PATH)
        print("旧向量库已清除")

    splitter = DocumentSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        strategy="recursive"
    )
    embedding = Embedding()
    vs = VectorStore(CHROMA_PATH)

    total = 0
    upload_dir = "uploads"

    for fname in sorted(os.listdir(upload_dir)):
        fpath = os.path.join(upload_dir, fname)
        if not os.path.isfile(fpath):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in [".md", ".txt", ".html"]:
            continue

        print("正在索引: " + fname + " ...")
        try:
            chunks = splitter.split(fpath)
            texts = [c["text"] for c in chunks]

            print("  分割为 " + str(len(chunks)) + " 个片段，开始并发 Embedding...")
            embeddings = await embedding.embed_batch_async(texts, concurrency=8)

            doc_id = fname.replace(".", "_")
            chunk_count = vs.add_chunks(doc_id, chunks, embeddings)
            print("  完成: " + str(chunk_count) + " 个片段入库")
            total += chunk_count
        except Exception as e:
            print("  失败: " + str(e))

    count = vs.count()
    print("\n向量库总计: " + str(count) + " 个片段")


if __name__ == "__main__":
    asyncio.run(reindex())
