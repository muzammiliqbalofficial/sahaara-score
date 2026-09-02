"""
Assessment — the output of a scoring run for one applicant.

Design decisions:
  - ``feature_contributions`` is stored as JSONB so we can query individual
    feature impacts without deserialising the whole row.
  - ``model_version`` is stamped at creation time so we can trace which model
    produced which score — critical for auditing when a reviewer challenges
    a decision.
  - ``confidence_level`` is persisted alongside the score so the reviewer UI
    never needs to recompute it.
  - The ``is_rule_based`` flag makes it explicit whether the ML model or the
    rule-based fallback produced this score.  No hidden fallbacks.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.enums import ConfidenceLevel, RiskLevel, ScoreBand
from app.utils.types import StrEnumType


class Assessment(Base):
    __tablename__ = "assessments"

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

    # Score output ───────────────────────────────────────────────────────────
    score: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[ScoreBand] = mapped_column(
        StrEnumType(ScoreBand), nullable=False,
    )

    # Explainability ─────────────────────────────────────────────────────────
    # JSONB structure:
    # [
    #   {"feature": "payment_reliability", "contribution": 12.5,
    #    "direction": "positive", "explanation": "..."},
    #   ...
    # ]
    feature_contributions: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )

    # Provenance ─────────────────────────────────────────────────────────────
    model_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="0.1.0"
    )
    is_rule_based: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        StrEnumType(ConfidenceLevel), nullable=False,
    )

    # Data sufficiency — first-class fields, not side metadata.
    # A score of 60 built on eight signals is not the same claim as a score
    # of 60 built on one signal.  These columns make that explicit at the
    # database level so reviewers and dashboards can filter / sort on them.
    signal_categories_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="How many distinct signal categories (utility, academic, income) backed this score.",
    )
    non_null_feature_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="How many of the 8 engineered features had non-null values.",
    )

    # Anomaly / fraud shield ──────────────────────────────────────────────
    # The fraud-shield verdict is persisted as flat columns (filterable in
    # SQL) plus a JSONB report carrying the full flags, evidence, and the
    # policy recommendation for reviewer detail views.
    anomaly_risk_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="0-100 fraud-shield risk score; 0 means no flags fired.",
    )
    anomaly_risk_level: Mapped[RiskLevel] = mapped_column(
        StrEnumType(RiskLevel), nullable=False, default=RiskLevel.CLEAN,
    )
    anomaly_audit_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="True when the anomaly engine mandates field verification.",
    )
    anomaly_flags_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    anomaly_report: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="Full fraud-shield report: flags, evidence, recommendation.",
    )

    # Timestamps ─────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Relationships ──────────────────────────────────────────────────────────
    applicant: Mapped["Applicant"] = relationship(  # noqa: F821
        back_populates="assessments"
    )
    reviewer_decisions: Mapped[list["ReviewerDecision"]] = relationship(  # noqa: F821
        back_populates="assessment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def top_flags(self) -> list[str]:
        """Codes of the most severe anomaly flags (worst first).

        Derived from the JSONB report so every schema serialising this
        object via ``from_attributes`` gets the queue-friendly summary
        without extra queries.
        """
        report = self.anomaly_report
        if not isinstance(report, dict):
            return []
        return report.get("top_flags", [])

    def __repr__(self) -> str:
        return (
            f"<Assessment score={self.score} band={self.band} "
            f"rule_based={self.is_rule_based}>"
        )
