import chromadb
from chromadb.config import Settings

class VectorStore:
    """
    Chroma 向量库封装。

    用法:
        store = VectorStore("./chroma_db")
        await store.add_chunks(doc_id, chunks, embeddings)
        results = await store.query(query_embedding, top_k=5)
        await store.delete_document(doc_id)
    """

    def __init__(self, persist_path:str = "./chroma_db"):
        self.client = chromadb.PersistentClient(
            path=persist_path,
            settings=Settings(anonymized_telemetry=False),
        )

        self.collection = self.client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"}
        )
    # ─── 增 ───
    def add_chunks(self, doc_id: str, chunks: list[dict], embeddings: list[list[float]])-> int:
        """
        将一批 chunk 和它们的向量写入 Chroma。

        参数:
            doc_id: 文档唯一标识（如 "doc_001"）
            chunks: [{"text": "...", "metadata": {...}}, ...]
            embeddings: [[0.1, 0.2, ...], [0.3, 0.4, ...], ...]

        返回:
            写入的 chunk 数量
        """

        ids = []
        documents = []
        metadatas =[]
        embeds = []

        for i, (chunk, emb)  in enumerate(zip(chunks, embeddings)):
            chunk_id = f"{doc_id}_chunk_{i}"
            ids.append(chunk_id)

            # Chroma 的 documents 字段存原文
            documents.append(chunk["text"])

            # metadata 里的值必须是 str / int / float / bool
            meta = {k: str(v) for k, v in chunk.get("metadata", {}).items()}
            meta["doc_id"] = doc_id
            metadatas.append(meta)

            embeds.append(emb)

        if ids:
            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeds
            )

        return len(ids)
    
    def query(self,  
                query_embedding: list[float],
                top_k: int = 5,
                where: dict | None = None,
                min_similarity: float = 0.0,
            ) -> list[dict]:
        """
        语义检索：用向量检索最相关的 chunk。

        返回:
        [
            {
                "id": "doc_001_chunk_3",
                "text": "匹配到的文本...",
                "metadata": {"source": "xxx.pdf", "page": "3"},
                "distance": 0.12,  # 余弦距离，越小越相似
                "similarity": 0.88,  # 转为相似度
            },
            ...
        ]
        """
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        
        formatted = []
        # Chroma 返回的是嵌套列表（因为支持批量查询）
        ids = results["ids"][0] if results["ids"] else []
        docs = results["documents"][0] if results["documents"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []
        dists = results["distances"][0] if results["distances"] else []

        for id_, doc, meta, dist in zip(ids, docs, metas, dists):
            sim = 1 - dist  # 余弦距离 → 余弦相似度
            if sim < min_similarity:
                continue
            formatted.append({
                "id": id_,
                "text": doc,
                "metadata": meta,
                "distance": dist,
                "similarity": round(sim, 4),
            })

        return formatted
    
    # ─── 删 ───
    def delete_document(self, doc_id: str) -> int:
        """
        删除一个文档的所有 chunk。

        参数:
            doc_id: 文档 ID（如 "doc_001"）

        返回:
            删除的 chunk 数量
        """
        # 先找到所有属于这个文档的 chunk id
        results = self.collection.get(
            where={"doc_id": doc_id},
            include=[],
        )
        chunk_ids = results["ids"]

        if chunk_ids:
            self.collection.delete(ids=chunk_ids)

        return len(chunk_ids)
    
    # ─── 统计 ───
    def count(self) -> int:
        """返回向量库中的 chunk 总数"""
        return self.collection.count()
    
    def list_documents(self) -> list[str]:
        """列出所有文档 ID"""
        # 用 get 获取所有不同的 doc_id
        results = self.collection.get(include=["metadatas"])
        doc_ids = set()
        for meta in (results.get("metadatas") or []):
            if meta and "doc_id" in meta:
                doc_ids.add(meta["doc_id"])
        return sorted(doc_ids)

    def get_all(self) -> list[dict]:
        """获取所有 chunk（用于全文关键词搜索）"""
        results = self.collection.get(include=["documents", "metadatas"])
        formatted = []
        ids = results.get("ids", [])
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        for id_, doc, meta in zip(ids, docs, metas):
            formatted.append({
                "id": id_,
                "text": doc or "",
                "metadata": meta or {},
            })
        return formatted