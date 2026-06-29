import json
import uuid

from core.splitter import DocumentSplitter
from core.embedding import Embedding
from rag.vector_store import VectorStore
from rag.retriever import Retriever
from rag.generator import Generator
import core.config as config


class RAGPipeline:
    def __init__(self):
        self.splitter = DocumentSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP,
            strategy="recursive"
        )
        self.embedding = Embedding(
            model=config.EMBED_MODEL,
            base_url=config.EMBED_BASE_URL
        )
        self.vector_store = VectorStore(config.CHROMA_PATH)
        self.retriever = Retriever(
            embedding=self.embedding,
            vector_store=self.vector_store
        )
        self.generator = Generator()

    async def index_document(self, file_path: str, filename: str, file_type: str) -> dict:
        """索引文档 -> 返回 {doc_id, chunk_count}"""
        doc_id = str(uuid.uuid4())

        # 1. 用DocumentSplitter.split分割文档
        chunks = self.splitter.split(file_path)

        # 2. 用并发 Embedding 生成向量
        texts = [chunk["text"] for chunk in chunks]
        embeddings = await self.embedding.embed_batch_async(texts, concurrency=8)

        # 3. 用VectorStore.add_chunks存入Chroma
        chunk_count = self.vector_store.add_chunks(doc_id, chunks, embeddings)

        return {
            "doc_id": doc_id,
            "chunk_count": chunk_count
        }

    async def query(self, question: str, conv_id: str = None) -> dict:
        """非流式问答 -> 返回 {answer, sources, usage}"""
        history = await self._get_history(conv_id)

        # 1. Query Rewriting
        rewritten_question = await self.retriever.rewrite_query(question, history)

        # 2. 高级检索（支持 Multi-Query / HyDE / Re-ranking）
        contexts = await self.retriever.retrieve_advanced(
            rewritten_question,
            top_k=config.RETRIEVAL_TOP_K,
            use_multi_query=config.USE_MULTI_QUERY,
            use_hyde=config.USE_HYDE,
            use_re_rank=config.USE_RE_RANK,
        )

        # 3. 生成答案
        result = await self.generator.generate(rewritten_question, contexts)
        result["question"] = question
        result["rewritten_question"] = rewritten_question

        return result

    async def query_stream(self, question: str, conv_id: str = None):
        """SSE流式问答 -> 生成器 yield dict"""
        history = await self._get_history(conv_id)

        # 1. Query Rewriting
        rewritten_question = await self.retriever.rewrite_query(question, history)

        # 2. 高级检索（支持 Multi-Query / HyDE / Re-ranking）
        contexts = await self.retriever.retrieve_advanced(
            rewritten_question,
            top_k=config.RETRIEVAL_TOP_K,
            use_multi_query=config.USE_MULTI_QUERY,
            use_hyde=config.USE_HYDE,
            use_re_rank=config.USE_RE_RANK,
        )

        # 3. 流式生成
        async for token in self.generator.generate_stream(rewritten_question, contexts):
            yield token

    async def _get_history(self, conv_id: str) -> list[dict] | None:
        """获取对话历史。

        数据库操作在API层处理，pipeline只返回数据。
        当前返回None，表示不使用历史进行Query Rewriting。
        如需接入历史，可由API层扩展此接口或先查询数据库再传入。
        """
        return None
