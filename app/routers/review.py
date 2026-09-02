"""
Reviewer dashboard endpoints — scored applicant list, detail, decisions, summary.

These endpoints power the reviewer interface.  They join applicant data with
assessment data and reviewer decisions so the frontend can render a complete
picture without multiple round-trips.
"""

import uuid
from collections import defaultdict
from enum import Enum
from statistics import median

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.applicant import Applicant
from app.models.assessment import Assessment
from app.models.reviewer_decision import ReviewerDecision
from app.repositories.applicant_repo import ApplicantRepository
from app.repositories.assessment_repo import AssessmentRepository
from app.schemas.assessment import AssessmentRead, AssessmentWithExplanations
from app.schemas.review import (
    ApplicantDetail,
    DecisionCreate,
    DecisionRead,
    ScoredApplicant,
    SummaryStats,
    BandCount,
    ConfidenceCount,
    CompletenessCount,
    DecisionCount,
)
from app.schemas.applicant import ApplicantRead
from app.utils.enums import DecisionOutcome, RiskLevel

router = APIRouter(prefix="/review", tags=["review"])


# ── Helpers ────────────────────────────────────────────────────────────────


def _latest_assessment_for(
    db: Session, applicant_id: uuid.UUID
) -> Assessment | None:
    """Return the most recent assessment for an applicant, or None."""
    return (
        db.query(Assessment)
        .filter(Assessment.applicant_id == applicant_id)
        .order_by(Assessment.created_at.desc())
        .first()
    )


def _assessment_to_read(a: Assessment) -> AssessmentRead:
    """Convert an ORM Assessment to the AssessmentRead schema."""
    return AssessmentRead(
        id=a.id,
        applicant_id=a.applicant_id,
        score=a.score,
        band=a.band,
        model_version=a.model_version,
        is_rule_based=a.is_rule_based,
        confidence_level=a.confidence_level,
        signal_categories_count=a.signal_categories_count,
        non_null_feature_count=a.non_null_feature_count,
        anomaly_risk_score=a.anomaly_risk_score,
        anomaly_risk_level=a.anomaly_risk_level,
        anomaly_audit_required=a.anomaly_audit_required,
        anomaly_flags_count=a.anomaly_flags_count,
        top_flags=a.top_flags,
        created_at=a.created_at,
    )


def _assessment_to_full(a: Assessment) -> AssessmentWithExplanations:
    """Convert an ORM Assessment to the full explanation schema."""
    return AssessmentWithExplanations(
        id=a.id,
        applicant_id=a.applicant_id,
        score=a.score,
        band=a.band,
        model_version=a.model_version,
        is_rule_based=a.is_rule_based,
        confidence_level=a.confidence_level,
        signal_categories_count=a.signal_categories_count,
        non_null_feature_count=a.non_null_feature_count,
        anomaly_risk_score=a.anomaly_risk_score,
        anomaly_risk_level=a.anomaly_risk_level,
        anomaly_audit_required=a.anomaly_audit_required,
        anomaly_flags_count=a.anomaly_flags_count,
        top_flags=a.top_flags,
        created_at=a.created_at,
        feature_contributions=a.feature_contributions,
        anomaly_report=a.anomaly_report,
    )


def _latest_decision_for(
    db: Session, applicant_id: uuid.UUID
) -> ReviewerDecision | None:
    """Return the most recent decision for any of an applicant's assessments."""
    return (
        db.query(ReviewerDecision)
        .join(Assessment)
        .filter(Assessment.applicant_id == applicant_id)
        .order_by(ReviewerDecision.created_at.desc())
        .first()
    )


# ── Scored applicant list ──────────────────────────────────────────────────


class SortField(str, Enum):
    score = "score"
    band = "band"
    confidence = "confidence"
    created_at = "created_at"
    city = "city"
    applicant_type = "applicant_type"


