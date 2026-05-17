# Day 07 — 综合实战：Agent 对话管理平台

## 产出目标

构建一个完整的 **Agent 对话管理平台** API 服务，覆盖 Week 01 全部知识点。这不是一个 Demo——它是一个真正能跑起来的后端，可以成为你后续项目的起点。

**今天的核心工作方式：你 + Claude Code 结对编程。** 你不是一个人在写，Claude Code 是你的副驾驶。

---

## 项目定位

```
一个多 Agent 对话管理后端，支持：
- 注册和管理多个 Agent（各自有独立的 system_prompt 和 tools）
- 与任意 Agent 进行对话（支持普通 + SSE 流式两种模式）
- 对话历史持久化（异步 SQLite）
- 语音输入（文件上传 + 模拟 ASR 返回文本）
- Token 用量追踪和统计
```

**为什么做这个：** 把这个后端跑起来之后，你随时可以在前面挂一个微信小程序、一个网页、甚至一个 CLI 工具。它是一个真正的"底座"，不是写完就扔的练习题。

---

## 项目结构

```
agent_platform/
├── main.py                 # FastAPI 应用入口 + 中间件 + 异常处理
├── models.py               # Pydantic 请求/响应模型
├── database.py             # SQLAlchemy async 配置 + 表定义
├── routers/
│   ├── __init__.py
│   ├── agents.py           # Agent CRUD
│   ├── conversations.py    # 对话 + 消息
│   └── uploads.py          # 文件上传
├── dependencies.py         # Depends 依赖函数
├── schemas.py              # 统一响应格式
├── seed.py                 # 初始化种子数据（可选）
└── uploads/                # 上传文件存储目录
    └── audio/
```

**原则：** 核心逻辑自己想、自己写；重复性代码（如 CRUD 模板、Schema 定义）可以让 Claude Code 出第一版，你审查修改。写完一个模块就跑 `uvicorn main:app --reload` 验证。

---

## 第一阶段：项目骨架（30 min）

### Step 1：创建目录和文件

```bash
mkdir -p agent_platform/routers agent_platform/uploads/audio
touch agent_platform/main.py agent_platform/models.py agent_platform/database.py
touch agent_platform/dependencies.py agent_platform/schemas.py
touch agent_platform/routers/__init__.py
touch agent_platform/routers/agents.py agent_platform/routers/conversations.py agent_platform/routers/uploads.py
```

### Step 2：安装依赖

```bash
pip install fastapi uvicorn[standard] pydantic sqlalchemy[asyncio] aiosqlite httpx python-multipart sse-starlette
```

### Step 3：`database.py` — 异步 SQLite

用 SQLite 而不是 PostgreSQL，因为零配置就能跑：

```python
"""数据库配置 — 异步 SQLite"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, DateTime, Float, ForeignKey
from datetime import datetime

# SQLite 异步驱动
DATABASE_URL = "sqlite+aiosqlite:///agent_platform.db"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ====== 数据表 ======

class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    model: Mapped[str] = mapped_column(String(50), default="claude-sonnet-4-6")
    system_prompt: Mapped[str] = mapped_column(Text, default="你是一个有用的助手")
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    title: Mapped[str] = mapped_column(String(100), default="新对话")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user / assistant / system
    content: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# 启动时自动建表
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

---

## 第二阶段：数据模型（20 min）

### `schemas.py` — 统一响应格式

```python
"""统一 API 响应格式"""
from pydantic import BaseModel


class APIResponse(BaseModel):
    success: bool = True
    data: dict | list | None = None
    error: str | None = None
    meta: dict | None = None
```

### `models.py` — 请求/响应 Pydantic 模型

```python
"""Pydantic 请求/响应模型"""
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime


# ====== Agent ======
class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    model: str = Field(default="claude-sonnet-4-6")
    system_prompt: str = Field(default="你是一个有用的助手", min_length=10)
    temperature: float = Field(default=0.7, ge=0, le=1)
    max_tokens: int = Field(default=4096, ge=1, le=32000)


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    model: str | None = None
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=32000)


class AgentOut(BaseModel):
    id: int
    name: str
    model: str
    temperature: float
    max_tokens: int
    created_at: datetime


