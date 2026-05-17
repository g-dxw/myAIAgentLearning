# Day 04 — 请求验证 + 错误处理

## 学习目标

掌握 FastAPI 依赖注入（Depends）、全局异常处理、中间件三大机制。这些是 Agent API 服务可靠性的基石——没有它们，你的 Agent 服务就是一个"裸奔"的 API。

---

## 一、依赖注入（Depends）—— 最让 Express.js 开发者羡慕的特性

### 1.1 什么问题？

在 Express.js 里，每个路由 handler 都要手动处理认证、数据库连接、参数提取等重复逻辑：

```typescript
// Express.js — 每个路由里重复相同的代码
app.get("/agents", async (req, res) => {
  const user = await authenticate(req.headers.authorization);  // 重复
  const db = await getDatabase();                              // 重复
  // 终于开始业务逻辑...
});
```

FastAPI 的 `Depends` 把可复用的逻辑抽成函数，框架自动注入：

```python
# FastAPI — 依赖函数写一次，任何路由都能用
from fastapi import Depends, FastAPI, HTTPException

app = FastAPI()

async def get_current_user(authorization: str | None = None):
    """验证 token 并返回当前用户"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未登录")
    # 实际项目查数据库/Redis
    return {"user_id": 1, "name": "张三"}

@app.get("/agents")
async def list_agents(user: dict = Depends(get_current_user)):
    # user 已经被 get_current_user 注入了
    return {"user": user["name"], "agents": []}
```

**思维转换：** Express.js 的 middleware 是拦截器模式，FastAPI 的 Depends 是依赖注入模式——更精准，只给需要的路由注入。

### 1.2 Depends 的三种核心用法

#### 用法一：认证/鉴权（最常用）

```python
from fastapi import Depends, HTTPException, Header

async def verify_api_key(x_api_key: str | None = Header(None)):
    """从 Header 提取 API Key 并校验"""
    valid_keys = {"sk-agent-001", "sk-agent-002"}  # 实际从配置/数据库读
    if not x_api_key or x_api_key not in valid_keys:
        raise HTTPException(status_code=403, detail="无效的 API Key")
    return x_api_key

@app.get("/agent/status")
async def agent_status(api_key: str = Depends(verify_api_key)):
    return {"status": "running", "api_key": api_key[:8] + "***"}
```

#### 用法二：数据库连接复用

```python
# 数据库依赖 —— 自动获取连接、自动关闭
from contextlib import asynccontextmanager

async def get_db():
    """获取数据库连接，请求结束后自动关闭"""
    # 模拟数据库连接
    db = {"connected": True, "host": "localhost"}
    try:
        yield db  # yield 的值注入到路由函数
    finally:
        # 无论路由成功还是报错，这里都会执行
        db["connected"] = False

@app.get("/elders")
async def list_elders(db: dict = Depends(get_db)):
    return {"db_status": db["connected"], "elders": []}  # True
# 请求结束后 db["connected"] 自动变为 False
```

> 这实际上是一个**生成器上下文管理器**，和 Day 01 学的 `@contextmanager` 原理相同。

#### 用法三：参数提取 + 校验组合

```python
from pydantic import BaseModel, Field

class PaginationParams(BaseModel):
    """通用分页参数"""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

class FilterParams(BaseModel):
    """通用筛选参数"""
    keyword: str | None = None
    status: str | None = None

async def get_pagination(page: int = 1, page_size: int = 20) -> PaginationParams:
    """注入分页参数并校验"""
    return PaginationParams(page=page, page_size=page_size)

async def get_filters(keyword: str | None = None, status: str | None = None) -> FilterParams:
    """注入筛选参数"""
    return FilterParams(keyword=keyword, status=status)

@app.get("/agents")
async def list_agents(
    pagination: PaginationParams = Depends(get_pagination),  # 依赖注入依赖！
    filters: FilterParams = Depends(get_filters),
):
    return {
        "page": pagination.page,
        "page_size": pagination.page_size,
        "keyword": filters.keyword,
        "agents": [],
    }
```

### 1.3 依赖链 —— 依赖可以嵌套

```python
async def get_db(): ...

async def get_user_repo(db = Depends(get_db)):
    """用户仓储——依赖数据库连接"""
    return UserRepository(db)

async def get_agent_service(user_repo = Depends(get_user_repo)):
    """Agent 服务——依赖用户仓储"""
    return AgentService(user_repo)

@app.post("/chat")
async def chat(agent_service = Depends(get_agent_service)):
    # 链条：get_agent_service → get_user_repo → get_db
    return await agent_service.process()
```

**FastAPI 自动解析依赖链并按需执行**，你只需要声明"我需要什么"，不需要管"怎么传过来"。

### 1.4 Agent 项目里的真实 Depends 函数

