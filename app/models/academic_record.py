"""
Academic record — one row per qualification or exam result.

Design decisions on normalising across scales:
  Pakistani education uses at least three different grading systems:
    - Percentage (0-100): common for matric and intermediate boards (BISE).
    - GPA (0.0-4.0): used by most universities (HEC standard).
    - Division (1, 2, 3): older universities and some boards.

  We store the raw ``result_value`` and its ``result_scale`` so no information
  is lost at ingestion. The feature engineering layer normalises everything
  to a 0-1 range using scale-specific mappings:
    - percentage → value / 100
    - gpa → value / 4.0
    - division → {1: 0.85, 2: 0.65, 3: 0.45} (First≈A, Second≈B, Third≈C)

  This approach lets us add new scales (e.g. letter grades) later without
  migrating stored data.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.enums import QualificationLevel, ResultScale
from app.utils.types import StrEnumType


class AcademicRecord(Base):
    __tablename__ = "academic_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    applicant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applicants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    institution: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    qualification_level: Mapped[QualificationLevel | None] = mapped_column(
        StrEnumType(QualificationLevel), nullable=True,
    )

    # Raw result — interpretation depends on result_scale.
    result_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_scale: Mapped[ResultScale | None] = mapped_column(
        StrEnumType(ResultScale), nullable=True,
    )

    # Year of result (e.g. 2023). Integer, not Date, because applicants
    # typically only remember the year.
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Relationships ──────────────────────────────────────────────────────────
    applicant: Mapped["Applicant"] = relationship( # noqa: F821
        back_populates="academic_records"
    )

    def __repr__(self) -> str:
        return (
            f"<AcademicRecord {self.qualification_level} "
            f"{self.result_value}/{self.result_scale} year={self.year}>"
        )
