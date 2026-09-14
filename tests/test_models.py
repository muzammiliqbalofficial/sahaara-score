"""
Tests for ORM models and Pydantic schemas.

These tests verify schema validation and model instantiation
without requiring a database connection.
"""

import uuid
from datetime import date, datetime

import pytest

from app.schemas.applicant import ApplicantCreate, ApplicantRead
from app.schemas.records import (
    AcademicRecordCreate,
    IncomeSignalCreate,
    UtilityRecordCreate,
)
from app.schemas.assessment import (
    AssessmentRead,
    AssessmentWithExplanations,
    FeatureContribution,
)
from app.utils.enums import (
    ApplicantType,
    ConfidenceLevel,
    ScoreBand,
    UtilityType,
)


# ── Applicant schemas ───────────────────────────────────────────────────────


class TestApplicantCreate:
    def test_minimal(self):
        """All fields optional — even empty dict should validate."""
        schema = ApplicantCreate()
        assert schema.identity_reference is None
        assert schema.applicant_type is None

    def test_full(self):
        schema = ApplicantCreate(
            identity_reference="35202-1234567-1",
            applicant_type=ApplicantType.STUDENT,
            household_size=5,
            city="Lahore",
            district="Lahore",
            dependants=2,
        )
        assert schema.city == "Lahore"
        assert schema.household_size == 5

    def test_invalid_household_size(self):
        with pytest.raises(Exception):
            ApplicantCreate(household_size=50)  # Exceeds max=30

    def test_invalid_dependants(self):
        with pytest.raises(Exception):
            ApplicantCreate(dependants=-1)  # Below min=0


class TestApplicantRead:
    def test_from_orm(self):
        now = datetime.now()
        schema = ApplicantRead(
            id=uuid.uuid4(),
            identity_reference="35202-1234567-1",
            applicant_type=ApplicantType.FREELANCER,
            household_size=4,
            city="Karachi",
            district="Karachi South",
            dependants=1,
            created_at=now,
            updated_at=now,
        )
        assert schema.city == "Karachi"


# ── Record schemas ──────────────────────────────────────────────────────────


class TestUtilityRecordCreate:
    def test_minimal(self):
        schema = UtilityRecordCreate()
        assert schema.utility_type is None

    def test_full(self):
        schema = UtilityRecordCreate(
            utility_type=UtilityType.ELECTRICITY,
            billing_month=date(2024, 6, 1),
            amount_billed=5000.0,
            amount_paid=5000.0,
            days_late=0,
        )
        assert schema.amount_billed == 5000.0

    def test_negative_amount_rejected(self):
        with pytest.raises(Exception):
            UtilityRecordCreate(amount_billed=-100)


class TestAcademicRecordCreate:
    def test_percentage(self):
        schema = AcademicRecordCreate(
            result_value=75.0,
            result_scale="percentage",
            year=2022,
        )
        assert schema.result_value == 75.0

    def test_gpa(self):
        schema = AcademicRecordCreate(
            result_value=3.5,
            result_scale="gpa",
        )
        assert schema.result_scale == "gpa"

    def test_invalid_year(self):
        with pytest.raises(Exception):
            AcademicRecordCreate(year=1900)


class TestIncomeSignalCreate:
    def test_minimal(self):
        schema = IncomeSignalCreate()
        assert schema.source_type is None

    def test_full(self):
        schema = IncomeSignalCreate(
            source_type="freelance",
            declared_monthly_amount=45000,
            evidence_type="documented",
            confidence_flag=True,
        )
        assert schema.confidence_flag is True


# ── Assessment schemas ──────────────────────────────────────────────────────


class TestFeatureContribution:
    def test_structure(self):
        fc = FeatureContribution(
            feature="payment_on_time_ratio",
            contribution=12.5,
            direction="positive",
            explanation="Pays bills on time 90% of the time.",
        )
        assert fc.direction == "positive"
        assert fc.contribution == 12.5


class TestAssessmentWithExplanations:
    def test_full(self):
        now = datetime.now()
        schema = AssessmentWithExplanations(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            score=72.5,
            band=ScoreBand.STRONG,
            model_version="0.1.0",
            is_rule_based=False,
            confidence_level=ConfidenceLevel.HIGH,
            created_at=now,
            feature_contributions=[
                FeatureContribution(
                    feature="payment_on_time_ratio",
                    contribution=15.0,
                    direction="positive",
                    explanation="Consistent on-time payments.",
                ),
            ],
            data_sufficiency_summary="7 features from 3 categories",
            categories_present=["utility", "academic", "income"],
            months_of_data=12,
        )
        assert schema.score == 72.5
        assert len(schema.feature_contributions) == 1

    def test_minimal(self):
        now = datetime.now()
        schema = AssessmentWithExplanations(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            score=25.0,
            band=ScoreBand.LOW,
            model_version="0.1.0",
            is_rule_based=True,
            confidence_level=ConfidenceLevel.LOW,
            created_at=now,
        )
        assert schema.feature_contributions is None


# ── Enums ───────────────────────────────────────────────────────────────────


class TestEnums:
    def test_applicant_type_values(self):
        assert ApplicantType.STUDENT.value == "student"
        assert ApplicantType.FREELANCER.value == "freelancer"
        assert ApplicantType.HOUSEHOLD.value == "household"

    def test_score_band_values(self):
        assert ScoreBand.LOW.value == "low"
        assert ScoreBand.MODERATE.value == "moderate"
        assert ScoreBand.STRONG.value == "strong"

    def test_enum_is_string(self):
        """Enums inherit from str, so they're JSON-serialisable."""
        assert isinstance(ApplicantType.STUDENT, str)
        assert isinstance(ScoreBand.MODERATE, str)
