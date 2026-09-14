"""
Pydantic schemas for multimodal document parsing results.

Design decisions:
  - Document parsing is inherently lossy: a blurry scan or handwritten
    affidavit may hide fields from the Qwen-VL extraction. Every field is
    therefore nullable and the router never raises on a missing value.
  - Parsed fields map one-to-one onto the existing record Create schemas
    (UtilityRecordCreate etc.) so a parse result can be persisted directly
    without a translation layer.
  - ``mode`` records whether the live Qwen-VL call or the offline mock
    produced the result. The reviewer interface surfaces this so a demo
    never silently pretends the API was live.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.assessment import AssessmentRead
from app.schemas.records import (
    AcademicRecordRead,
    IncomeSignalRead,
    UtilityRecordRead,
)
from app.utils.enums import (
    EvidenceType,
    IncomeSourceType,
    QualificationLevel,
    ResultScale,
    UtilityType,
)


class ParsedDocumentBase(BaseModel):
    """Fields common to every parse result."""

    mode: str = Field(
        description="Which engine produced the result: 'qwen_vl' or 'mock'.",
    )
    source_filename: str = Field(description="Original uploaded filename.")
    parsed_at: datetime = Field(
        description="Server timestamp of the parse — useful for audit trails.",
    )


class UtilityBillParseResult(ParsedDocumentBase):
    """Structured extraction from a utility bill (K-Electric, LESCO, SSGC, …)."""

    provider: str | None = Field(
        default=None, description="e.g. 'K-Electric', 'LESCO', 'SNGPL'.",
    )
    utility_type: UtilityType | None = None
    units_consumed: float | None = Field(
        default=None,
        description="Consumption units — kWh (electricity), cubic feet/MMBtu (gas), gallons (water).",
    )
    amount_billed: float | None = Field(
        default=None, description="Total billed amount in PKR.",
    )
    arrears: float | None = Field(
        default=None,
        description="Outstanding previous dues in PKR (0 if none).",
    )
    billing_month: date | None = Field(
        default=None, description="First day of the billing period.",
    )
    consumer_name: str | None = None


class AcademicRecordParseResult(ParsedDocumentBase):
    """Structured extraction from a marksheet or transcript."""

    institution: str | None = None
    qualification_level: QualificationLevel | None = None
    result_value: float | None = Field(
        default=None,
        description="Raw result — interpretation depends on result_scale.",
    )
    result_scale: ResultScale | None = None
    year: int | None = Field(
        default=None, description="Year the result was awarded.",
    )
    student_name: str | None = None


class IncomeSlipParseResult(ParsedDocumentBase):
    """Structured extraction from an income affidavit, salary slip, or similar."""

    monthly_income: float | None = Field(
        default=None, description="Declared monthly income in PKR.",
    )
    source_type: IncomeSourceType | None = None
    dependants: int | None = Field(
        default=None, description="Dependants named in the affidavit.",
    )
    employer_or_source: str | None = Field(
        default=None, description="Employer, client, or income source name.",
    )
    evidence_type: EvidenceType | None = Field(
        default=None,
        description="Documented by default — the applicant supplied paper proof.",
    )


class BundleParseResult(BaseModel):
    """Aggregated result of parsing multiple documents at once.

    When an ``applicant_id`` is supplied the parsed values are also written
    as real records (and optionally scored), so the bundle endpoint doubles
    as a one-shot intake: photograph three documents, get a scored applicant.
    """

    utility_bills: list[UtilityBillParseResult] = []
    academic_records: list[AcademicRecordParseResult] = []
    income_slips: list[IncomeSlipParseResult] = []

    applicant_id: uuid.UUID | None = None

    created_utility_records: list[UtilityRecordRead] = []
    created_academic_records: list[AcademicRecordRead] = []
    created_income_signals: list[IncomeSignalRead] = []

    assessment: AssessmentRead | None = None
    mode_summary: dict[str, int] = Field(
        default_factory=dict,
        description="Count of documents by mode, e.g. {'qwen_vl': 2, 'mock': 1}.",
    )


__all__ = [
    "ParsedDocumentBase",
    "UtilityBillParseResult",
    "AcademicRecordParseResult",
    "IncomeSlipParseResult",
    "BundleParseResult",
]
