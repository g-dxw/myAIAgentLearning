"""
异步 Agent 对话 API
- SqlAlchemy async 存储对话历史
- httpx async 调用 LLM
- Depends 注入数据库和 LLM 客户端
- 全局异常处理和日志
"""


import time
from fastapi import Depends, FastAPI, Request
from fastapi.concurrency import asynccontextmanager
from fastapi.responses import JSONResponse
import httpx
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Text, String, select
from datetime import datetime

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行：创建数据库表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # 关闭时执行（可选）：关闭数据库连接池
    await engine.dispose()


# ==========================================
# 初始化
# ==========================================

app = FastAPI(title="异步 Agent 对话 API", version="0.3.0", lifespan=lifespan)

# 数据库引擎
engine = create_async_engine("sqlite+aiosqlite:///./agent.db", echo=False)

# 创建异步会话
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ==========================================
# 数据模型（Pydantic）
# ==========================================
class ChatRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=36, description="对话 ID")
    message: str = Field(min_length=1, max_length=4000, description="用户消息")
    model: str = Field(default="deepseek-v4-Flash", description="模型名称")

class ChatResponse(BaseModel):
    reply: str
    model: str
    conversation_id: str
    usage: dict

# ==========================================
# 数据库模型（SQLAlchemy）
# ==========================================

class Base(DeclarativeBase):
    pass

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    create_at:Mapped[datetime] = mapped_column(default=datetime.now)

# ==========================================
# 依赖注入
# ==========================================
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
async def get_llm_client():
    async with httpx.AsyncClient(
        base_url= "http://localhost:11434",
        timeout=60,
    ) as client:
        yield client

# ==========================================
# 中间件 & 异常处理
# ==========================================
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    '''添加处理时间头部'''
    start = time.time()
    response = await call_next(request)
    elapsed_time = time.time() - start
    response.headers["X-Process-Time-Ms"] = str(elapsed_time * 1000)

    # 日志记录
    print(f"Request: {request.method} {request.url} {response.status_code} - Process Time: {elapsed_time:.4f} seconds")
    return response

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    print(f"[FATAL] {request.method} {request.url} - {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "内部服务器错误", "error": True, "code": 500}
    )

# ==========================================
# 核心：异步 Agent 对话路由
# ==========================================
@app.post("/v1/chat", response_model= ChatResponse)
async def chat(request: ChatRequest, 
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
    try:
        data = resp.json()
    except httpx.HTTPError as e:
        print(f"LLM Request Error: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": "内部服务器错误", "error": True, "code": 500}
        )

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
    return ChatResponse(
        reply=reply_text,
        model="qwen2.5:1.5b",
        conversation_id= request.conversation_id,
        usage=data.get("usage", {})
    )


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.3.0"}