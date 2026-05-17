# Day 06 — API 设计 + 流式响应 + 文件上传

## 学习目标

掌握 Agent API 的 RESTful 设计规范、SSE 流式响应（让用户实时看到 LLM 输出）、文件上传处理（语音/图片输入），以及中间件进阶技巧。这些是 Agent 服务从 Demo 变成可用的关键。

---

## 一、Agent API 的 RESTful 设计

### 1.1 资源命名规范

```python
# ✅ 好的设计 — 名词复数 + 层级清晰
GET    /api/v1/conversations                    # 列出对话
POST   /api/v1/conversations                    # 创建对话
GET    /api/v1/conversations/{conv_id}          # 获取对话详情
DELETE /api/v1/conversations/{conv_id}          # 删除对话
GET    /api/v1/conversations/{conv_id}/messages # 获取对话的消息列表
POST   /api/v1/conversations/{conv_id}/messages # 发送消息（触发 Agent）

# ❌ 差的设计 — 动词 + 不统一
POST /api/v1/chat
GET  /api/v1/getMessages?convId=123
POST /api/v1/deleteConversation
```

**Agent 项目推荐的 URL 结构：**

```
/api/v1/
├── conversations/           # 对话管理
│   ├── {conv_id}/
│   │   ├── messages/        # 消息
│   │   └── context/         # 上下文（注入的知识/工具）
├── agents/                  # Agent 配置
│   └── {agent_id}/
│       ├── tools/           # Agent 绑定的工具
│       └── stats/           # 统计（token/调用次数）
├── tools/                   # 工具注册中心
├── uploads/                 # 文件上传（语音、图片）
└── health                   # 健康检查
```

### 1.2 统一响应格式

```python
# 整个项目用同一个响应格式，前端不用猜
from pydantic import BaseModel
from typing import Generic, TypeVar

T = TypeVar("T")

class APIResponse(BaseModel, Generic[T]):
    """统一响应格式"""
    success: bool = True
    data: T | None = None
    error: str | None = None
    meta: dict | None = None  # 分页信息等

class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int

# 使用
@app.get("/api/v1/conversations", response_model=APIResponse[list[ConversationOut]])
async def list_conversations(page: int = 1, page_size: int = 20):
    conversations = [...]
    return APIResponse(
        success=True,
        data=conversations,
        meta={"page": page, "page_size": page_size, "total": 100, "total_pages": 5},
    )

# 错误时
@app.get("/api/v1/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = find_conversation(conv_id)
    if not conv:
        return JSONResponse(
            status_code=404,
            content=APIResponse(success=False, error="对话不存在", data=None).model_dump(),
        )
    return APIResponse(success=True, data=conv)
```

### 1.3 Agent 路由最佳实践

```python
from fastapi import APIRouter

# 按模块拆分路由文件
# routers/conversations.py
conv_router = APIRouter(prefix="/api/v1/conversations", tags=["对话管理"])

@conv_router.post("/")
async def create_conversation(...): ...

@conv_router.get("/{conv_id}/messages")
async def list_messages(...): ...

# routers/agents.py
agent_router = APIRouter(prefix="/api/v1/agents", tags=["Agent 配置"])

# routers/tools.py
tool_router = APIRouter(prefix="/api/v1/tools", tags=["工具管理"])

# main.py — 统一注册
app = FastAPI()
app.include_router(conv_router)
app.include_router(agent_router)
app.include_router(tool_router)
```

---

## 二、SSE 流式响应 —— Agent 交互的核心体验

LLM 生成一个 500 字的回答可能需要 5-10 秒。如果等全部生成完再返回，用户盯着白屏干等。**SSE 流式输出让用户实时看到每个字**，体验完全不同。

### 2.1 SSE 原理

```
普通 HTTP：
  客户端 ──请求──→ 服务端 ──等待5秒生成完──→ 一次性返回全部内容

SSE：
  客户端 ──请求──→ 服务端 ──data: "今"\n\n──→
                           ──data: "天"\n\n──→
                           ──data: "天"\n\n──→
                           ──data: "气"\n\n──→
                           ...
                           ──data: [DONE]\n\n──→ 关闭连接
```

