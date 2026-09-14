"""
Reviewer decision — a human reviewer's verdict on an assessment.

One assessment can have multiple decisions (e.g. initial review, appeal).
The ``rationale`` field is free text so reviewers can explain their reasoning
in their own words — this is essential for audit trails.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.enums import DecisionOutcome
from app.utils.types import StrEnumType


class ReviewerDecision(Base):
    __tablename__ = "reviewer_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Free-text reviewer identifier (name, employee ID, or system user ID).
    reviewer: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    outcome: Mapped[DecisionOutcome] = mapped_column(
        StrEnumType(DecisionOutcome), nullable=False,
    )

    # Free-text explanation of why this decision was made.
    rationale: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Relationships ──────────────────────────────────────────────────────────
    assessment: Mapped["Assessment"] = relationship( # noqa: F821
        back_populates="reviewer_decisions"
    )

    def __repr__(self) -> str:
        return (
            f"<ReviewerDecision outcome={self.outcome} "
            f"reviewer={self.reviewer}>"
        )