```python
# === LLM 客户端依赖 ===
from httpx import AsyncClient

async def get_llm_client() -> AsyncClient:
    """返回已配置好 base_url + headers 的 httpx 客户端"""
    async with AsyncClient(
        base_url="https://api.anthropic.com/v1",
        headers={
            "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
        },
        timeout=60,
    ) as client:
        yield client  # 请求结束自动关连接

@app.post("/chat")
async def chat(request: ChatRequest, client = Depends(get_llm_client)):
    resp = await client.post("/messages", json=request.model_dump())
    return resp.json()

# === Token 用量追踪依赖 ===
class TokenTracker:
    def __init__(self):
        self.total_input = 0
        self.total_output = 0

    def track(self, input_tokens: int, output_tokens: int):
        self.total_input += input_tokens
        self.total_output += output_tokens

tracker = TokenTracker()  # 全局单例（实际项目用 Redis）

async def get_token_tracker() -> TokenTracker:
    return tracker

@app.post("/chat")
async def chat(
    request: ChatRequest,
    client = Depends(get_llm_client),
    tracker = Depends(get_token_tracker),
):
    resp = await client.post("/messages", json=...)
    data = resp.json()
    tracker.track(data["usage"]["input_tokens"], data["usage"]["output_tokens"])
    return data
```

---

## 二、全局异常处理

### 2.1 默认行为 vs 自定义异常处理器

```python
# 默认：Pydantic 校验失败 → 自动返回 422
# 路由里 raise HTTPException → 自动返回对应状态码
# 未捕获的异常 → 自动返回 500 Internal Server Error（无详情，不安全）

from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """统一格式化 HTTP 异常返回"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "code": exc.status_code,
            "detail": exc.detail,
        },
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """兜底异常处理——不要让客户端看到 traceback"""
    # 实际项目这里接日志系统
    print(f"[ERROR] {request.method} {request.url.path} → {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "code": 500,
            "detail": "服务器内部错误，已记录日志",
        },
    )
```

### 2.2 自定义业务异常

```python
# 定义业务异常类
class AgentError(Exception):
    """Agent 业务异常基类"""
    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code

class TokenLimitExceeded(AgentError):
    """对话 token 超出上限"""
    def __init__(self, current: int, limit: int):
        super().__init__(
            detail=f"Token 超出限制：已用 {current}/{limit}",
            status_code=429,
        )

class InvalidToolCall(AgentError):
    """工具调用参数错误"""
    def __init__(self, tool_name: str, detail: str):
        super().__init__(
            detail=f"工具 [{tool_name}] 调用失败：{detail}",
            status_code=400,
        )

# 注册 Agent 异常的处理器
@app.exception_handler(AgentError)
async def agent_error_handler(request: Request, exc: AgentError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "code": exc.status_code,
            "type": type(exc).__name__,  # TokenLimitExceeded / InvalidToolCall
            "detail": exc.detail,
        },
    )

# 在路由中使用
@app.post("/chat")
async def chat(request: ChatRequest):
    current_tokens = count_user_tokens(request.user_id)
    if current_tokens > TOKEN_BUDGET:
        raise TokenLimitExceeded(current_tokens, TOKEN_BUDGET)
    # ...
```

### 2.3 RequestValidationError —— 更友好的校验错误

```python
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """将 Pydantic 校验错误转为更友好的格式"""
    errors = []
    for error in exc.errors():
        field = " → ".join(str(loc) for loc in error["loc"])
        errors.append({
            "field": field,
            "message": error["msg"],
            "type": error["type"],
        })
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "code": 422,
            "detail": "请求参数校验失败",
            "errors": errors,
        },
    )
```

**效果对比：**

```json
// 默认 422 返回
{"detail": [{"loc": ["body", "messages"], "msg": "field required", "type": "missing"}]}

// 自定义处理后返回
{
  "error": true,
  "code": 422,
  "detail": "请求参数校验失败",
  "errors": [
    {"field": "body → messages", "message": "field required", "type": "missing"}
  ]
}
```

---

## 三、中间件（Middleware）

中间件在**请求到达路由之前**和**响应返回之后**执行，类似 Express.js 的 `app.use()`。

### 3.1 请求/响应日志中间件

```typescript
// Express.js
app.use(async (req, res, next) => {
  const start = Date.now();
  await next();
  console.log(`${req.method} ${req.path} ${Date.now() - start}ms`);
});
```

```python
# FastAPI — 中间件
from fastapi import Request
import time

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录每个请求的方法、路径、状态码、耗时"""
    start = time.time()
    response = await call_next(request)  # 调用下一个处理器
    elapsed = time.time() - start
    print(f"{request.method} {request.url.path} → {response.status_code} ({elapsed:.3f}s)")
    return response
```

