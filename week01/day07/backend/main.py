from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL, CORS_ORIGINS

# ── 数据库 ────────────────────────────────────────────
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# 启用外键约束（SQLite 默认不启用）
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── 生命周期 ──────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：创建表 + 种子数据
    from models import Base
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        from seed import seed_admin
        seed_admin(db)
    finally:
        db.close()

    # 注册 DB 工厂到依赖注入
    import dependencies
    dependencies.init_db(SessionLocal)
    yield


# ── 应用 ──────────────────────────────────────────────
app = FastAPI(title="养老管理系统 API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 全局异常处理 ──────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": f"服务器内部错误: {str(exc)}", "data": None},
    )


# ── 路由注册 ──────────────────────────────────────────
from routers.auth import router as auth_router
from routers.worker import router as worker_router
from routers.patient import router as patient_router
from routers.schedule import router as schedule_router
from routers.session import router as session_router
from routers.checkin import router as checkin_router
from routers.record import router as record_router
from routers.absenteeism import router as absenteeism_router
from routers.reminder import router as reminder_router

app.include_router(auth_router)
app.include_router(worker_router)
app.include_router(patient_router)
app.include_router(schedule_router)
app.include_router(session_router)
app.include_router(checkin_router)
app.include_router(record_router)
app.include_router(absenteeism_router)
app.include_router(reminder_router)


# ── 健康检查 ──────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"code": 200, "message": "ok"}