**SSE 就是服务端持续往一个 HTTP 连接写数据，客户端用 `EventSource` 读。** 比 WebSocket 简单得多，单向即可。

### 2.2 FastAPI 实现 SSE

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import httpx
import json

@app.post("/api/v1/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式 Agent 对话"""
    async def generate():
        async with httpx.AsyncClient(timeout=60) as client:
            # 调用 Claude Streaming API
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": request.model,
                    "max_tokens": request.max_tokens,
                    "messages": [m.model_dump() for m in request.messages],
                    "stream": True,  # ← 关键
                },
            ) as response:
                full_text = ""
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])

                        # Claude SSE 的事件类型
                        if data.get("type") == "content_block_delta":
                            text = data["delta"].get("text", "")
                            full_text += text
                            # 每收到一个字就推给前端
                            yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"

                        elif data.get("type") == "message_delta":
                            usage = data.get("usage", {})
                            yield f"data: {json.dumps({'type': 'usage', 'usage': usage})}\n\n"

                # 结束信号
                yield f"data: {json.dumps({'type': 'done', 'full_text': full_text})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx 下禁用缓冲
        },
    )
```

### 2.3 前端消费 SSE

```javascript
// 前端 JavaScript
async function streamChat(message) {
  const resp = await fetch("/api/v1/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: message }] }),
  });

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();  // 保留未完成的最后一行

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = JSON.parse(line.slice(6));
        if (data.type === "text") {
          // 逐字追加到 UI
          appendToChat(data.content);
        } else if (data.type === "done") {
          console.log("生成完成，全文:", data.full_text);
        }
      }
    }
  }
}
```

### 2.4 简化版 sse-starlette

```python
# pip install sse-starlette — 更简洁的写法
from sse_starlette.sse import EventSourceResponse

@app.post("/api/v1/chat/stream")
async def chat_stream(request: ChatRequest):
    async def generate():
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", "...", json={...}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        if data.get("type") == "content_block_delta":
                            yield {"event": "text", "data": data["delta"].get("text", "")}
                        elif data.get("type") == "message_delta":
                            yield {"event": "usage", "data": json.dumps(data.get("usage", {}))}
            yield {"event": "done", "data": ""}

    return EventSourceResponse(generate())
```

---

## 三、文件上传 —— 语音/图片输入

养老护工系统里，护工上传录音文件，后端做语音识别。FastAPI 处理文件上传非常简洁。

### 3.1 单文件上传

```python
from fastapi import UploadFile, File

@app.post("/api/v1/upload/audio")
async def upload_audio(file: UploadFile = File(...)):
    """
    上传语音文件，返回 ASR 识别文本
    file: UploadFile 提供 .filename / .content_type / .read() / .size
    """
    # 校验文件类型
    ALLOWED_TYPES = {"audio/wav", "audio/mpeg", "audio/webm", "audio/mp4"}
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file.content_type}")

    # 校验文件大小（UploadFile 默认没有 .size，需要读完后才知道）
    contents = await file.read()
    max_size = 10 * 1024 * 1024  # 10MB
    if len(contents) > max_size:
        raise HTTPException(status_code=400, detail=f"文件超过 {max_size // 1024 // 1024}MB 限制")

    # 保存文件
    file_path = f"uploads/audio/{uuid.uuid4()}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(contents)

    # 调 ASR 服务（腾讯云 / Whisper）
    # transcript = await asr_service.transcribe(file_path)

    return APIResponse(success=True, data={
        "filename": file.filename,
        "size_bytes": len(contents),
        "file_path": file_path,
        # "transcript": transcript,
    })
```

### 3.2 多文件上传 + 批量处理

```python
from fastapi import UploadFile, File, Form
from typing import Annotated

