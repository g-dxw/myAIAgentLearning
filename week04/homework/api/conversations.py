"""
对话管理 API
POST   /api/v1/conversations/         创建对话
GET    /api/v1/conversations/         对话列表
GET    /api/v1/conversations/{id}     对话详情
GET    /api/v1/conversations/{id}/messages  消息列表
DELETE /api/v1/conversations/{id}     删除对话
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.conversations import Conversation
from models.messages import Message
from schemas.response import APIResponse
from schemas.models import ConversationCreate, ConversationInfo, MessageInfo

router = APIRouter(tags=["conversations"])


@router.post("/conversations/", response_model=APIResponse[ConversationInfo])
async def create_conversation(
    data: ConversationCreate = None,
    db: AsyncSession = Depends(get_db)
):
    """创建新对话，自动生成标题"""
    if data is None:
        data = ConversationCreate()

    conv = Conversation(title=data.title)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return APIResponse(success=True, data=ConversationInfo.model_validate(conv))


@router.get("/conversations/", response_model=APIResponse[list[ConversationInfo]])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    """获取所有对话列表（按创建时间倒序）"""
    result = await db.execute(
        select(Conversation).order_by(Conversation.created_at.desc())
    )
    convs = result.scalars().all()

    items = [ConversationInfo.model_validate(c) for c in convs]
    return APIResponse(success=True, data=items)


@router.get("/conversations/{conv_id}", response_model=APIResponse[ConversationInfo])
async def get_conversation(conv_id: int, db: AsyncSession = Depends(get_db)):
    """获取单个对话详情"""
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        return APIResponse(success=False, error="对话不存在")

    return APIResponse(success=True, data=ConversationInfo.model_validate(conv))


@router.get("/conversations/{conv_id}/messages", response_model=APIResponse[list[MessageInfo]])
async def list_messages(conv_id: int, db: AsyncSession = Depends(get_db)):
    """获取对话的消息列表（按时间正序）"""
    # 检查对话是否存在
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        return APIResponse(success=False, error="对话不存在")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    msgs = result.scalars().all()

    items = [MessageInfo.model_validate(m) for m in msgs]
    return APIResponse(success=True, data=items)


@router.delete("/conversations/{conv_id}", response_model=APIResponse[dict])
async def delete_conversation(conv_id: int, db: AsyncSession = Depends(get_db)):
    """删除对话及其所有消息"""
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        return APIResponse(success=False, error="对话不存在")

    # 先删除关联消息
    await db.execute(delete(Message).where(Message.conversation_id == conv_id))
    # 再删除对话
    await db.delete(conv)
    await db.commit()

    return APIResponse(success=True, data={"deleted_id": conv_id})