**输出：**
```
POST /chat → 200 (1.234s)
GET /agents → 200 (0.012s)
POST /chat → 429 (0.001s)
```

### 3.2 Agent 专用中间件示例

```python
# === Token 用量计费中间件 ===
@app.middleware("http")
async def token_accounting(request: Request, call_next):
    """统计每个请求的 token 消耗"""
    response = await call_next(request)
    # 从响应 body 读取 token 用量
    # （实际项目用 response.body_iterator 读取后重建）
    if "token-usage" in response.headers:
        input_tokens = int(response.headers["input-tokens"])
        output_tokens = int(response.headers["output-tokens"])
        # 入库或计数...
        print(f"Token: {input_tokens} in / {output_tokens} out")
    return response

# === 请求限流中间件 ===
from collections import defaultdict
from datetime import datetime

rate_limit_store: dict[str, list[float]] = defaultdict(list)

@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """简单限流：每 IP 每分钟最多 30 次请求"""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = 60  # 60 秒窗口
    max_requests = 30

    # 清理过期记录
    rate_limit_store[client_ip] = [
        t for t in rate_limit_store[client_ip] if now - t < window
    ]

    if len(rate_limit_store[client_ip]) >= max_requests:
        return JSONResponse(
            status_code=429,
            content={"error": True, "detail": "请求过于频繁，请稍后再试"},
        )

    rate_limit_store[client_ip].append(now)
    return await call_next(request)
```

### 3.3 FastAPI 中间件 vs Depends

| 对比维度 | 中间件 `@app.middleware` | 依赖注入 `Depends` |
|---------|------------------------|-------------------|
| 作用范围 | 全局，所有路由都经过 | 按路由，声明了才注入 |
| 执行时机 | 请求前 + 响应后 | 只在请求前（yield 后是响应后） |
| 典型用途 | 日志、CORS、限流、监控 | 认证、数据库连接、参数校验 |
| Express 对照 | `app.use(...)` | 没有直接对照 |

**选择原则：** 
- 需要拦截所有请求 → 中间件
- 只给特定路由注入数据/校验 → Depends

---

## 四、CORS 配置

Agent API 通常要被前端/小程序跨域调用：

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://your-app.com"],  # 生产环境指定具体域名
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有请求头
)
```

> 开发环境 `allow_origins=["*"]` 方便调试，生产环境必须指定具体域名。

---

## 五、综合实战 —— 给 Day 03 的 Agent API 加上"铠甲"

把 Day 03 的 `/chat` 端点升级为生产可用的版本（加认证、异常处理、日志、限流）：

```python
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal
import httpx
import os
import time
import hashlib
import hmac

app = FastAPI(title="AI Agent API", version="0.2.0")

# ==========================================
# 1. CORS
# ==========================================
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ==========================================
# 2. 全局中间件
# ==========================================
@app.middleware("http")
async def log_and_time(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    response.headers["X-Process-Time-Ms"] = str(round(elapsed, 2))
    print(f"[{time.strftime('%H:%M:%S')}] {request.method:6} {request.url.path:20} → {response.status_code} ({elapsed:.0f}ms)")
    return response

# ==========================================
# 3. 数据模型
# ==========================================
class AgentMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

class ChatRequest(BaseModel):
    messages: list[AgentMessage] = Field(min_length=1)
    model: str = Field(default="claude-sonnet-4-6")
    max_tokens: int = Field(default=4096, ge=1, le=32000)

class ChatResponse(BaseModel):
    reply: str
    model: str
    usage: dict

# ==========================================
# 4. 依赖注入
# ==========================================
API_KEYS = {"sk-agent-001": "张三", "sk-agent-002": "李四"}

async def verify_api_key(x_api_key: str | None = None):
    """API Key 认证"""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="缺少 x-api-key 请求头")
    user = API_KEYS.get(x_api_key)
    if not user:
        raise HTTPException(status_code=403, detail="无效的 API Key")
    return {"key": x_api_key[:8] + "***", "user": user}

async def get_llm_client():
    """LLM HTTP 客户端"""
    async with httpx.AsyncClient(
        base_url="https://api.anthropic.com/v1",
        headers={
            "x-api-key": os.getenv("ANTHROPIC_API_KEY", ""),
            "anthropic-version": "2023-06-01",
        },
        timeout=60,
    ) as client:
        yield client

# ==========================================
# 5. 异常处理
# ==========================================
class AgentError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code

