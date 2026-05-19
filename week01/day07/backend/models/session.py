from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class SessionStatus(StrEnum):
    ONGOING = "ongoing"
    COMPLETED = "completed"


class Session(Base, TimestampMixin):
    __tablename__ = "session"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"), nullable=False)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker.id"), nullable=False)
    status: Mapped[SessionStatus] = mapped_column(
        String(15), default=SessionStatus.ONGOING, nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text)  # AI 自动生成的历史摘要

    patient: Mapped["Patient"] = relationship(back_populates="sessions")
    worker: Mapped["Worker"] = relationship(back_populates="sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", order_by="ChatMessage.created_at"
    )
