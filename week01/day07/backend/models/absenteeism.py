from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Absenteeism(Base):
    __tablename__ = "absenteeism"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedule.id"), nullable=False)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker.id"), nullable=False)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="absent", nullable=False)  # absent / corrected
    auto_marked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime)
    corrected_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    correction_reason: Mapped[str | None] = mapped_column(Text)

    # 预留绩效字段，Phase 1 不使用
    score: Mapped[int | None] = mapped_column(Integer)
    performance_level: Mapped[str | None] = mapped_column(String(20))

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    worker: Mapped["Worker"] = relationship(back_populates="absenteeisms")
    patient: Mapped["Patient"] = relationship()
    schedule: Mapped["Schedule"] = relationship(back_populates="absenteeisms")