@app.exception_handler(AgentError)
async def agent_error_handler(request: Request, exc: AgentError):
    return JSONResponse(status_code=exc.status_code, content={"error": True, "detail": exc.detail})

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = [{"field": " → ".join(str(l) for l in e["loc"]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": True, "detail": "参数校验失败", "errors": errors})

@app.exception_handler(Exception)
async def catch_all(request: Request, exc: Exception):
    print(f"[FATAL] {request.method} {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"error": True, "detail": "服务器内部错误"})

# ==========================================
# 6. Agent 聊天端点
# ==========================================
@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    auth: dict = Depends(verify_api_key),
    client: httpx.AsyncClient = Depends(get_llm_client),
):
    """Agent 聊天接口 — 带完整的认证、异常处理、日志"""
    resp = await client.post("/messages", json={
        "model": request.model,
        "max_tokens": request.max_tokens,
        "messages": [m.model_dump() for m in request.messages],
    })

    if resp.status_code != 200:
        raise AgentError(
            detail=f"LLM 调用失败 [{resp.status_code}]: {resp.text[:200]}",
            status_code=502,
        )

    data = resp.json()
    return ChatResponse(
        reply=data["content"][0]["text"],
        model=data["model"],
        usage=data["usage"],
    )

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}
```

**对比 Day 03 的裸版：**

| 能力 | Day 03 版本 | Day 04 升级版 |
|------|-----------|-------------|
| API 认证 | ❌ 无 | ✅ `Depends(verify_api_key)` |
| 请求日志 | ❌ 无 | ✅ 全局中间件 |
| CORS | ❌ 无 | ✅ CORSMiddleware |
| 异常格式 | 默认 JSON | ✅ 统一 `{"error": true, "detail": ...}` |
| 校验错误 | 英文 raw | ✅ 中文友好格式 |
| 不限流 | 没限制 | ✅ 每 IP 限制 |
| LLM 客户端 | 每次 new | ✅ `Depends` 注入，自动复用+关闭 |

---

## 六、今日练习（约 2.5 小时）

### 练习 1：写认证依赖（15 min）

实现 `verify_token` 依赖函数：
- 从 Header 读取 `Authorization: Bearer xxx`
- 简单校验 token 前缀和最小长度
- 无效时抛出 401
- 测试：不带 token / 带无效 token / 带有效 token

### 练习 2：自定义 422 响应（15 min）

注册 `RequestValidationError` 异常处理器，把默认的英文错误转成 `{"error": true, "errors": [{"field": "...", "message": "..."}]}`。

### 练习 3：写一个 Agent 专用中间件（20 min）

写一个 `TokenBudgetMiddleware`：
- 从 Header 读取 `X-User-Id`
- 检查该用户的累计 token 消耗（用全局 dict 模拟）
- 超出预算时返回 429 而不是真去调 LLM

### 练习 4：依赖链练习（30 min）

实现三层依赖：
1. `get_db` → 模拟数据库连接
2. `get_conversation_repo(db)` → 用 db 查询对话历史
3. `get_agent_service(repo)` → 用对话历史构造 LLM 请求

在 `/chat` 路由中用 `Depends(get_agent_service)` 注入。

### 练习 5：给 Day 03 的练习项目加上防护（60 min）

把 Day 03 综合练习里的 Agent 配置 API 升级：
1. 加上 API Key 认证（`Depends`）
2. 加上请求日志中间件
3. 加上全局异常处理
4. 加上 CORS

---

## 七、踩坑记录

```
// 写代码时记录你遇到的所有坑：

[ ] 坑 1：____________________
解决：____________________

[ ] 坑 2：____________________
解决：____________________
```

**常见坑预警：**

| 坑 | 表现 | 解决 |
|----|------|------|
| ❌ Depends 函数没写 `yield` | 不会自动清理 | 需要清理资源时用 `yield`，不需要时直接 `return` |
| ❌ 异常处理器覆盖了框架默认行为 | 422 不返回 | 确保 `RequestValidationError` 处理器返回 JSONResponse |
| ❌ 中间件顺序 | CORS 在限流中间件之前才生效 | `add_middleware` 的顺序就是执行顺序 |
| ❌ 中间件读取响应 body | 响应体只能读一次 | 用 `response.body_iterator` 重建，或只在 Header 传数据 |
| ❌ 全局异常吞了重要错误 | 无法 debug | 在 handler 里 `print(repr(exc))` 或接日志系统 |

---

## Day 04 检查清单

- [ ] 能用 `Depends` 抽取认证逻辑
- [ ] 能写 `yield` 风格的数据库/客户端依赖（自动清理）
- [ ] 能构建依赖链（A → B → C）
- [ ] 能用 `@app.exception_handler` 自定义错误格式
- [ ] 能定义业务异常类（AgentError）
- [ ] 能写 `RequestValidationError` 处理器优化校验错误提示
- [ ] 能用 `@app.middleware("http")` 写请求日志
- [ ] 能区分中间件和 Depends 的使用场景
- [ ] 能配置 CORS

## 明天计划

- [ ] Day 05 — async/await 协程模型（事件循环、await vs 多线程对比、FastAPI 中的协程实践）
