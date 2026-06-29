from sqlalchemy import Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin

class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    saved_as: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 状态: pending=待处理, processing=处理中, done=完成, error=失败
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_msg: Mapped[str] = mapped_column(String(500), nullable=True)
