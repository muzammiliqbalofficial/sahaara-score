"""
Pydantic schemas for the Applicant entity.

Design decision: ``ApplicantCreate`` makes every field optional except
``applicant_type`` (which we need to route scoring logic). This reflects
the reality that a field worker may only have partial information at first
intake, and the rest gets filled in over time.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.records import (
    AcademicRecordRead,
    IncomeSignalRead,
    UtilityRecordRead,
)
from app.utils.enums import ApplicantType


class ApplicantCreate(BaseModel):
    """Payload to register a new applicant."""

    identity_reference: str | None = None
    applicant_type: ApplicantType | None = None
    household_size: int | None = Field(default=None, ge=1, le=30)
    city: str | None = None
    district: str | None = None
    dependants: int | None = Field(default=None, ge=0, le=20)


class ApplicantRead(BaseModel):
    """Single applicant without nested records."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    identity_reference: str | None = None
    applicant_type: ApplicantType | None = None
    household_size: int | None = None
    city: str | None = None
    district: str | None = None
    dependants: int | None = None
    created_at: datetime
    updated_at: datetime


class ApplicantWithRecords(ApplicantRead):
    """Applicant with all related records hydrated — used for scoring."""

    utility_records: list[UtilityRecordRead] = []
    academic_records: list[AcademicRecordRead] = []
    income_signals: list[IncomeSignalRead] = []
