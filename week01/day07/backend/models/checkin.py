from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class CheckinStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    ABSENT = "absent"


class Checkin(Base, TimestampMixin):
    __tablename__ = "checkin"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker.id"), nullable=False)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"), nullable=False)
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("schedule.id"))  # 可空，补卡不关联排班
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    content: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[CheckinStatus] = mapped_column(
        String(15), default=CheckinStatus.STARTED, nullable=False
    )
    is_makeup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    worker: Mapped["Worker"] = relationship(back_populates="checkins")
    patient: Mapped["Patient"] = relationship(back_populates="checkins")
    schedule: Mapped["Schedule"] = relationship(back_populates="checkins")