# ====== Conversation ======
class ConversationCreate(BaseModel):
    agent_id: int = Field(ge=1)
    title: str = Field(default="新对话", max_length=100)


class ConversationOut(BaseModel):
    id: int
    agent_id: int
    title: str
    created_at: datetime


# ====== Message / Chat ======
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


# ====== Stats ======
class TokenStats(BaseModel):
    total_conversations: int
    total_messages: int
    total_input_tokens: int
    total_output_tokens: int
```

---

## 第三阶段：依赖注入（15 min）

### `dependencies.py`

```python
"""FastAPI 依赖注入"""
from database import AsyncSessionLocal
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
import os


async def get_db():
    """异步数据库会话"""
    async with AsyncSessionLocal() as session:
        yield session


async def get_llm_client():
    """LLM HTTP 客户端"""
    async with httpx.AsyncClient(
        base_url="https://api.anthropic.com/v1",
        headers={
            "x-api-key": os.getenv("ANTHROPIC_API_KEY", "sk-placeholder"),
            "anthropic-version": "2023-06-01",
        },
        timeout=60,
    ) as client:
        yield client
```

---

## 第四阶段：路由实现（90 min）

### `routers/agents.py` — Agent CRUD

```python
"""Agent 管理路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from dependencies import get_db
from database import Agent
from models import AgentCreate, AgentUpdate, AgentOut
from schemas import APIResponse

router = APIRouter(prefix="/api/v1/agents", tags=["Agent 管理"])


@router.post("/", status_code=201)
async def create_agent(data: AgentCreate, db: AsyncSession = Depends(get_db)):
    """创建 Agent"""
    # 检查重名
    existing = await db.execute(select(Agent).where(Agent.name == data.name))
    if existing.scalar():
        raise HTTPException(status_code=409, detail=f"Agent '{data.name}' 已存在")

    agent = Agent(**data.model_dump())
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    return APIResponse(success=True, data={
        "id": agent.id, "name": agent.name, "model": agent.model,
        "created_at": agent.created_at.isoformat(),
    })


@router.get("/")
async def list_agents(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """列出所有 Agent"""
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Agent).offset(offset).limit(page_size).order_by(Agent.created_at.desc())
    )
    agents = result.scalars().all()

    # 总数
    total_result = await db.execute(select(func.count(Agent.id)))
    total = total_result.scalar()

    return APIResponse(success=True, data=[
        {"id": a.id, "name": a.name, "model": a.model, "created_at": a.created_at.isoformat()}
        for a in agents
    ], meta={"page": page, "page_size": page_size, "total": total})


@router.get("/{agent_id}")
async def get_agent(agent_id: int, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} 不存在")
    return APIResponse(success=True, data={
        "id": agent.id, "name": agent.name, "model": agent.model,
        "system_prompt": agent.system_prompt,
        "temperature": agent.temperature, "max_tokens": agent.max_tokens,
        "created_at": agent.created_at.isoformat(),
    })


@router.put("/{agent_id}")
async def update_agent(agent_id: int, data: AgentUpdate, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} 不存在")

    # 只更新传入的字段
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(agent, key, value)

    await db.commit()
    await db.refresh(agent)
    return APIResponse(success=True, data={"id": agent.id, "name": agent.name, "updated": True})


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: int, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} 不存在")
    await db.delete(agent)
    await db.commit()
```

### `routers/conversations.py` — 对话 + 消息 + SSE 流式

```python
"""对话管理路由"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from dependencies import get_db, get_llm_client
from database import Agent, Conversation, Message
from models import ConversationCreate, ChatRequest
from schemas import APIResponse
import httpx
import json
import uuid

router = APIRouter(prefix="/api/v1/conversations", tags=["对话管理"])


