from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class PatientVersion(Base):
    __tablename__ = "patient_version"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"), nullable=False)
    updater_id: Mapped[int] = mapped_column(Integer, nullable=False)
    update_method: Mapped[str] = mapped_column(String(20), nullable=False)  # admin_manual / ai_supplement
    changed_fields: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    patient: Mapped["Patient"] = relationship(back_populates="versions")
