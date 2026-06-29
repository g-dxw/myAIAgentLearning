from contextlib import asynccontextmanager
import os
import time
import uuid

from fastapi import FastAPI, Request
from core.database import init_db, close_db
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from api.router import register_routes

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="RAG文档问答系统",
    version="1.0.0",
    description="一个基于RAG的文档问答系统",
    lifespan=lifespan
)


#cors配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def trace_requests(request: Request, call_next):
    rid = request.headers.get("X-Request-Id", str(uuid.uuid4().hex[:8]))
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Request-Id"] = rid
    print(f"[{rid}] {request.method:6} {request.url} -> {response.status_code} ({process_time:.2f}ms)")
    return response

@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    print(f"[EEROR] {request.method} {request.url} : {exc}")
    return JSONResponse(content={"success": False, "error": "服务器内部错误"}, status_code=500)

register_routes(app)

app.mount("/static", StaticFiles(directory="web", html=True), name="static")


@app.get("/")
async def read_root(request: Request):
    index_path = os.path.join("web", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "RAG文档问答系统"}

@app.get("/health")
async def health(request: Request):
    return {"status": "ok", "version": "1.0.0"}


