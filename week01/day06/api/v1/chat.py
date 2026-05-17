
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
import httpx
from schemas.chat import ChatRequest, ChatResponse, MessageResponse
from core.client import get_llm_client

chat_router = APIRouter(prefix="/chat", tags=["对话"])

# ==========================================
# 新实现：sse-starlette EventSourceResponse
# ==========================================

@chat_router.post("/stream")
async def chat_stream(request: ChatRequest, client: httpx.AsyncClient = Depends(get_llm_client)):
    """SSE 流式聊天 — sse-starlette 实现"""
    async def event_generator():
        async with client.stream("POST", "/api/chat", json={
            "model": "qwen2.5:1.5b",
            "max_tokens": 4096,
            "messages": [
                {"role": "user", "content": request.message}
            ],
            "stream": True
        }) as response:
            full_text = ""
            async for chunk in response.aiter_lines():
                chunk = chunk.strip()
                if not chunk:
                    continue
                try:
                    data = json.loads(chunk)
                    if "message" in data and "content" in data["message"]:
                        text = data["message"]["content"]
                        full_text += text
                        yield {
                            "event": "message",
                            "data": json.dumps({"text": "text", "content": text}),
                        }
                except Exception:
                    continue
            yield {
                "event": "done",
                "data": json.dumps({"type": "done", "full_text": full_text}),
            }

    return EventSourceResponse(event_generator())

# ==========================================
# 旧实现（保留学习用）：手动 StreamingResponse
# ==========================================

@chat_router.post("/stream-legacy")
async def chat_stream_legacy(request: ChatRequest, client: httpx.AsyncClient = Depends(get_llm_client)):
    """聊天流接口 — 手动构造 SSE 格式"""
    async def generate():
        async with client.stream("POST", "/api/chat", json={
            "model": "qwen2.5:1.5b",
            "max_tokens": 4096,
            "messages": [
                {"role": "user", "content": request.message}
            ],
            "stream": True
        }) as response:
            full_text = ""
            async for chunk in response.aiter_lines():
                chunk = chunk.strip()
                if not chunk:
                    continue
                try:
                    data = json.loads(chunk)
                    if "message" in data and "content" in data["message"]:
                        text = data["message"]["content"]
                        full_text += text
                        yield f"data: {json.dumps({'text': 'text', 'content': text})}\n\n"
                except:
                    continue
            yield f"data: {json.dumps({'type': 'done', 'full_text': full_text})}\n\n"
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
