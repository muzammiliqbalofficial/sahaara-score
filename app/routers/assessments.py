"""
Assessment endpoints — trigger scoring, retrieve results.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.assessment import Assessment
from app.repositories.applicant_repo import ApplicantRepository
from app.repositories.assessment_repo import AssessmentRepository
from app.schemas.assessment import AssessmentRead, AssessmentWithExplanations
from app.services.scoring_service import score_applicant

router = APIRouter(prefix="/assessments", tags=["assessments"])


@router.post(
    "/{applicant_id}/score",
    response_model=AssessmentWithExplanations,
    status_code=201,
)
def run_assessment(
    applicant_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """
    Run the Sahaara Score assessment for an applicant.

    This is the primary scoring endpoint.  It:
      1. Loads the applicant with all related records.
      2. Computes features from raw data.
      3. Routes to model-based or rule-based scoring.
      4. Generates feature-level explanations.
      5. Persists the assessment and returns it.
    """
    applicant_repo = ApplicantRepository(db)
    applicant = applicant_repo.get_by_id(applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Applicant not found")

    # Compute score.
    result = score_applicant(applicant)

    # Persist.
    assessment = Assessment(
        applicant_id=applicant_id,
        score=result["score"],
        band=result["band"],
        feature_contributions=result["feature_contributions"],
        model_version=result["model_version"],
        is_rule_based=result["is_rule_based"],
        confidence_level=result["confidence_level"],
        signal_categories_count=result["signal_categories_count"],
        non_null_feature_count=result["non_null_feature_count"],
    )

    assessment_repo = AssessmentRepository(db)
    assessment = assessment_repo.create(assessment)

    # Build response with extra metadata.
    return AssessmentWithExplanations(
        id=assessment.id,
        applicant_id=assessment.applicant_id,
        score=assessment.score,
        band=assessment.band,
        model_version=assessment.model_version,
        is_rule_based=assessment.is_rule_based,
        confidence_level=assessment.confidence_level,
        signal_categories_count=assessment.signal_categories_count,
        non_null_feature_count=assessment.non_null_feature_count,
        created_at=assessment.created_at,
        feature_contributions=result["feature_contributions"],
        data_sufficiency_summary=result["data_sufficiency_summary"],
        categories_present=result["categories_present"],
        months_of_data=result["months_of_data"],
    )


@router.get("/", response_model=list[AssessmentRead])
def list_assessments(
    offset: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List all assessments (paginated)."""
    repo = AssessmentRepository(db)
    return repo.list_all(offset=offset, limit=limit)


@router.get(
    "/applicant/{applicant_id}",
    response_model=list[AssessmentRead],
)
def list_assessments_by_applicant(
    applicant_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List all assessments for a specific applicant."""
    repo = AssessmentRepository(db)
    return repo.list_by_applicant(applicant_id)


@router.get("/{assessment_id}", response_model=AssessmentWithExplanations)
def get_assessment(
    assessment_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Get a single assessment with its feature contributions."""
    repo = AssessmentRepository(db)
    assessment = repo.get_by_id(assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    return AssessmentWithExplanations(
        id=assessment.id,
        applicant_id=assessment.applicant_id,
        score=assessment.score,
        band=assessment.band,
        model_version=assessment.model_version,
        is_rule_based=assessment.is_rule_based,
        confidence_level=assessment.confidence_level,
        signal_categories_count=assessment.signal_categories_count,
        non_null_feature_count=assessment.non_null_feature_count,
        created_at=assessment.created_at,
        feature_contributions=assessment.feature_contributions,
    )
