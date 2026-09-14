"""
Tests for the feature engineering module.

These tests verify that:
  1. Each feature function handles missing data correctly (returns None).
  2. Features are normalised to the expected 0-1 range.
  3. Academic results are normalised correctly across all three scales.
  4. The master build_feature_vector produces correct metadata.
"""

import math
from datetime import date

from app.services.feature_engineering import (
    FeatureSet,
    academic_signal,
    billed_amount_cv,
    build_feature_vector,
    data_sufficiency,
    household_burden,
    income_confidence,
    longest_on_time_streak,
    mean_days_late,
    payment_on_time_ratio,
    total_declared_income,
)
from tests.conftest import (
    MockAcademicRecord,
    MockApplicant,
    MockIncomeSignal,
    MockUtilityRecord,
)


# ── Payment reliability ─────────────────────────────────────────────────────


class TestPaymentOnTimeRatio:
    def test_all_on_time(self):
        records = [
            MockUtilityRecord(days_late=0),
            MockUtilityRecord(days_late=0),
            MockUtilityRecord(days_late=0),
        ]
        assert payment_on_time_ratio(records) == 1.0

    def test_some_late(self):
        records = [
            MockUtilityRecord(days_late=0),
            MockUtilityRecord(days_late=5),
            MockUtilityRecord(days_late=0),
            MockUtilityRecord(days_late=10),
        ]
        assert payment_on_time_ratio(records) == 0.5

    def test_all_late(self):
        records = [
            MockUtilityRecord(days_late=3),
            MockUtilityRecord(days_late=7),
        ]
        assert payment_on_time_ratio(records) == 0.0

    def test_empty_records(self):
        assert payment_on_time_ratio([]) is None

    def test_all_null_days_late(self):
        records = [
            MockUtilityRecord(days_late=None),
            MockUtilityRecord(days_late=None),
        ]
        assert payment_on_time_ratio(records) is None

    def test_mixed_null_and_zero(self):
        records = [
            MockUtilityRecord(days_late=0),
            MockUtilityRecord(days_late=None),
            MockUtilityRecord(days_late=0),
        ]
        # Only 2 records have timing data, both on time.
        assert payment_on_time_ratio(records) == 1.0


class TestLongestOnTimeStreak:
    def test_consecutive_on_time(self):
        records = [
            MockUtilityRecord(billing_month=date(2024, 1, 1), days_late=0),
            MockUtilityRecord(billing_month=date(2024, 2, 1), days_late=0),
            MockUtilityRecord(billing_month=date(2024, 3, 1), days_late=0),
            MockUtilityRecord(billing_month=date(2024, 4, 1), days_late=5),
            MockUtilityRecord(billing_month=date(2024, 5, 1), days_late=0),
        ]
        assert longest_on_time_streak(records) == 3.0

    def test_single_record(self):
        records = [
            MockUtilityRecord(billing_month=date(2024, 1, 1), days_late=0),
        ]
        assert longest_on_time_streak(records) is None

    def test_no_timing_data(self):
        records = [
            MockUtilityRecord(billing_month=date(2024, 1, 1), days_late=None),
            MockUtilityRecord(billing_month=date(2024, 2, 1), days_late=None),
        ]
        assert longest_on_time_streak(records) is None


class TestMeanDaysLate:
    def test_normal(self):
        records = [
            MockUtilityRecord(days_late=0),
            MockUtilityRecord(days_late=5),
            MockUtilityRecord(days_late=10),
        ]
        assert mean_days_late(records) == 5.0

    def test_empty(self):
        assert mean_days_late([]) is None

    def test_all_null(self):
        records = [MockUtilityRecord(days_late=None)]
        assert mean_days_late(records) is None


# ── Payment consistency ─────────────────────────────────────────────────────


class TestBilledAmountCV:
    def test_stable_amounts(self):
        # Very low CV → normalised value close to 1.0.
        records = [
            MockUtilityRecord(amount_billed=5000),
            MockUtilityRecord(amount_billed=5010),
            MockUtilityRecord(amount_billed=4990),
            MockUtilityRecord(amount_billed=5005),
        ]
        result = billed_amount_cv(records)
        assert result is not None
        assert result > 0.9

    def test_erratic_amounts(self):
        # High CV → normalised value close to 0.
        records = [
            MockUtilityRecord(amount_billed=1000),
            MockUtilityRecord(amount_billed=15000),
            MockUtilityRecord(amount_billed=500),
            MockUtilityRecord(amount_billed=20000),
        ]
        result = billed_amount_cv(records)
        assert result is not None
        assert result < 0.3

    def test_single_record(self):
        records = [MockUtilityRecord(amount_billed=5000)]
        assert billed_amount_cv(records) is None

    def test_empty(self):
        assert billed_amount_cv([]) is None


# ── Academic signal ─────────────────────────────────────────────────────────


