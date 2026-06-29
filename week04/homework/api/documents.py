"""
文档管理 API
POST   /api/v1/documents/          上传文档（multipart/form-data）
GET    /api/v1/documents/          文档列表（?page=1&page_size=20）
GET    /api/v1/documents/{id}      文档详情
DELETE /api/v1/documents/{id}      删除文档（同时删向量库数据和数据库记录）
"""

import asyncio
import logging
import os
import uuid

from fastapi import APIRouter, UploadFile, File, Depends, Query
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import UPLOAD_DIR, MAX_UPLOAD_BYTES, ALLOWED_EXTENSIONS, CHROMA_PATH
from core.database import get_db, AsyncSessionLocal
from models.documents import Document
from schemas.response import APIResponse
from schemas.models import DocumentUploadResponse, DocumentInfo, DocumentListResponse
from rag.pipeline import RAGPipeline
from rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

os.makedirs(UPLOAD_DIR, exist_ok=True)


async def _process_document_background(doc_id: int, file_path: str, filename: str, file_ext: str):
    """后台任务：对文档进行分割+Embedding+入库"""
    pipeline = RAGPipeline()
    async with AsyncSessionLocal() as db:
        try:
            # 1. 标记为处理中
            await db.execute(
                update(Document).where(Document.id == doc_id)
                .values(status="processing")
            )
            await db.commit()

            # 2. 执行索引
            result = await pipeline.index_document(file_path, filename, file_ext)
            chunk_count = result.get("chunk_count", 0)

            # 3. 标记为完成
            await db.execute(
                update(Document).where(Document.id == doc_id)
                .values(status="done", chunk_count=chunk_count)
            )
            await db.commit()
            logger.info(f"文档 {filename} 索引完成，共 {chunk_count} 个片段")

        except Exception as e:
            # 标记为失败
            error_msg = str(e)[:500]
            await db.execute(
                update(Document).where(Document.id == doc_id)
                .values(status="error", error_msg=error_msg)
            )
            await db.commit()
            logger.error(f"文档 {filename} 索引失败: {error_msg}")


@router.post("/documents/", response_model=APIResponse[DocumentUploadResponse])
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """上传文档：保存文件、写入数据库、后台异步处理Embedding"""
    # 检查扩展名
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        return APIResponse(
            success=False,
            error=f"不支持的文件类型，仅允许: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # 读取并检查大小
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        return APIResponse(
            success=False,
            error=f"文件大小超过限制（最大 {MAX_UPLOAD_BYTES / 1024 / 1024:.0f}MB）"
        )

    # 保存文件到磁盘
    saved_as = f"{uuid.uuid4().hex}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, saved_as)
    with open(file_path, "wb") as buffer:
        buffer.write(contents)

    # 写入数据库（状态为 pending，后台处理）
    db_doc = Document(
        filename=file.filename,
        saved_as=saved_as,
        file_type=file_ext,
        size_bytes=len(contents),
        chunk_count=0,
        status="pending"
    )
    db.add(db_doc)
    await db.commit()
    await db.refresh(db_doc)

    # 启动后台任务处理 Embedding
    asyncio.create_task(
        _process_document_background(db_doc.id, file_path, file.filename, file_ext)
    )

    return APIResponse(
        success=True,
        data=DocumentUploadResponse(
            doc_id=db_doc.id,
            chunk_count=0,
            filename=file.filename
        )
    )


@router.get("/documents/", response_model=APIResponse[DocumentListResponse])
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """获取文档列表（分页）"""
    total_result = await db.execute(select(func.count()).select_from(Document))
    total = total_result.scalar()

    offset = (page - 1) * page_size
    result = await db.execute(
        select(Document)
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    docs = result.scalars().all()

    items = [DocumentInfo.model_validate(d) for d in docs]

    return APIResponse(
        success=True,
        data=DocumentListResponse(items=items, total=total),
        meta={"page": page, "page_size": page_size, "total": total}
    )


@router.get("/documents/{doc_id}", response_model=APIResponse[DocumentInfo])
async def get_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    """获取单个文档详情"""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        return APIResponse(success=False, error="文档不存在")

    return APIResponse(success=True, data=DocumentInfo.model_validate(doc))


@router.delete("/documents/{doc_id}", response_model=APIResponse[dict])
async def delete_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    """删除文档：同时删除向量库数据、数据库记录和物理文件"""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        return APIResponse(success=False, error="文档不存在")

    try:
        # 删除向量库中的数据
        vs = VectorStore(CHROMA_PATH)
        vs.delete_document(str(doc.id))

        # 删除数据库记录
        await db.delete(doc)
        await db.commit()

        # 删除物理文件
        file_path = os.path.join(UPLOAD_DIR, doc.saved_as)
        if os.path.exists(file_path):
            os.remove(file_path)

        return APIResponse(success=True, data={"deleted_id": doc_id})
    except Exception as e:
        return APIResponse(success=False, error=f"删除失败: {str(e)}")
