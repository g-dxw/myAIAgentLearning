from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class WorkerStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DELETED = "deleted"


class Worker(Base, TimestampMixin):
    __tablename__ = "worker"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    id_card: Mapped[str] = mapped_column(String(18), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[WorkerStatus] = mapped_column(
        String(10), default=WorkerStatus.ACTIVE, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="worker")
    care_records: Mapped[list["CareRecord"]] = relationship(back_populates="worker")
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="worker")
    checkins: Mapped[list["Checkin"]] = relationship(back_populates="worker")
    sessions: Mapped[list["Session"]] = relationship(back_populates="worker")
    absenteeisms: Mapped[list["Absenteeism"]] = relationship(back_populates="worker")
    reminders: Mapped[list["Reminder"]] = relationship(back_populates="worker")
    patients: Mapped[list["Patient"]] = relationship(
        back_populates="assigned_worker", foreign_keys="Patient.assigned_worker_id"
    )
