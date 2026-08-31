"""
Shared test fixtures.

Uses lightweight mock objects instead of a real database so that feature
engineering and scoring tests run without Postgres.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date

import pytest


@dataclass
class MockApplicant:
    """Lightweight stand-in for the ORM Applicant model."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    identity_reference: str | None = "35202-1234567-1"
    applicant_type: str | None = "student"
    household_size: int | None = 5
    city: str | None = "Lahore"
    district: str | None = "Lahore"
    dependants: int | None = 2
    utility_records: list = field(default_factory=list)
    academic_records: list = field(default_factory=list)
    income_signals: list = field(default_factory=list)


@dataclass
class MockUtilityRecord:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    applicant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    utility_type: str | None = "electricity"
    billing_month: date | None = None
    amount_billed: float | None = None
    amount_paid: float | None = None
    days_late: int | None = None


@dataclass
class MockAcademicRecord:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    applicant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    institution: str | None = "LUMS"
    qualification_level: str | None = None
    result_value: float | None = None
    result_scale: str | None = None
    year: int | None = None


@dataclass
class MockIncomeSignal:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    applicant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    source_type: str | None = "freelance"
    declared_monthly_amount: float | None = None
    evidence_type: str | None = None
    confidence_flag: bool | None = None


@pytest.fixture
def full_applicant():
    """Applicant with utility, academic, and income data (full profile)."""
    applicant = MockApplicant(dependants=2)

    # 8 months of electricity bills, mostly on time.
    for i in range(8):
        month = date(2024, 1 + i, 1)
        applicant.utility_records.append(MockUtilityRecord(
            applicant_id=applicant.id,
            billing_month=month,
            amount_billed=5000 + i * 100,
            amount_paid=5000 + i * 100,
            days_late=0 if i < 6 else 5,
        ))

    # Academic record — matric at 75%.
    applicant.academic_records.append(MockAcademicRecord(
        applicant_id=applicant.id,
        qualification_level="matric",
        result_value=75.0,
        result_scale="percentage",
        year=2022,
    ))

    # Income signal — freelance, documented.
    applicant.income_signals.append(MockIncomeSignal(
        applicant_id=applicant.id,
        source_type="freelance",
        declared_monthly_amount=40000,
        evidence_type="documented",
        confidence_flag=False,
    ))

    return applicant


@pytest.fixture
def thin_applicant():
    """Applicant with only utility data (thin file)."""
    applicant = MockApplicant(dependants=None)

    # 3 months of gas bills.
    for i in range(3):
        applicant.utility_records.append(MockUtilityRecord(
            applicant_id=applicant.id,
            billing_month=date(2024, 10 + i, 1),
            amount_billed=2000,
            amount_paid=2000,
            days_late=0,
        ))

    return applicant


@pytest.fixture
def empty_applicant():
    """Applicant with no records at all."""
    return MockApplicant(dependants=None)
