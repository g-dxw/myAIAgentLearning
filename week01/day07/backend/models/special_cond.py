from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class SpecialCondition(Base):
    __tablename__ = "special_condition"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # 死亡/就医/外出/其他
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    patient: Mapped["Patient"] = relationship(back_populates="special_conditions")
