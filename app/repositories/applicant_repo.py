"""
Repository for Applicant and related records.

Keeps SQLAlchemy queries out of the service layer. Every method accepts and
returns ORM objects — Pydantic conversion happens in the service/router layer.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.applicant import Applicant
from app.models.academic_record import AcademicRecord
from app.models.income_signal import IncomeSignal
from app.models.utility_record import UtilityRecord


class ApplicantRepository:
    """CRUD + query helpers for applicants and their child records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Applicant CRUD ──────────────────────────────────────────────────────

    def create(self, applicant: Applicant) -> Applicant:
        self.db.add(applicant)
        self.db.commit()
        self.db.refresh(applicant)
        return applicant

    def get_by_id(self, applicant_id: uuid.UUID) -> Applicant | None:
        return self.db.get(Applicant, applicant_id)

    def list_all(self, offset: int = 0, limit: int = 50) -> list[Applicant]:
        return (
            self.db.query(Applicant)
            .order_by(Applicant.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    # ── Child record creation ───────────────────────────────────────────────

    def add_utility_record(self, record: UtilityRecord) -> UtilityRecord:
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def add_academic_record(self, record: AcademicRecord) -> AcademicRecord:
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def add_income_signal(self, signal: IncomeSignal) -> IncomeSignal:
        self.db.add(signal)
        self.db.commit()
        self.db.refresh(signal)
        return signal

    # ── Bulk operations (used by seed script) ───────────────────────────────

    def bulk_create(self, applicants: list[Applicant]) -> None:
        """Insert many applicants and their children in one transaction."""
        self.db.add_all(applicants)
        self.db.commit()