@router.post("/", status_code=201)
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建新对话"""
    # 验证 agent 存在
    agent = await db.get(Agent, data.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {data.agent_id} 不存在")

    conv = Conversation(agent_id=data.agent_id, title=data.title)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return APIResponse(success=True, data={"id": conv.id, "title": conv.title})


@router.get("/")
async def list_conversations(
    agent_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """列出对话"""
    query = select(Conversation)
    if agent_id:
        query = query.where(Conversation.agent_id == agent_id)
    query = query.offset((page - 1) * page_size).limit(page_size).order_by(Conversation.created_at.desc())

    result = await db.execute(query)
    convs = result.scalars().all()

    total_result = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.agent_id == agent_id) if agent_id
        else select(func.count(Conversation.id))
    )
    total = total_result.scalar()

    return APIResponse(success=True, data=[
        {"id": c.id, "agent_id": c.agent_id, "title": c.title, "created_at": c.created_at.isoformat()}
        for c in convs
    ], meta={"page": page, "page_size": page_size, "total": total})


@router.get("/{conv_id}")
async def get_conversation(conv_id: int, db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"对话 {conv_id} 不存在")
    return APIResponse(success=True, data={
        "id": conv.id, "agent_id": conv.agent_id, "title": conv.title,
        "created_at": conv.created_at.isoformat(),
    })


@router.get("/{conv_id}/messages")
async def list_messages(conv_id: int, db: AsyncSession = Depends(get_db)):
    """获取对话的所有消息"""
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"对话 {conv_id} 不存在")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    return APIResponse(success=True, data=[
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in messages
    ])


@router.post("/{conv_id}/messages")
async def send_message(
    conv_id: int,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    llm: httpx.AsyncClient = Depends(get_llm_client),
):
    """发送消息并获取 Agent 回复（非流式）"""
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"对话 {conv_id} 不存在")

    agent = await db.get(Agent, conv.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="关联的 Agent 不存在")

    # 1. 取历史消息
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    history = list(reversed(result.scalars().all()))

    # 2. 构建 LLM 请求
    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": request.message})

    # 3. 调 LLM
    resp = await llm.post("/messages", json={
        "model": agent.model,
        "max_tokens": agent.max_tokens,
        "system": agent.system_prompt,
        "temperature": agent.temperature,
        "messages": messages,
    })

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"LLM 调用失败: {resp.text[:200]}")

    data = resp.json()
    reply_text = data["content"][0]["text"]
    usage = data["usage"]

    # 4. 存消息
    user_msg = Message(
        conversation_id=conv_id, role="user", content=request.message,
        input_tokens=usage.get("input_tokens", 0),
    )
    assistant_msg = Message(
        conversation_id=conv_id, role="assistant", content=reply_text,
        input_tokens=0, output_tokens=usage.get("output_tokens", 0),
    )
    db.add_all([user_msg, assistant_msg])
    await db.commit()
    await db.refresh(assistant_msg)

    return APIResponse(success=True, data={
        "reply": reply_text,
        "model": agent.model,
        "usage": {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"]},
        "message_id": assistant_msg.id,
    })


# ====== SSE 流式对话 ======
@router.post("/{conv_id}/stream")
async def stream_chat(
    conv_id: int,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    llm: httpx.AsyncClient = Depends(get_llm_client),
):
    """SSE 流式对话"""
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"对话 {conv_id} 不存在")

    agent = await db.get(Agent, conv.agent_id)

    # 取历史消息
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    history = list(reversed(result.scalars().all()))
    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": request.message})

    async def event_stream():
        full_text = ""
        try:
            async with llm.stream("POST", "/messages", json={
                "model": agent.model if agent else "claude-sonnet-4-6",
                "max_tokens": agent.max_tokens if agent else 4096,
                "system": agent.system_prompt if agent else "",
                "temperature": agent.temperature if agent else 0.7,
                "messages": messages,
                "stream": True,
            }) as resp:
                if resp.status_code != 200:
                    yield f"data: {json.dumps({'type': 'error', 'detail': 'LLM 调用失败'})}\n\n"
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])

                    if event.get("type") == "content_block_delta":
                        text = event["delta"].get("text", "")
                        full_text += text
                        yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"

                    elif event.get("type") == "message_delta":
                        yield f"data: {json.dumps({'type': 'usage', 'usage': event.get('usage', {})})}\n\n"

            # 存消息
            user_msg = Message(conversation_id=conv_id, role="user", content=request.message)
            assistant_msg = Message(conversation_id=conv_id, role="assistant", content=full_text)
            db.add_all([user_msg, assistant_msg])
            await db.commit()

            yield f"data: {json.dumps({'type': 'done', 'full_length': len(full_text)})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.delete("/{conv_id}", status_code=204)
async def delete_conversation(conv_id: int, db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"对话 {conv_id} 不存在")
    await db.delete(conv)
    await db.commit()


# ====== 统计 ======
@router.get("/stats/overview")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """全局统计"""
    total_convs = (await db.execute(select(func.count(Conversation.id)))).scalar()
    total_msgs = (await db.execute(select(func.count(Message.id)))).scalar()
    total_input = (await db.execute(select(func.sum(Message.input_tokens)))).scalar() or 0
    total_output = (await db.execute(select(func.sum(Message.output_tokens)))).scalar() or 0

    return APIResponse(success=True, data={
        "total_conversations": total_convs,
        "total_messages": total_msgs,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
    })
```

### `routers/uploads.py` — 文件上传

```python
"""文件上传路由"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from schemas import APIResponse
import uuid
import os