@app.post("/api/v1/upload/audio/batch")
async def upload_multiple_audio(
    files: list[UploadFile] = File(...),
    elder_id: str = Form(...),  # 附加表单字段
    caregiver_id: str = Form(...),
):
    """批量上传照护录音"""
    results = []
    for file in files:
        contents = await file.read()
        results.append({
            "filename": file.filename,
            "size": len(contents),
            "saved": True,
        })
    return APIResponse(success=True, data={
        "elder_id": elder_id,
        "caregiver_id": caregiver_id,
        "files": results,
    })
```

### 3.3 UploadFile vs bytes

```python
# 方式一：UploadFile（推荐）— 流式读取，适合大文件
@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    contents = await file.read()  # 或逐块读: async for chunk in file

# 方式二：bytes — 整个文件读到内存，只适合小文件
@app.post("/upload")
async def upload(file: bytes = File(...)):
    # file 已经是 bytes，10MB 文件直接占 10MB 内存
    pass
```

**永远用 `UploadFile`，除非你确定文件不超过 1MB。**

---

## 四、中间件进阶

Day 04 学过的中间件基础（日志、限流、CORS），这里补充两个 Agent 项目里的高频需求。

### 4.1 请求体日志中间件（排障必备）

```python
from fastapi import Request
import json

@app.middleware("http")
async def log_request_body(request: Request, call_next):
    """记录请求体内容（调试 Agent 输入用）"""
    # 只记录 POST/PUT/PATCH 的 body
    if request.method in ("POST", "PUT", "PATCH"):
        body_bytes = await request.body()
        try:
            body_text = body_bytes.decode()[:500]  # 截断，最多 500 字符
            print(f"[BODY] {request.url.path}: {body_text}")
        except Exception:
            print(f"[BODY] {request.url.path}: <无法解码>")

        # 重要：重新构造 Request，因为 body 只能读一次
        async def receive():
            return {"type": "http.request", "body": body_bytes}
        request._receive = receive

    return await call_next(request)
```

### 4.2 请求 ID 追踪

```python
import uuid
from contextvars import ContextVar

# ContextVar 是协程安全的"线程局部变量"
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """给每个请求打上唯一 ID，日志可追踪"""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    request_id_ctx.set(request_id)

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# 在任何地方获取当前请求 ID
def get_request_id() -> str:
    return request_id_ctx.get()

@app.post("/chat")
async def chat(...):
    print(f"[{get_request_id()}] 用户发来消息")
    # [a1b2c3d4] 用户发来消息
```

---

## 五、完整实战 —— 流式 Agent 对话 API

串联 Day 01~06 的知识，写一个生产级的流式 Agent 对话服务：

```python
"""
流式 Agent 对话 API — 终极版
- SSE 流式输出 LLM 回复
- 文件上传（语音）
- 异步数据库存储对话历史
- 请求 ID 追踪 + 完整日志
- 统一响应格式
"""
from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, APIRouter
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from contextvars import ContextVar
import httpx
import json
import uuid
import time
import os

app = FastAPI(title="Agent API Pro", version="1.0.0")

# ====== 全局上下文 ======
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

