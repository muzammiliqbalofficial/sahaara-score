"""
Income signal — one row per income source an applicant declares.

Design decisions:
  - Most Pakistani informal-sector workers cannot produce salary slips.
    We capture ``declared_monthly_amount`` alongside an ``evidence_type``
    (self_declared / documented / verified) so the scoring engine can
    weight the signal by credibility.
  - ``confidence_flag`` is a boolean that data collectors can set when
    they have independently corroborated the amount (e.g. by speaking
    to the applicant's employer or checking mobile money records).
  - Multiple rows per applicant are expected — a farmer may also receive
    remittances from a sibling working abroad.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.enums import EvidenceType, IncomeSourceType
from app.utils.types import StrEnumType


class IncomeSignal(Base):
    __tablename__ = "income_signals"

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

    source_type: Mapped[IncomeSourceType | None] = mapped_column(
        StrEnumType(IncomeSourceType), nullable=True,
    )

    # PKR per month, as declared by the applicant or data collector.
    declared_monthly_amount: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    evidence_type: Mapped[EvidenceType | None] = mapped_column(
        StrEnumType(EvidenceType), nullable=True,
    )

    # True if a data collector independently verified this signal.
    confidence_flag: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Relationships ──────────────────────────────────────────────────────────
    applicant: Mapped["Applicant"] = relationship( # noqa: F821
        back_populates="income_signals"
    )

    def __repr__(self) -> str:
        return (
            f"<IncomeSignal {self.source_type} "
            f"PKR {self.declared_monthly_amount} "
            f"evidence={self.evidence_type}>"
        )