class TestAcademicSignal:
    def test_percentage_scale(self):
        records = [
            MockAcademicRecord(
                result_value=80.0,
                result_scale="percentage",
                qualification_level="matric",
                year=2024,
            )
        ]
        result = academic_signal(records)
        assert result is not None
        # 80/100 * 0.8 (matric weight) * recency ≈ 0.72
        assert 0.55 < result < 0.80

    def test_gpa_scale(self):
        records = [
            MockAcademicRecord(
                result_value=3.5,
                result_scale="gpa",
                qualification_level="bachelors",
                year=2024,
            )
        ]
        result = academic_signal(records)
        assert result is not None
        # 3.5/4.0 * 0.95 (bachelors) * recency ≈ 0.83
        assert 0.70 < result < 0.90

    def test_division_scale_first(self):
        records = [
            MockAcademicRecord(
                result_value=1.0,
                result_scale="division",
                qualification_level="bachelors",
                year=2024,
            )
        ]
        result = academic_signal(records)
        assert result is not None
        # 0.85 * 0.95 * recency
        assert result > 0.65

    def test_division_scale_third(self):
        records = [
            MockAcademicRecord(
                result_value=3.0,
                result_scale="division",
                qualification_level="bachelors",
                year=2020,
            )
        ]
        result = academic_signal(records)
        assert result is not None
        # 0.45 * 0.95 * 0.8 (recency for 6 years ago)
        assert result < 0.40

    def test_empty_records(self):
        assert academic_signal([]) is None

    def test_multiple_records_returns_best(self):
        records = [
            MockAcademicRecord(
                result_value=60.0, result_scale="percentage",
                qualification_level="matric", year=2020,
            ),
            MockAcademicRecord(
                result_value=3.8, result_scale="gpa",
                qualification_level="masters", year=2025,
            ),
        ]
        result = academic_signal(records)
        assert result is not None
        # The masters GPA record should be the best.
        assert result > 0.75

    def test_no_result_value(self):
        records = [
            MockAcademicRecord(result_value=None, result_scale="percentage"),
        ]
        assert academic_signal(records) is None


# ── Household burden ────────────────────────────────────────────────────────


class TestHouseholdBurden:
    def test_low_burden(self):
        income = [
            MockIncomeSignal(declared_monthly_amount=80000),
        ]
        utility = [
            MockUtilityRecord(amount_billed=5000),
        ]
        result = household_burden(1, income, utility)
        assert result is not None
        assert result > 0.7  # Low burden

    def test_high_burden(self):
        income = [
            MockIncomeSignal(declared_monthly_amount=15000),
        ]
        utility = [
            MockUtilityRecord(amount_billed=8000),
        ]
        result = household_burden(6, income, utility)
        assert result is not None
        assert result < 0.5  # High burden

    def test_no_data(self):
        assert household_burden(None, [], []) is None


# ── Data sufficiency ────────────────────────────────────────────────────────


class TestDataSufficiency:
    def test_all_categories(self, full_applicant):
        cats, months = data_sufficiency(
            full_applicant.utility_records,
            full_applicant.academic_records,
            full_applicant.income_signals,
        )
        assert "utility" in cats
        assert "academic" in cats
        assert "income" in cats
        assert months == 8

    def test_utility_only(self, thin_applicant):
        cats, months = data_sufficiency(
            thin_applicant.utility_records,
            thin_applicant.academic_records,
            thin_applicant.income_signals,
        )
        assert cats == ["utility"]
        assert months == 3

    def test_no_data(self, empty_applicant):
        cats, months = data_sufficiency(
            empty_applicant.utility_records,
            empty_applicant.academic_records,
            empty_applicant.income_signals,
        )
        assert cats == []
        assert months == 0


# ── Income confidence ───────────────────────────────────────────────────────


class TestIncomeConfidence:
    def test_verified_income(self):
        signals = [
            MockIncomeSignal(
                declared_monthly_amount=50000,
                evidence_type="verified",
                confidence_flag=True,
            ),
        ]
        result = income_confidence(signals)
        assert result is not None
        assert result > 0.9

    def test_self_declared(self):
        signals = [
            MockIncomeSignal(
                declared_monthly_amount=20000,
                evidence_type="self_declared",
                confidence_flag=False,
            ),
        ]
        result = income_confidence(signals)
        assert result is not None
        assert result < 0.5

    def test_empty(self):
        assert income_confidence([]) is None


# ── Build feature vector (integration) ──────────────────────────────────────


class TestBuildFeatureVector:
    def test_full_applicant(self, full_applicant):
        fs = build_feature_vector(full_applicant)
        assert isinstance(fs, FeatureSet)
        assert fs.non_null_count >= 5
        assert "utility" in fs.categories_present
        assert "academic" in fs.categories_present
        assert "income" in fs.categories_present
        assert fs.months_of_utility_data == 8

        # All features should be present for a full applicant.
        assert fs.features["payment_on_time_ratio"] is not None
        assert fs.features["academic_signal"] is not None
        assert fs.features["total_income_normalised"] is not None

    def test_thin_applicant(self, thin_applicant):
        fs = build_feature_vector(thin_applicant)
        assert fs.non_null_count < 5
        assert "utility" in fs.categories_present
        assert "academic" not in fs.categories_present
        assert "income" not in fs.categories_present

        # Academic and income features should be None.
        assert fs.features["academic_signal"] is None
        assert fs.features["income_confidence"] is None

    def test_empty_applicant(self, empty_applicant):
        fs = build_feature_vector(empty_applicant)
        assert fs.non_null_count == 0
        assert fs.categories_present == []
        assert all(v is None for v in fs.features.values())

    def test_data_sufficiency_summary(self, full_applicant):
        fs = build_feature_vector(full_applicant)
        summary = fs.data_sufficiency_summary
        assert "features computed" in summary
        assert "signal categories" in summary