# ====== 中间件 ======
@app.middleware("http")
async def trace_and_log(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    request_id_ctx.set(rid)
    start = time.time()
    response = await call_next(request)
    elapsed_ms = (time.time() - start) * 1000
    response.headers["X-Request-ID"] = rid
    print(f"[{rid}] {request.method} {request.url.path} → {response.status_code} ({elapsed_ms:.0f}ms)")
    return response

# ====== 数据模型 ======
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    model: str = Field(default="claude-sonnet-4-6")

class APIResponse(BaseModel):
    success: bool = True
    data: dict | None = None
    error: str | None = None

# ====== 依赖 ======
async def get_llm_client():
    async with httpx.AsyncClient(
        base_url="https://api.anthropic.com/v1",
        headers={
            "x-api-key": os.getenv("ANTHROPIC_API_KEY", ""),
            "anthropic-version": "2023-06-01",
        },
        timeout=60,
    ) as client:
        yield client

# ====== 流式对话 ======
@app.post("/api/v1/chat/stream")
async def chat_stream(
    request: ChatRequest,
    llm: httpx.AsyncClient = Depends(get_llm_client),
):
    """流式 Agent 对话"""

    async def event_stream():
        rid = request_id_ctx.get()
        full_text = ""

        try:
            async with llm.stream("POST", "/messages", json={
                "model": request.model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": request.message}],
                "stream": True,
            }) as resp:
                if resp.status_code != 200:
                    error_text = await resp.aread()
                    yield f"data: {json.dumps({'type': 'error', 'detail': error_text.decode()[:200]})}\n\n"
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

            # 存数据库（异步，不阻塞 SSE 结束）
            # await save_message(conv_id, "user", request.message)
            # await save_message(conv_id, "assistant", full_text)

            yield f"data: {json.dumps({'type': 'done', 'full_length': len(full_text)})}\n\n"

        except Exception as e:
            print(f"[{rid}] 流式错误: {e}")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-ID": request_id_ctx.get(),
        },
    )


# ====== 文件上传 ======
@app.post("/api/v1/upload/audio")
async def upload_audio(file: UploadFile = File(...)):
    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件超过 10MB 限制")

    filename = f"{uuid.uuid4()}_{file.filename}"
    save_path = f"uploads/audio/{filename}"
    os.makedirs("uploads/audio", exist_ok=True)
    with open(save_path, "wb") as f:
        f.write(contents)

    return APIResponse(success=True, data={"filename": file.filename, "path": save_path, "size": len(contents)})


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
```

---

## 六、今日练习（约 2.5 小时）

### 练习 1：设计 Agent API 路由结构（20 min）

画一个养老护工系统的 API 路由树，至少包含：
- 语音上传
- 照护记录 CRUD
- 老人信息查询
- 趋势分析（调用 Agent）

用 APIRouter 拆成独立文件（不要求全实现，画结构即可）。

### 练习 2：实现 SSE 流式 API（40 min）

基于 Day 05 的 `/chat` 端点，改成 SSE 流式版本：
1. 用 `httpx.stream()` 调 Claude streaming API
2. 解析 `content_block_delta` 事件
3. 用 `StreamingResponse` 返回
4. 用 curl 或浏览器 fetch 测试

### 练习 3：文件上传 + 处理（30 min）

实现一个音频上传端点，包含：
- 文件类型校验（白名单）
- 大小限制（10MB）
- 保存到本地 `uploads/` 目录
- 返回文件信息（文件名、大小、路径）

### 练习 4：请求 ID 追踪（20 min）

给已有项目加上请求 ID 中间件：
1. 从请求头读取 `X-Request-ID`，没有则自动生成
2. 用 `ContextVar` 存储
3. 在所有日志输出前加上 `[request_id]`
4. 响应头中返回 `X-Request-ID`

### 练习 5：统一响应格式改造（40 min）

把 Day 05 的 Agent API 改造为统一响应格式：
- 所有成功返回 `{"success": true, "data": ...}`
- 所有错误返回 `{"success": false, "error": "..."}`
- 不需要改动 Day 04 的异常处理器，和它配合

---

## 七、踩坑记录

```
// 写代码时记录：

[ ] 坑 1：____________________
解决：____________________

