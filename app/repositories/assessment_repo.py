"""
Repository for Assessment and ReviewerDecision records.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.assessment import Assessment
from app.models.reviewer_decision import ReviewerDecision


class AssessmentRepository:
    """CRUD + query helpers for assessments and reviewer decisions."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Assessments ─────────────────────────────────────────────────────────

    def create(self, assessment: Assessment) -> Assessment:
        self.db.add(assessment)
        self.db.commit()
        self.db.refresh(assessment)
        return assessment

    def get_by_id(self, assessment_id: uuid.UUID) -> Assessment | None:
        return self.db.get(Assessment, assessment_id)

    def list_by_applicant(
        self, applicant_id: uuid.UUID
    ) -> list[Assessment]:
        return (
            self.db.query(Assessment)
            .filter(Assessment.applicant_id == applicant_id)
            .order_by(Assessment.created_at.desc())
            .all()
        )

    def list_all(
        self, offset: int = 0, limit: int = 50
    ) -> list[Assessment]:
        return (
            self.db.query(Assessment)
            .order_by(Assessment.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    # ── Reviewer Decisions ──────────────────────────────────────────────────

    def add_decision(self, decision: ReviewerDecision) -> ReviewerDecision:
        self.db.add(decision)
        self.db.commit()
        self.db.refresh(decision)
        return decision
