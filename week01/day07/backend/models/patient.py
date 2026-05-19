from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class PatientStatus(StrEnum):
    ACTIVE = "active"
    PENDING = "pending"


class Patient(Base, TimestampMixin):
    __tablename__ = "patient"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[str] = mapped_column(String(4), nullable=False)  # 男/女
    insurance_type: Mapped[str] = mapped_column(String(20), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    address: Mapped[str] = mapped_column(String(200), nullable=False)
    emergency_contact: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    # 护工通过 AI 对话补充的字段
    guardian_info: Mapped[str | None] = mapped_column(Text)
    disease_info: Mapped[str | None] = mapped_column(Text)
    care_requirements: Mapped[str | None] = mapped_column(Text)
    personality: Mapped[str | None] = mapped_column(Text)

    status: Mapped[PatientStatus] = mapped_column(
        String(10), default=PatientStatus.PENDING, nullable=False
    )
    assigned_worker_id: Mapped[int | None] = mapped_column(ForeignKey("worker.id"))

    # 版本追踪
    last_updater_id: Mapped[int | None] = mapped_column(Integer)
    update_method: Mapped[str | None] = mapped_column(String(20))  # admin_manual / ai_supplement
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    assigned_worker: Mapped["Worker | None"] = relationship(
        back_populates="patients", foreign_keys=[assigned_worker_id]
    )
    special_conditions: Mapped[list["SpecialCondition"]] = relationship(back_populates="patient")
    care_records: Mapped[list["CareRecord"]] = relationship(back_populates="patient")
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="patient")
    checkins: Mapped[list["Checkin"]] = relationship(back_populates="patient")
    sessions: Mapped[list["Session"]] = relationship(back_populates="patient")
    versions: Mapped[list["PatientVersion"]] = relationship(back_populates="patient")
