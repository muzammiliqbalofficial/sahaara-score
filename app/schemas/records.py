"""
Pydantic schemas for utility, academic, and income records.

All ``Create`` schemas are fully optional — every field is nullable to
reflect the incomplete-data reality of the domain.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.utils.enums import (
    EvidenceType,
    IncomeSourceType,
    QualificationLevel,
    ResultScale,
    UtilityType,
)


# ── Utility Records ─────────────────────────────────────────────────────────


class UtilityRecordCreate(BaseModel):
    applicant_id: uuid.UUID | None = None
    utility_type: UtilityType | None = None
    billing_month: date | None = None
    amount_billed: float | None = Field(default=None, ge=0)
    amount_paid: float | None = Field(default=None, ge=0)
    days_late: int | None = Field(default=None, ge=0)


class UtilityRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    applicant_id: uuid.UUID
    utility_type: UtilityType | None = None
    billing_month: date | None = None
    amount_billed: float | None = None
    amount_paid: float | None = None
    days_late: int | None = None
    created_at: datetime


# ── Academic Records ────────────────────────────────────────────────────────


class AcademicRecordCreate(BaseModel):
    applicant_id: uuid.UUID | None = None
    institution: str | None = None
    qualification_level: QualificationLevel | None = None
    result_value: float | None = Field(default=None, ge=0)
    result_scale: ResultScale | None = None
    year: int | None = Field(default=None, ge=1970, le=2030)


class AcademicRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    applicant_id: uuid.UUID
    institution: str | None = None
    qualification_level: QualificationLevel | None = None
    result_value: float | None = None
    result_scale: ResultScale | None = None
    year: int | None = None
    created_at: datetime


# ── Income Signals ──────────────────────────────────────────────────────────


class IncomeSignalCreate(BaseModel):
    applicant_id: uuid.UUID | None = None
    source_type: IncomeSourceType | None = None
    declared_monthly_amount: float | None = Field(default=None, ge=0)
    evidence_type: EvidenceType | None = None
    confidence_flag: bool | None = None


class IncomeSignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    applicant_id: uuid.UUID
    source_type: IncomeSourceType | None = None
    declared_monthly_amount: float | None = None
    evidence_type: EvidenceType | None = None
    confidence_flag: bool | None = None
    created_at: datetime
