from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ScheduleLog(Base):
    __tablename__ = "schedule_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedule.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # created/cancelled/substituted
    operator_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    original_worker_id: Mapped[int | None] = mapped_column(ForeignKey("worker.id"))
    new_worker_id: Mapped[int | None] = mapped_column(ForeignKey("worker.id"))
    remark: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    schedule: Mapped["Schedule"] = relationship(back_populates="logs")
