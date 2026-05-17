from collections import defaultdict
from contextlib import asynccontextmanager
import time
from fastapi.params import Header
from pydantic import Field
from typing_extensions import Literal
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import httpx
from openai import BaseModel

# 全局单例 client
llm_client: httpx.AsyncClient | None = None
@asynccontextmanager
async def lifespan(app: FastAPI):
    global llm_client
    llm_client = httpx.AsyncClient(
        base_url="https://api.deepseek.com",
        headers={"Authorization": f"Bearer ===="},
        timeout=httpx.Timeout(60.0, connect=10.0),  # 细分超时
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)  # 连接池
    )
    yield
    await llm_client.aclose()


app = FastAPI(title="AI Agent API", version="1.0.0", description="API for AI Agent", lifespan=lifespan)

# 跨越CORS中间件，允许所有来源、方法和头部
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 全局中间件
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

@app.middleware("http")
async def token_accounting_middleware(request: Request, call_next):
    '''添加Token计费头部'''
    response = await call_next(request)
    if "token-usage" in response.headers:
        input_tokens = int(response.headers["input_tokens"])
        output_tokens = int(response.headers["output_tokens"])
        # 记录Token使用情况
        print(f"Token Usage - Input: {input_tokens}, Output: {output_tokens}")
    return response

# 限流中间件
rate_limit_store: dict[str, list[float]] = defaultdict(list)
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    '''添加限流头部'''
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    print(1)
    window = 60
    max_requests = 2

    rate_limit_store[client_ip] = [
                                    timestamp 
                                    for timestamp in rate_limit_store[client_ip] 
                                    if timestamp > now - window
                                ]
    print(len(rate_limit_store[client_ip]))
    if len(rate_limit_store[client_ip]) >= max_requests:
        return JSONResponse(status_code=429, 
                           content={"detail": "请求过多，请稍后再试", "error": True, "code": 429})  
    rate_limit_store[client_ip].append(now)
    return await call_next(request)


# 异常处理
class AgetError(Exception):
    '''agent 异常处理'''
    def __init__(self, detail: str, status_code: int = 400):
        self.status_code = status_code
        self.detail = detail

@app.exception_handler(AgetError)
async def agent_error_handler(request: Request, exc: AgetError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "error": True, "code": exc.status_code}
    )
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [{"field": " → ".join(str(loc) for loc in error["loc"]), "detail": error["msg"]} for error in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={"detail": "参数校验错误", "errors": errors, "error": True, "code": 422}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    print(f"[FATAL] {request.method} {request.url} - {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "内部服务器错误", "error": True, "code": 500}
    )

API_KEYS = {"sk-agent-001": "张三", "sk-agent-002": "李四"}


# 依赖注入
async def verify_token(x_api_key: str | None = Header(None, alias="X-API-Key")):
    print(x_api_key)
    print(2)
    if not x_api_key:
        raise HTTPException(status_code=401, detail="缺少API密钥")
    user = API_KEYS.get(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="无效的API密钥")
    return {
        "key": x_api_key[:8],
        "user": user
    }

async def get_llm_client() -> httpx.AsyncClient:
    if not llm_client:
        raise HTTPException(status_code=500, detail="模型调用失败")
    return llm_client


async def get_db():
    # 链接数据库
    db = { "connected": True, "host": "localhost", "port": 5432 }
    try:
       yield db
    finally:
       db["connected"] = False

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

@app.post("/v1/chat", response_model= ChatResponse)
async def chat(request: ChatRequest, 
               auth:dict= Depends(verify_token),
               client: httpx.AsyncClient = Depends(get_llm_client)):
    '''Agent 聊天接口 — 带完整的认证、异常处理、日志'''

    resp = await client.post("/chat/completions", json={
        "model": "deepseek-v4-pro",
        "messages": [m.model_dump() for m in request.messages],
        "stream": False
    })
    if resp.status_code != 200:
        raise AgetError(f"模型调用失败: {resp.text}", status_code=502)
    data = resp.json()
    return ChatResponse(
        reply=data["choices"][0]["message"]["content"],
        model=data["model"],
        usage=data["usage"]
    )

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}


@app.get("/dblist")
async def db_list(db: dict=Depends(get_db)):
    if not db["connected"]:
        raise HTTPException(status_code=500, detail="数据库未连接")
    return {"databases": ["db1", "db2", "db3"], "db_status": db["connected"]}