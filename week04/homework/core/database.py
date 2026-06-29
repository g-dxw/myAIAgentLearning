"""
documents               conversations         messages
├── id                  ├── id                ├── id
├── filename            ├── title             ├── conversation_id (FK)
├── saved_as            ├── created_at        ├── role
├── file_type                                 ├── content
├── size_bytes                                ├── sources (JSON)
├── chunk_count                               └── created_at
└── created_at
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from core.config import DATABASE_URL
from models.base import Base

# 创建异步引擎
engine = create_async_engine(DATABASE_URL, echo=False, future=True)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def init_db():
    """初始化数据库，创建所有表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def close_db():
    """关闭数据库引擎"""
    await engine.dispose()

async def get_db():
    """获取数据库会话（用于FastAPI依赖注入）"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
