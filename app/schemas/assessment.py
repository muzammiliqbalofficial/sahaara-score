"""
Pydantic schemas for the Assessment entity.

The ``AssessmentWithExplanations`` schema is the primary response format
for the scoring API.  It includes structured feature contributions that
are safe to render directly in a reviewer dashboard.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.utils.enums import ConfidenceLevel, ScoreBand


class FeatureContribution(BaseModel):
    """One feature's impact on the score, in reviewer-readable language."""

    feature: str
    label: str | None = None
    contribution: float
    direction: str  # "positive", "negative", or "neutral"
    explanation: str  # Plain-language sentence for the reviewer
    raw_value: float | None = None
    no_data: bool = False  # True when the feature had no underlying data


class AssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    applicant_id: uuid.UUID
    score: float
    band: ScoreBand
    model_version: str
    is_rule_based: bool
    confidence_level: ConfidenceLevel
    # Data sufficiency — first-class fields, not side metadata.
    signal_categories_count: int = 0
    non_null_feature_count: int = 0
    created_at: datetime


class AssessmentWithExplanations(AssessmentRead):
    """Full assessment with reviewer-facing feature explanations."""

    feature_contributions: list[FeatureContribution] | None = None

    # Human-readable summary of data completeness.
    data_sufficiency_summary: str | None = None
    categories_present: list[str] | None = None
    months_of_data: int | None = None