router = APIRouter(prefix="/api/v1/uploads", tags=["文件上传"])

ALLOWED_AUDIO = {"audio/wav", "audio/mpeg", "audio/webm", "audio/mp4", "audio/ogg"}
MAX_SIZE = 10 * 1024 * 1024  # 10MB
UPLOAD_DIR = "uploads/audio"


@router.post("/audio")
async def upload_audio(file: UploadFile = File(...)):
    """上传音频文件"""
    # 校验类型
    if file.content_type not in ALLOWED_AUDIO:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file.content_type}")

    # 读取 + 校验大小
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=400, detail=f"文件超过 10MB 限制")

    # 保存
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    save_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    save_path = os.path.join(UPLOAD_DIR, save_name)
    with open(save_path, "wb") as f:
        f.write(contents)

    # 模拟 ASR 返回（实际项目调腾讯云/Whisper API）
    mock_transcript = f"[模拟语音识别结果] 共 {len(contents)} 字节的音频"

    return APIResponse(success=True, data={
        "filename": file.filename,
        "saved_as": save_name,
        "size_bytes": len(contents),
        "transcript": mock_transcript,
    })
```

---

## 第五阶段：组装 main.py（20 min）

```python
"""Agent 对话管理平台 — 应用入口"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextvars import ContextVar
import uuid
import time

from database import init_db
from routers import agents, conversations, uploads

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库"""
    await init_db()
    yield


app = FastAPI(
    title="Agent 对话管理平台",
    version="1.0.0",
    description="多 Agent 对话管理后端 — Week 01 综合实战",
    lifespan=lifespan,
)

# ====== CORS ======
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ====== 请求追踪中间件 ======
@app.middleware("http")
async def trace_requests(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]
    request_id_ctx.set(rid)
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    response.headers["X-Request-ID"] = rid
    print(f"[{rid}] {request.method:6} {request.url.path:30} → {response.status_code} ({elapsed:.0f}ms)")
    return response

# ====== 全局异常处理 ======
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[ERROR] {request.method} {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"success": False, "error": "服务器内部错误"})

