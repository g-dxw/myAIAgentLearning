# ==========================================
# 1. 全局中间件：计算接口耗时
# ==========================================

from contextvars import ContextVar
import time
import uuid

from fastapi import FastAPI, Request

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

async def timing_middleware(request, call_next):
   start_time = time.time()
   # 执行请求
   response = await call_next(request)
   # 计算耗时
   process_time = time.time() - start_time
   response.headers["X-Process-Time"] = str(process_time)
   print(f"✅ 请求：{request.url} | 耗时：{process_time:.3f}s")

   return response

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

def register_middlewares(app: FastAPI):
   app.middleware("http")(timing_middleware)
   app.middleware("http")(log_request_body)
