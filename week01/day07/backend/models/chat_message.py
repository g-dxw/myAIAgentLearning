from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("session.id"), nullable=False)
    role: Mapped[MessageRole] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    session: Mapped["Session"] = relationship(back_populates="messages")
