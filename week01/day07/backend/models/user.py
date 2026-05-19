from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class UserRole(StrEnum):
    ADMIN = "admin"
    WORKER = "worker"


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        String(10), default=UserRole.WORKER, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    worker: Mapped["Worker"] = relationship(back_populates="user", uselist=False)
