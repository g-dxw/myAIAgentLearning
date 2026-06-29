from fastapi import APIRouter, FastAPI
from api.documents import router as documents_router
from api.conversations import router as conversations_router
from api.qa import router as qa_router


def register_routes(app: FastAPI):
    """注册所有子路由到 /api/v1 前缀"""
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(conversations_router, prefix="/api/v1")
    app.include_router(qa_router, prefix="/api/v1")
