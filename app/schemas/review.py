"""
Pydantic schemas for the reviewer dashboard endpoints.

These extend the base applicant/assessment schemas with the joined data
a reviewer actually needs: applicant info alongside their latest score,
decision history, and summary statistics.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.applicant import ApplicantRead
from app.schemas.assessment import AssessmentRead, AssessmentWithExplanations
from app.schemas.records import (
    AcademicRecordRead,
    IncomeSignalRead,
    UtilityRecordRead,
)
from app.utils.enums import ConfidenceLevel, DecisionOutcome, ScoreBand


# ── Scored applicant list ──────────────────────────────────────────────────


class ScoredApplicant(BaseModel):
    """An applicant row in the reviewer's list — applicant + latest assessment."""

    model_config = ConfigDict(from_attributes=True)

    # Applicant fields.
    id: uuid.UUID
    identity_reference: str | None = None
    applicant_type: str | None = None
    city: str | None = None
    district: str | None = None
    created_at: datetime

    # Latest assessment (None if never scored).
    latest_assessment: AssessmentRead | None = None

    # Review status.
    has_decision: bool = False
    latest_decision_outcome: str | None = None


# ── Applicant detail (full) ────────────────────────────────────────────────


class ApplicantDetail(BaseModel):
    """Full applicant detail with records, assessment, and decisions."""

    model_config = ConfigDict(from_attributes=True)

    applicant: ApplicantRead
    latest_assessment: AssessmentWithExplanations | None = None
    utility_records: list[UtilityRecordRead] = []
    academic_records: list[AcademicRecordRead] = []
    income_signals: list[IncomeSignalRead] = []
    decisions: list["DecisionRead"] = []


# ── Reviewer decisions ─────────────────────────────────────────────────────


class DecisionCreate(BaseModel):
    """Payload for submitting a reviewer decision."""

    reviewer: str | None = None
    outcome: DecisionOutcome
    rationale: str | None = None


class DecisionRead(BaseModel):
    """A recorded reviewer decision."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assessment_id: uuid.UUID
    reviewer: str | None = None
    outcome: DecisionOutcome
    rationale: str | None = None
    created_at: datetime


# ── Summary statistics ─────────────────────────────────────────────────────


class BandCount(BaseModel):
    band: str
    count: int


class ConfidenceCount(BaseModel):
    confidence: str
    count: int


class CompletenessCount(BaseModel):
    categories: int
    count: int


class DecisionCount(BaseModel):
    outcome: str
    count: int


class SummaryStats(BaseModel):
    """Aggregate statistics for the reviewer dashboard summary view."""

    total_applicants: int = 0
    scored_applicants: int = 0
    mean_score: float | None = None
    median_score: float | None = None
    score_distribution: list[dict] = []  # [{bin: "0-10", count: 5}, ...]
    band_breakdown: list[BandCount] = []
    confidence_breakdown: list[ConfidenceCount] = []
    completeness_breakdown: list[CompletenessCount] = []
    decision_counts: list[DecisionCount] = []
    undecided_count: int = 0