# ====== 注册路由 ======
app.include_router(agents.router)
app.include_router(conversations.router)
app.include_router(uploads.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Agent 对话管理平台", "version": "1.0.0"}
```

---

## 第六阶段：启动 & 测试（30 min）

### 启动

```bash
cd agent_platform
uvicorn main:app --reload
```

打开 `http://127.0.0.1:8000/docs` → 在 Swagger UI 里直接测试所有接口。

### 测试路径（按顺序手动测一遍）

```bash
# 1. 健康检查
curl http://127.0.0.1:8000/health

# 2. 创建 Agent
curl -X POST http://127.0.0.1:8000/api/v1/agents/ \
  -H "Content-Type: application/json" \
  -d '{"name":"旅行规划师","model":"claude-sonnet-4-6","system_prompt":"你是一个专业的旅行规划助手，帮助用户规划行程。","temperature":0.7}'

# 3. 列出 Agent
curl http://127.0.0.1:8000/api/v1/agents/

# 4. 创建对话
curl -X POST http://127.0.0.1:8000/api/v1/conversations/ \
  -H "Content-Type: application/json" \
  -d '{"agent_id":1,"title":"北京三日游规划"}'

# 5. 发送消息（需要设置 ANTHROPIC_API_KEY 环境变量）
curl -X POST http://127.0.0.1:8000/api/v1/conversations/1/messages \
  -H "Content-Type: application/json" \
  -d '{"message":"推荐北京三日游的行程"}'

# 6. 获取消息列表
curl http://127.0.0.1:8000/api/v1/conversations/1/messages

# 7. 上传音频（先准备一个测试文件）
echo "test audio content" > /tmp/test.wav
curl -X POST http://127.0.0.1:8000/api/v1/uploads/audio \
  -F "file=@/tmp/test.wav"

# 8. 统计
curl http://127.0.0.1:8000/api/v1/conversations/stats/overview

# 9. 流式对话（在终端实时看逐字输出）
curl -N -X POST http://127.0.0.1:8000/api/v1/conversations/1/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"详细说说第一天下午的行程"}'
```

---

## 副线：全程 Claude Code 结对编程

今天不是"写完代码再问 Claude Code"，而是**一边写一边用 Claude Code**。这是高效 Agent 开发者的真实工作流。

### 开发前的准备：补全 CLAUDE.md（5 min）

把 Day 06 写的 CLAUDE.md 放到 `agent_platform/` 目录下，确认项目结构部分准确。然后新增一段：

```markdown
## 当前任务
Day 07 — 正在构建 Agent 对话管理平台，包含以下模块：
1. database.py — SQLAlchemy async 模型（Agent / Conversation / Message）
2. models.py — Pydantic 请求/响应模型
3. routers/agents.py — Agent CRUD
4. routers/conversations.py — 对话管理 + SSE 流式
5. routers/uploads.py — 音频上传
6. main.py — 应用入口 + 中间件 + 路由注册

## 代码偏好
- 所有路由用 async def
- 错误统一用 HTTPException，不裸抛
- 响应用 APIResponse(success=..., data=..., error=...)
- 不需要写 docstring，命名已经够清楚
- 不要加过度抽象，三行能解决的别写十行
```

### 开发中的 Claude Code 使用策略

**Stage 1-2（基础文件）：自己写为主。**
`database.py` 和 `models.py` 应该自己打一遍，这是理解项目骨架的关键。遇到不确定的，比如 SQLAlchemy 字段类型怎么选，直接问 Claude Code。

**Stage 3-4（路由实现）：让 Claude Code 出第一版，你来改。**
比如 `agents.py` 的 CRUD 是重复模式，你可以：

```
"帮我在 agents.py 里写一个标准的 FastAPI CRUD router：
- 数据模型是 database.py 里的 Agent
- 请求模型是 models.py 里的 AgentCreate / AgentUpdate
- 响应用 schemas.py 的 APIResponse
- 分页查询支持 page 和 page_size
- 更新用 model_dump(exclude_unset=True)"
```

Claude Code 出代码后，你的工作是：
- 检查 async/await 对不对
- 检查错误处理是否完整
- 改掉你觉得不合适的设计
- 跑起来验证

**Stage 5（main.py 组装）：你写框架，Claude Code 帮你补细节。**

**Stage 6（测试）：全程让 Claude Code 帮你调试。**

当你遇到报错时，不要自己盯着 traceback 看 10 分钟。把 traceback 复制，直接问：

```
"启动时报了这个错：<paste traceback>。帮我分析原因。"
```

### 今天应该用到的 Claude Code 能力

| 能力 | 怎么用 | 今天的场景 |
|------|--------|-----------|
| 代码生成 | 描述需求 → 出第一版 | 写 CRUD 路由模板 |
| 代码审查 | `/review` 或直接问 | 检查 async/await 是否正确 |
| 错误诊断 | 贴 traceback | 启动报错、API 500 |
| 知识问答 | "SQLAlchemy async 的 select 怎么写" | 忘了语法时 |
| 重构 | "这个函数太长了，拆成两个" | 优化代码结构 |

### 今天的核心心法

```
你决定"做什么"和"为什么"
Claude Code 帮你加速"怎么做"

不要让它替你做决策 → 架构选型你定
不要让它替你想需求 → 功能需求你定
让它写重复代码你审查 → 这是它最擅长的事
```

### 最终检验

开发完成后，新开一个对话，对 Claude Code 说：

```
"项目在 agent_platform/ 目录，我已经写完了。帮我做一次代码审查，
重点检查：1) async/await 是否正确 2) 数据库操作是否有遗漏
3) 异常处理是否完整 4) 有没有明显的安全或性能问题"
```

把 Claude Code 发现的问题记下来（哪怕只有一个），这是你今天最大的收获。

---

## API 路由速查表

```
健康检查
  GET    /health

Agent 管理
  POST   /api/v1/agents/              创建 Agent
  GET    /api/v1/agents/              列出 Agent（分页）
  GET    /api/v1/agents/{id}          查看 Agent
  PUT    /api/v1/agents/{id}          更新 Agent
  DELETE /api/v1/agents/{id}          删除 Agent

对话管理
  POST   /api/v1/conversations/       创建对话
  GET    /api/v1/conversations/       列出对话（可选过滤 agent_id）
  GET    /api/v1/conversations/{id}   查看对话
  DELETE /api/v1/conversations/{id}   删除对话

消息 & 对话
  GET    /api/v1/conversations/{id}/messages   获取消息列表
  POST   /api/v1/conversations/{id}/messages   发送消息（普通）
  POST   /api/v1/conversations/{id}/stream     发送消息（SSE 流式）

统计
  GET    /api/v1/conversations/stats/overview  全局统计

文件上传
  POST   /api/v1/uploads/audio                 上传音频
```

---

## Week 01 技能覆盖清单

对照这个表，确认每个知识点都在项目里用到了：

| Day | 知识点 | 在本项目中的体现 |
|-----|--------|-----------------|
| Day 01 | 类型注解、dataclass、推导式、with、async | `database.py` 类型定义、`models.py` Pydantic 模型、lifespan async with |
| Day 02 | Pydantic v2 + Field 约束 + Validator | `models.py` 全部模型，`Field(ge/le/min_length)` |
| Day 03 | FastAPI 路由 + Path/Query/Body | 三个 router，Path 参数 `{id}`，Query 分页 |
| Day 04 | Depends + 异常处理 + 中间件 | `dependencies.py` 依赖注入，全局异常 handler，trace 中间件 |
| Day 05 | async/await + 异步数据库 | `database.py` async SQLite，所有路由 `await db.execute(...)` |
| Day 06 | SSE 流式 + 文件上传 + API 设计 | `conversations.py` SSE 端点，`uploads.py` 文件上传，RESTful 路由树 |
| **Day 07** | **综合产出** | **这个项目** |

---

## Day 07 检查清单

- [ ] 项目能正常启动（`uvicorn main:app --reload`）
- [ ] Swagger 文档（`/docs`）能看到所有路由
- [ ] 能创建 Agent（名称为空时报 422）
- [ ] 能创建对话（agent_id 不存在时报 404）
- [ ] 能发消息并收到 LLM 回复
- [ ] 能查看历史消息
- [ ] SSE 流式端点能逐字输出
- [ ] 文件上传能保存并返回信息
- [ ] 统计端点返回正确的数字
- [ ] 所有接口返回统一 `{"success": true, "data": ...}` 格式
- [ ] 请求日志有 `[request_id]` 前缀

## 本周总结

```
这周写了一个能跑的项目：
项目路径：agent_platform/
启动命令：uvicorn main:app --reload
代码行数（大概）：________

最大的收获：
________________________________

踩过最大的坑 & 怎么解决的：
________________________________

还没搞懂的（诚实写）：
________________________________

这个项目接下来我想加的功能：
________________________________

用 Claude Code 的感觉（和不用有什么区别）：
________________________________
```

---

## 下周预告

Week 02 进入 LLM 原理层：Token 机制、Thinking/Effort、Prompt Caching、封装一个真正的对话 API 服务。

但更重要的是——**下周你写的每个 API 都能挂到这个 agent_platform 项目上**。它不是一次性作业，是会持续生长的底座。
