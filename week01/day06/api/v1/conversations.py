from sqlalchemy import select
from fastapi import APIRouter, Depends
import httpx
from schemas.chat import ChatRequest, ChatResponse, MessageResponse
from models.message import Message
from schemas.commonResponse import APIResponse, PaginatedResponse
from core.database import get_db
from core.client import get_llm_client
from sqlalchemy.ext.asyncio import AsyncSession

conv_router = APIRouter(prefix="/conversations", tags=["对话管理"])

@conv_router.post("/", response_model= APIResponse[ChatResponse])
async def create_conversation(request: ChatRequest, 
               db:AsyncSession = Depends(get_db),
               client: httpx.AsyncClient = Depends(get_llm_client)):
    # 1. 异步查历史消息 → 同时事件循环可以处理其他请求
    result = await db.execute(
       select(Message)
       .where(Message.conversation_id == request.conversation_id)
       .order_by(Message.create_at)
       .limit(20)
    )
    history = result.scalars().all()
    # 2. 构建 LLM 请求
    messages = [
        {"role": m.role, "content": m.content}
        for m in history
    ]
    messages.append({"role": "user", "content": request.message})

    # 3. 异步调 LLM → 等待期间事件循环继续处理其他请求
    resp = await client.post("/api/chat", json={
        "model": "qwen2.5:1.5b",
        "max_tokens": 4096,
        "messages": messages,
        "stream": False
    })
    data = resp.json()

    print(f"LLM Response: {data}")

    reply_text = data["message"]["content"]

    # 4. 异步存用户消息
    user_msg = Message(
        conversation_id=request.conversation_id,
        role="user",
        content=request.message
    )
    db.add(user_msg)

    # 5. 异步存 Assistant 回复
    assistant_msg = Message(
        conversation_id=request.conversation_id,
        role="assistant",
        content=reply_text
    )
    db.add(assistant_msg)
    # 6. 异步提交
    await db.commit()
    return APIResponse(
        data=ChatResponse(
            reply=reply_text,
            model="qwen2.5:1.5b",
            conversation_id=request.conversation_id,
            usage=data.get("usage", {})
        )
    )

@conv_router.get("/{conversation_id}", response_model= APIResponse[list[MessageResponse]])
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.create_at)
    )
    messages = result.scalars().all()
    return APIResponse(
        data=messages
    ) 

@conv_router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
    )
    messages = result.scalars().all()
    for message in messages:
        await db.delete(message)
    await db.commit()
    return APIResponse(
        data=f"对话 {conversation_id} 已删除"
    )

@conv_router.delete("/{conversation_id}/{id}")
async def delete_message(conversation_id: str, id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.id == id)
    )
    message = result.scalar()
    if message:
        await db.delete(message)
    await db.commit()
    return APIResponse(
        data=f"对话 {conversation_id} 中的消息 {id} 已删除"
    )

@conv_router.get("/")
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Message.conversation_id)
        .distinct()
    )
    conversations = result.scalars().all()
    return APIResponse(
        data={
            list: conversations,
            **PaginatedResponse(
                total=len(conversations),
                page=1,
                page_size=len(conversations),
                total_pages=1
            )
        },
    )