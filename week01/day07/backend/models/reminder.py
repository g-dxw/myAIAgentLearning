from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Reminder(Base):
    __tablename__ = "reminder"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker.id"), nullable=False)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedule.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="未提交提醒")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    worker: Mapped["Worker"] = relationship(back_populates="reminders")
    schedule: Mapped["Schedule"] = relationship(back_populates="reminders")