@router.get("/applicants", response_model=list[ScoredApplicant])
def list_scored_applicants(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    band: str | None = Query(None, description="Filter by score band: low, moderate, strong"),
    confidence: str | None = Query(None, description="Filter by confidence: high, medium, low"),
    review_status: str | None = Query(
        None,
        description="Filter by review status: decided, undecided",
    ),
    risk_level: str | None = Query(
        None,
        description=(
            "Filter by anomaly risk level: clean, low_risk, moderate_flag, "
            "high_suspicion, critical_mismatch"
        ),
    ),
    audit_required: bool | None = Query(
        None,
        description="Only applicants whose anomaly verdict mandates a field audit.",
    ),
    min_anomaly_score: float | None = Query(
        None, ge=0, le=100,
        description="Minimum anomaly risk score (0-100).",
    ),
    sort_by: SortField = Query(SortField.created_at),
    sort_order: str = Query("desc", description="asc or desc"),
    search: str | None = Query(None, description="Search by city, district, or CNIC"),
    db: Session = Depends(get_db),
):
    """
    List scored applicants for the reviewer dashboard.

    Returns applicant info joined with their latest assessment, sortable
    and filterable by band, confidence, review status, fraud-shield risk
    level, audit requirement, and minimum anomaly score.
    """
    # ── Fetch paginated applicants ────────────────────────────────────
    query = db.query(Applicant).order_by(Applicant.created_at.desc())

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (Applicant.city.ilike(pattern))
            | (Applicant.district.ilike(pattern))
            | (Applicant.identity_reference.ilike(pattern))
        )

    applicants = query.offset(offset).limit(limit).all()
    if not applicants:
        return []

    applicant_ids = [a.id for a in applicants]

    # ── Batch-load latest assessments (1 query, not N) ──────────────
    latest_assessment_subq = (
        db.query(
            Assessment.applicant_id,
            func.max(Assessment.created_at).label("max_created"),
        )
        .filter(Assessment.applicant_id.in_(applicant_ids))
        .group_by(Assessment.applicant_id)
        .subquery()
    )
    assessments = (
        db.query(Assessment)
        .join(
            latest_assessment_subq,
            (Assessment.applicant_id == latest_assessment_subq.c.applicant_id)
            & (Assessment.created_at == latest_assessment_subq.c.max_created),
        )
        .all()
    )
    assessment_map: dict[uuid.UUID, Assessment] = {
        a.applicant_id: a for a in assessments
    }

    # ── Batch-load latest decisions (1 query, not N) ────────────────
    decision_subq = (
        db.query(
            Assessment.applicant_id,
            func.max(ReviewerDecision.created_at).label("max_decision"),
        )
        .join(ReviewerDecision)
        .filter(Assessment.applicant_id.in_(applicant_ids))
        .group_by(Assessment.applicant_id)
        .subquery()
    )
    decisions = (
        db.query(ReviewerDecision)
        .join(
            Assessment,
            ReviewerDecision.assessment_id == Assessment.id,
        )
        .join(
            decision_subq,
            (Assessment.applicant_id == decision_subq.c.applicant_id)
            & (ReviewerDecision.created_at == decision_subq.c.max_decision),
        )
        .all()
    )
    decision_map: dict[uuid.UUID, ReviewerDecision] = {}
    for d in decisions:
        # Find which applicant this decision belongs to.
        for a in assessments:
            if a.id == d.assessment_id:
                decision_map[a.applicant_id] = d
                break

    # ── Build results with in-memory filtering ──────────────────────
    results: list[ScoredApplicant] = []
    for applicant in applicants:
        assessment = assessment_map.get(applicant.id)
        decision = decision_map.get(applicant.id)

        # Apply band filter.
        if band and (assessment is None or assessment.band.value != band):
            continue
        # Apply confidence filter.
        if confidence and (
            assessment is None or assessment.confidence_level.value != confidence
        ):
            continue
        # Apply review status filter.
        if review_status == "decided" and decision is None:
            continue
        if review_status == "undecided" and decision is not None:
            continue
        # Apply anomaly risk-level filter (unscored applicants never match).
        if risk_level and (
            assessment is None or assessment.anomaly_risk_level.value != risk_level
        ):
            continue
        # Apply audit-required filter (unscored applicants never match).
        if audit_required is not None and (
            assessment is None
            or bool(assessment.anomaly_audit_required) != audit_required
        ):
            continue
        # Apply minimum anomaly score filter (unscored applicants never match).
        if min_anomaly_score is not None and (
            assessment is None
            or assessment.anomaly_risk_score < min_anomaly_score
        ):
            continue

        results.append(
            ScoredApplicant(
                id=applicant.id,
                identity_reference=applicant.identity_reference,
                applicant_type=applicant.applicant_type.value if applicant.applicant_type else None,
                city=applicant.city,
                district=applicant.district,
                created_at=applicant.created_at,
                latest_assessment=_assessment_to_read(assessment) if assessment else None,
                has_decision=decision is not None,
                latest_decision_outcome=decision.outcome.value if decision else None,
                anomaly_risk_score=(
                    assessment.anomaly_risk_score if assessment else 0.0
                ),
                anomaly_risk_level=(
                    assessment.anomaly_risk_level if assessment else RiskLevel.CLEAN
                ),
                anomaly_audit_required=(
                    assessment.anomaly_audit_required if assessment else False
                ),
                anomaly_flags_count=(
                    assessment.anomaly_flags_count if assessment else 0
                ),
                top_flags=assessment.top_flags if assessment else [],
            )
        )

    # Sort in Python (applicants may or may not have assessments).
    reverse = sort_order == "desc"
    if sort_by == SortField.score:
        results.sort(
            key=lambda r: r.latest_assessment.score if r.latest_assessment else -1,
            reverse=reverse,
        )
    elif sort_by == SortField.band:
        band_order = {"strong": 3, "moderate": 2, "low": 1}
        results.sort(
            key=lambda r: (
                band_order.get(r.latest_assessment.band.value, 0)
                if r.latest_assessment
                else 0
            ),
            reverse=reverse,
        )
    elif sort_by == SortField.confidence:
        conf_order = {"high": 3, "medium": 2, "low": 1}
        results.sort(
            key=lambda r: (
                conf_order.get(r.latest_assessment.confidence_level.value, 0)
                if r.latest_assessment
                else 0
            ),
            reverse=reverse,
        )
    elif sort_by == SortField.city:
        results.sort(
            key=lambda r: r.city or "", reverse=reverse,
        )
    elif sort_by == SortField.applicant_type:
        results.sort(
            key=lambda r: r.applicant_type or "", reverse=reverse,
        )

    return results


