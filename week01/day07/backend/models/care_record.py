from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class CareRecord(Base, TimestampMixin):
    __tablename__ = "care_record"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"), nullable=False)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker.id"), nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)

    patient: Mapped["Patient"] = relationship(back_populates="care_records")
    worker: Mapped["Worker"] = relationship(back_populates="care_records")
