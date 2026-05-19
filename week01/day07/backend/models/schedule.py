from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ScheduleStatus(StrEnum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Schedule(Base):
    __tablename__ = "schedule"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker.id"), nullable=False)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[ScheduleStatus] = mapped_column(
        String(15), default=ScheduleStatus.ASSIGNED, nullable=False
    )

    worker: Mapped["Worker"] = relationship(back_populates="schedules")
    patient: Mapped["Patient"] = relationship(back_populates="schedules")
    logs: Mapped[list["ScheduleLog"]] = relationship(back_populates="schedule")
    reminders: Mapped[list["Reminder"]] = relationship(back_populates="schedule")
    checkins: Mapped[list["Checkin"]] = relationship(back_populates="schedule")
    absenteeisms: Mapped[list["Absenteeism"]] = relationship(back_populates="schedule")