# ── Applicant detail ───────────────────────────────────────────────────────


@router.get("/applicants/{applicant_id}", response_model=ApplicantDetail)
def get_applicant_detail(
    applicant_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """
    Full applicant detail: profile, latest assessment with explanations,
    all underlying records, and decision history.
    """
    applicant_repo = ApplicantRepository(db)
    applicant = applicant_repo.get_by_id(applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Applicant not found")

    # Latest assessment.
    assessment = _latest_assessment_for(db, applicant_id)

    # All decisions for this applicant's assessments.
    decisions = (
        db.query(ReviewerDecision)
        .join(Assessment)
        .filter(Assessment.applicant_id == applicant_id)
        .order_by(ReviewerDecision.created_at.desc())
        .all()
    )

    return ApplicantDetail(
        applicant=ApplicantRead.model_validate(applicant),
        latest_assessment=(
            _assessment_to_full(assessment) if assessment else None
        ),
        utility_records=applicant.utility_records or [],
        academic_records=applicant.academic_records or [],
        income_signals=applicant.income_signals or [],
        decisions=[DecisionRead.model_validate(d) for d in decisions],
    )


# ── Decision submission ────────────────────────────────────────────────────


@router.post(
    "/assessments/{assessment_id}/decisions",
    response_model=DecisionRead,
    status_code=201,
)
def submit_decision(
    assessment_id: uuid.UUID,
    payload: DecisionCreate,
    db: Session = Depends(get_db),
):
    """
    Record a reviewer's approval or denial with a written rationale.
    The decision is attached to a specific assessment so the audit trail
    is clear even if the applicant is re-scored later.
    """
    assessment_repo = AssessmentRepository(db)
    assessment = assessment_repo.get_by_id(assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    decision = ReviewerDecision(
        assessment_id=assessment_id,
        reviewer=payload.reviewer,
        outcome=payload.outcome,
        rationale=payload.rationale,
    )
    return assessment_repo.add_decision(decision)


# ── Summary statistics ─────────────────────────────────────────────────────


@router.get("/summary", response_model=SummaryStats)
def get_summary_stats(
    db: Session = Depends(get_db),
):
    """
    Aggregate statistics for the reviewer dashboard:
    score distribution, band breakdown, data completeness, decision counts.
    """
    total_applicants = db.query(func.count(Applicant.id)).scalar() or 0

    # All latest assessments (one per applicant).
    # Use a subquery to get the most recent assessment per applicant.
    latest_ids = (
        db.query(
            Assessment.applicant_id,
            func.max(Assessment.created_at).label("max_created"),
        )
        .group_by(Assessment.applicant_id)
        .subquery()
    )
    latest_assessments = (
        db.query(Assessment)
        .join(
            latest_ids,
            (Assessment.applicant_id == latest_ids.c.applicant_id)
            & (Assessment.created_at == latest_ids.c.max_created),
        )
        .all()
    )

    scored_count = len(latest_assessments)
    scores = [a.score for a in latest_assessments]

    # Mean and median.
    mean_score = round(sum(scores) / len(scores), 2) if scores else None
    median_score = round(median(scores), 2) if scores else None

    # Score distribution (10-point bins).
    score_dist = []
    for lo in range(0, 100, 10):
        hi = lo + 10
        count = sum(1 for s in scores if lo <= s < hi) if lo < 90 else sum(
            1 for s in scores if lo <= s <= hi
        )
        score_dist.append({"bin": f"{lo}-{hi}", "count": count})

    # Band breakdown.
    band_counts: dict[str, int] = {}
    for a in latest_assessments:
        b = a.band.value if hasattr(a.band, "value") else a.band
        band_counts[b] = band_counts.get(b, 0) + 1
    band_breakdown = [
        BandCount(band=b, count=c) for b, c in sorted(band_counts.items())
    ]

    # Confidence breakdown.
    conf_counts: dict[str, int] = {}
    for a in latest_assessments:
        c = (
            a.confidence_level.value
            if hasattr(a.confidence_level, "value")
            else a.confidence_level
        )
        conf_counts[c] = conf_counts.get(c, 0) + 1
    confidence_breakdown = [
        ConfidenceCount(confidence=c, count=n)
        for c, n in sorted(conf_counts.items())
    ]

    # Completeness breakdown (signal_categories_count).
    comp_counts: dict[int, int] = {}
    for a in latest_assessments:
        sc = a.signal_categories_count
        comp_counts[sc] = comp_counts.get(sc, 0) + 1
    completeness_breakdown = [
        CompletenessCount(categories=cat, count=cnt)
        for cat, cnt in sorted(comp_counts.items())
    ]

    # Decision counts.
    decision_outcomes = (
        db.query(ReviewerDecision.outcome, func.count(ReviewerDecision.id))
        .group_by(ReviewerDecision.outcome)
        .all()
    )
    decision_counts = [
        DecisionCount(
            outcome=o.value if hasattr(o, "value") else o, count=c
        )
        for o, c in decision_outcomes
    ]

    # Count applicants with at least one decision.
    decided_applicant_ids = (
        db.query(Assessment.applicant_id)
        .join(ReviewerDecision)
        .distinct()
        .all()
    )
    decided_count = len(decided_applicant_ids)
    undecided_count = scored_count - decided_count

    return SummaryStats(
        total_applicants=total_applicants,
        scored_applicants=scored_count,
        mean_score=mean_score,
        median_score=median_score,
        score_distribution=score_dist,
        band_breakdown=band_breakdown,
        confidence_breakdown=confidence_breakdown,
        completeness_breakdown=completeness_breakdown,
        decision_counts=decision_counts,
        undecided_count=undecided_count,
    )
