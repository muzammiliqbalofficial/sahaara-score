"""
Utility bill record — monthly electricity, gas, or water bills.

Design decisions:
  - ``amount_billed`` and ``amount_paid`` are both nullable.  A household that
    received a bill but couldn't pay it yet still provides a signal (we see
    the billing amount and that payment is outstanding).
  - ``days_late`` is nullable independently of payment amounts.  A value of 0
    means on-time; NULL means unknown (e.g. the applicant only remembers the
    amount, not the timing).
  - ``billing_month`` is a Date truncated to the first of the month so we can
    sort and compute streaks without string parsing.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.enums import UtilityType
from app.utils.types import StrEnumType


class UtilityRecord(Base):
    __tablename__ = "utility_records"

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

    utility_type: Mapped[UtilityType | None] = mapped_column(
        StrEnumType(UtilityType), nullable=True,
    )

    # First day of the billing period, stored as Date for sorting.
    billing_month: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Monetary values in PKR.  Float is acceptable here — we're doing
    # statistical aggregation, not accounting.
    amount_billed: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_paid: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 0 = on time, positive = late, NULL = unknown timing.
    days_late: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Relationships ──────────────────────────────────────────────────────────
    applicant: Mapped["Applicant"] = relationship(  # noqa: F821
        back_populates="utility_records"
    )

    def __repr__(self) -> str:
        return (
            f"<UtilityRecord {self.utility_type} "
            f"month={self.billing_month} billed={self.amount_billed}>"
        )
