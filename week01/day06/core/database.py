from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from models.message import Base

@asynccontextmanager
async def init_db(app: FastAPI):
    # 启动时执行：创建数据库表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # 关闭时执行（可选）：关闭数据库连接池
    await engine.dispose()


# 数据库引擎
engine = create_async_engine("sqlite+aiosqlite:///./agent.db", echo=False)

# 创建异步会话
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
