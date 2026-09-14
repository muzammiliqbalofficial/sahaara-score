"""
Applicant model — the central entity every other record hangs off.

Design decisions:
  - ``identity_reference`` is a free-text CNIC or B-Form number stored as a
    string (CNICs have dashes and leading zeros).  We do NOT enforce a unique
    constraint at DB level yet because the same person may apply under
    different reference types; uniqueness should be enforced at the service
    layer with proper deduplication logic.
  - ``city`` and ``district`` are both nullable because rural applicants may
    only know their tehsil or union council.
  - ``household_size`` and ``dependants`` are integers but nullable: a student
    living in a hostel may not know or may not wish to declare these.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.enums import ApplicantType
from app.utils.types import StrEnumType


class Applicant(Base):
    __tablename__ = "applicants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Identity ───────────────────────────────────────────────────────────────
    # Free-text to accommodate CNIC (13 digits), B-Form, or passport numbers.
    identity_reference: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    applicant_type: Mapped[ApplicantType | None] = mapped_column(
        StrEnumType(ApplicantType), nullable=True,
    )

    # Demographics ───────────────────────────────────────────────────────────
    household_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dependants: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Labels (populated by seed script for model training) ──────────────
    # These are synthetic ground-truth labels generated from a latent
    # approval model that is *independent* of the rule-based scorer.
    reviewer_approved: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True,
    )
    approval_score: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )

    # Timestamps ─────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships ──────────────────────────────────────────────────────────
    utility_records: Mapped[list["UtilityRecord"]] = relationship(  # noqa: F821
        back_populates="applicant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    academic_records: Mapped[list["AcademicRecord"]] = relationship(  # noqa: F821
        back_populates="applicant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    income_signals: Mapped[list["IncomeSignal"]] = relationship(  # noqa: F821
        back_populates="applicant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    assessments: Mapped[list["Assessment"]] = relationship(  # noqa: F821
        back_populates="applicant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Applicant {self.id} type={self.applicant_type} "
            f"city={self.city}>"
        )