[ ] 坑 2：____________________
解决：____________________
```

**常见坑预警：**

| 坑 | 表现 | 解决 |
|----|------|------|
| ❌ SSE 中途断开 | 前端收了一半就停了 | 检查 Nginx 配置 `proxy_buffering off`；检查 `X-Accel-Buffering: no` |
| ❌ `StreamingResponse` 用了但没效果 | 等全部生成完才一次性返回 | 生成器里每一步 yield 后可能被框架缓冲，检查是否用了 `response.media_type` |
| ❌ `UploadFile` 读第二次为空 | `await file.read()` 只能读一次 | 第一次读后缓存到变量，下次用变量 |
| ❌ `await file.read()` 不 await | `coroutine object has no attribute 'xxx'` | `UploadFile.read()` 是 async 方法，必须 await |
| ❌ `ContextVar` 在普通线程里失效 | 获取不到值 | ContextVar 只在同一个协程上下文里有效，线程切换会丢失 |
| ❌ 大文件上传内存爆 | 上传 100MB 文件 OOM | 用 `file.read(chunk_size)` 分块读取 |

---

## Day 06 检查清单

- [ ] 能设计符合 RESTful 规范的 Agent API 路由结构
- [ ] 能用 `StreamingResponse` 实现 SSE 流式输出
- [ ] 能解析 Claude streaming API 的事件类型
- [ ] 能用 `UploadFile` 接收文件并校验类型和大小
- [ ] 能理解 `UploadFile` vs `bytes` 的区别
- [ ] 能用 `ContextVar` 实现请求级上下文传递
- [ ] 能用 `APIRouter` 拆分路由到独立模块
- [ ] 能设计统一的 `APIResponse` 响应格式

---

## 副线：Claude Code 实战（20 min）

### 今天的任务：给你的项目写一个 CLAUDE.md

`CLAUDE.md` 是 Claude Code 的项目记忆文件，告诉它你的项目结构、技术栈、约定和偏好。写好它，Claude Code 就不再是通用助手，而是熟悉你项目的专属搭档。

**Step 1 — 创建 CLAUDE.md：**

在你正在写的 FastAPI 项目根目录下创建 `CLAUDE.md`：

```markdown
# CLAUDE.md

## 项目概述
Agent 对话管理平台 — FastAPI 后端，支持多 Agent 对话、SSE 流式输出、异步数据库。

## 技术栈
- FastAPI (Python 3.11+)
- SQLAlchemy async + SQLite/aiosqlite
- Pydantic v2
- httpx (async client)
- sse-starlette

## 项目结构
agent_platform/
├── main.py          # 应用入口，中间件 + 异常处理 + 路由注册
├── database.py      # SQLAlchemy async 引擎 + 表定义
├── models.py        # Pydantic 请求/响应模型
├── dependencies.py  # Depends 依赖函数
├── schemas.py       # 统一响应 APIResponse
├── routers/         # 按资源拆分的路由模块
│   ├── agents.py
│   ├── conversations.py
│   └── uploads.py
└── uploads/audio/   # 上传文件存储

## 约定
- 所有路由函数用 async def
- 数据库操作用 SQLAlchemy async（select + await db.execute）
- API 响应统一用 APIResponse(success=..., data=..., error=...)
- 路由前缀 /api/v1/
- 异常不裸抛，用 HTTPException 或自定义 AgentError

## 当前阶段
Week 01 Day 06 — 正在实现 SSE 流式响应和文件上传
```

**Step 2 — 验证 CLAUDE.md 是否生效：**

新开一个 Claude Code 对话（或 `/clear`），不要额外解释，直接问：

```
"帮我在 conversations.py 里加一个 GET /api/v1/conversations/{id}/export 端点，导出对话为 JSON"
```

观察 Claude Code 是否：
- 自动读懂了你的项目结构，把端点加到了正确的 router
- 使用了你定义的 APIResponse 格式
- 用了 async def + await db.execute
- 遵循了约定的路由前缀

如果它做到了，说明 CLAUDE.md 写对了。如果没做到，回头看看 CLAUDE.md 里漏了什么。

**Step 3 — 日常习惯（从今天开始养成）：**

每次你写了一段新代码，或者学到一种新的模式，用 `/init` 命令更新 CLAUDE.md（或者手动改）。这 5 分钟的投入会在后续开发中省下大量解释成本。

### CLI Agent 认知笔记

```
今天 CLAUDE.md 写完后，Claude Code 的表现有什么变化：
________________________________

它还犯什么错（说明 CLAUDE.md 漏了什么）：
________________________________
```
