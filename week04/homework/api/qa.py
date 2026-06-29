"""
问答 API
POST   /api/v1/qa/                非流式问答
POST   /api/v1/qa/stream          流式问答（SSE）
"""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, AsyncSessionLocal
from models.messages import Message
from models.conversations import Conversation
from schemas.response import APIResponse
from schemas.models import QuestionRequest, QAResponse
from rag.pipeline import RAGPipeline

router = APIRouter(tags=["qa"])
pipeline = RAGPipeline()


@router.post("/qa/", response_model=APIResponse[QAResponse])
async def ask_question(
    req: QuestionRequest,
    db: AsyncSession = Depends(get_db)
):
    """非流式问答"""
    # 校验对话是否存在
    if req.conversation_id:
        result = await db.execute(
            select(Conversation).where(Conversation.id == req.conversation_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return APIResponse(success=False, error="对话不存在")

    # 保存用户提问
    if req.conversation_id:
        user_msg = Message(
            conversation_id=req.conversation_id,
            role="user",
            content=req.question
        )
        db.add(user_msg)
        await db.commit()

        # 如果对话标题为默认值，用第一条提问前20个字符作为标题
        result = await db.execute(
            select(Conversation).where(Conversation.id == req.conversation_id)
        )
        conv = result.scalar_one_or_none()
        if conv and conv.title == "新对话":
            new_title = req.question[:20].replace("\n", " ")
            if len(req.question) > 20:
                new_title += "..."
            await db.execute(
                update(Conversation)
                .where(Conversation.id == req.conversation_id)
                .values(title=new_title)
            )
            await db.commit()

    try:
        # 调用 RAGPipeline
        result = await pipeline.query(req.question, req.conversation_id)
        answer = result.get("answer", "")
        sources = result.get("sources", [])
        usage = result.get("usage")

        # 保存助手回答
        if req.conversation_id:
            sources_json = json.dumps(sources, ensure_ascii=False, default=str) if sources else None
            assistant_msg = Message(
                conversation_id=req.conversation_id,
                role="assistant",
                content=answer,
                sources=sources_json
            )
            db.add(assistant_msg)
            await db.commit()

        return APIResponse(
            success=True,
            data=QAResponse(answer=answer, sources=sources, usage=usage)
        )
    except Exception as e:
        return APIResponse(success=False, error=f"问答处理失败: {str(e)}")


@router.post("/qa/stream")
async def ask_question_stream(
    req: QuestionRequest,
    db: AsyncSession = Depends(get_db)
):
    """流式问答（SSE）"""
    # 校验对话是否存在
    if req.conversation_id:
        result = await db.execute(
            select(Conversation).where(Conversation.id == req.conversation_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return APIResponse(success=False, error="对话不存在")

    # 保存用户提问
    if req.conversation_id:
        user_msg = Message(
            conversation_id=req.conversation_id,
            role="user",
            content=req.question
        )
        db.add(user_msg)
        await db.commit()

        # 如果对话标题为默认值，用第一条提问前20个字符作为标题
        result = await db.execute(
            select(Conversation).where(Conversation.id == req.conversation_id)
        )
        conv = result.scalar_one_or_none()
        if conv and conv.title == "新对话":
            new_title = req.question[:20].replace("\n", " ")
            if len(req.question) > 20:
                new_title += "..."
            await db.execute(
                update(Conversation)
                .where(Conversation.id == req.conversation_id)
                .values(title=new_title)
            )
            await db.commit()

    async def event_generator():
        full_answer = ""
        sources = []

        try:
            async for chunk in pipeline.query_stream(req.question, req.conversation_id):
                if isinstance(chunk, dict):
                    delta = chunk.get("delta") or ""
                    done = chunk.get("done", False)
                    chunk_sources = chunk.get("sources")
                    if chunk_sources:
                        sources = chunk_sources
                    full_answer += delta

                    data = json.dumps(chunk, ensure_ascii=False, default=str)
                    yield f"event: message\ndata: {data}\n\n"
                else:
                    # 非字典类型，包装后发送
                    data = json.dumps(
                        {"delta": str(chunk), "done": False},
                        ensure_ascii=False,
                        default=str
                    )
                    yield f"event: message\ndata: {data}\n\n"

            # 流结束后保存助手消息
            if req.conversation_id and full_answer:
                async with AsyncSessionLocal() as db2:
                    sources_json = json.dumps(
                        sources, ensure_ascii=False, default=str
                    ) if sources else None
                    assistant_msg = Message(
                        conversation_id=req.conversation_id,
                        role="assistant",
                        content=full_answer,
                        sources=sources_json
                    )
                    db2.add(assistant_msg)
                    await db2.commit()

        except Exception as e:
            data = json.dumps(
                {"delta": "", "done": True, "error": str(e)},
                ensure_ascii=False,
                default=str
            )
            yield f"event: message\ndata: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
