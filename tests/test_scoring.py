"""
Tests for the scoring service.

Verifies:
  1. Rule-based scoring produces valid scores (0-100) and bands.
  2. Thin-file applicants always use the rule-based path.
  3. Confidence levels are correctly derived from data sufficiency.
  4. The score_applicant function returns a complete result dict.
"""

from app.services.scoring_service import (
    RULE_WEIGHTS,
    _compute_confidence,
    _score_rule_based,
    _score_to_band,
    score_applicant,
)
from app.services.explainability import explain_rule_based
from app.services.feature_engineering import FeatureSet, build_feature_vector
from app.utils.enums import ConfidenceLevel, ScoreBand
from tests.conftest import MockApplicant, MockIncomeSignal


# ── Score to band mapping ──────────────────────────────────────────────────


class TestScoreToBand:
    def test_strong(self):
        assert _score_to_band(80) == ScoreBand.STRONG
        assert _score_to_band(60) == ScoreBand.STRONG

    def test_moderate(self):
        assert _score_to_band(50) == ScoreBand.MODERATE
        assert _score_to_band(35) == ScoreBand.MODERATE

    def test_low(self):
        assert _score_to_band(20) == ScoreBand.LOW
        assert _score_to_band(0) == ScoreBand.LOW


# ── Confidence computation ──────────────────────────────────────────────────


class TestComputeConfidence:
    def test_high_confidence(self):
        fs = FeatureSet(
            categories_present=["utility", "academic", "income"],
            months_of_utility_data=8,
        )
        assert _compute_confidence(fs) == ConfidenceLevel.HIGH

    def test_medium_confidence_two_categories(self):
        fs = FeatureSet(
            categories_present=["utility", "academic"],
            months_of_utility_data=2,
        )
        assert _compute_confidence(fs) == ConfidenceLevel.MEDIUM

    def test_medium_confidence_months(self):
        fs = FeatureSet(
            categories_present=["utility"],
            months_of_utility_data=5,
        )
        assert _compute_confidence(fs) == ConfidenceLevel.MEDIUM

    def test_low_confidence(self):
        fs = FeatureSet(
            categories_present=["utility"],
            months_of_utility_data=1,
        )
        assert _compute_confidence(fs) == ConfidenceLevel.LOW

    def test_no_data(self):
        fs = FeatureSet(
            categories_present=[],
            months_of_utility_data=0,
        )
        assert _compute_confidence(fs) == ConfidenceLevel.LOW


# ── Rule-based scoring ──────────────────────────────────────────────────────


class TestScoreRuleBased:
    def test_perfect_features(self):
        """All features at 1.0 should produce a score of 100."""
        fs = FeatureSet(
            features={name: 1.0 for name in RULE_WEIGHTS},
            categories_present=["utility", "academic", "income"],
        )
        score, contributions = _score_rule_based(fs)
        assert score == 100.0
        assert len(contributions) > 0

    def test_zero_features(self):
        """All features at 0.0 should produce a score of 0."""
        fs = FeatureSet(
            features={name: 0.0 for name in RULE_WEIGHTS},
            categories_present=["utility", "academic", "income"],
        )
        score, _ = _score_rule_based(fs)
        assert score == 0.0

    def test_partial_features(self):
        """Only some features present — score normalises by available weight."""
        fs = FeatureSet(
            features={
                "payment_on_time_ratio": 1.0,
                "academic_signal": None,
                "income_confidence": None,
                "longest_on_time_streak": None,
                "mean_days_late": None,
                "payment_consistency": None,
                "household_burden": None,
                "total_income_normalised": None,
            },
            categories_present=["utility"],
        )
        score, contributions = _score_rule_based(fs)
        # Only payment_on_time_ratio (weight 0.30) is present at 1.0.
        # Normalised: 1.0 * 0.30 / 0.30 = 1.0 → score = 100.
        assert score == 100.0

    def test_no_features_at_all(self):
        """Completely empty feature set returns baseline 25."""
        fs = FeatureSet(
            features={name: None for name in RULE_WEIGHTS},
            categories_present=[],
        )
        score, contributions = _score_rule_based(fs)
        assert score == 25.0
        assert contributions == []


# ── Integration: score_applicant ────────────────────────────────────────────


class TestScoreApplicant:
    def test_full_applicant(self, full_applicant):
        """Full applicant should get a valid score and band."""
        result = score_applicant(full_applicant)

        assert 0 <= result["score"] <= 100
        assert result["band"] in (ScoreBand.LOW, ScoreBand.MODERATE, ScoreBand.STRONG)
        assert result["confidence_level"] in (
            ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW,
        )
        assert isinstance(result["feature_contributions"], list)
        assert len(result["feature_contributions"]) > 0
        assert "features computed" in result["data_sufficiency_summary"]

    def test_thin_applicant_uses_rule_based(self, thin_applicant):
        """Thin-file applicant should always use rule-based path."""
        result = score_applicant(thin_applicant)

        assert result["is_rule_based"] is True
        assert 0 <= result["score"] <= 100
        assert result["band"] in (ScoreBand.LOW, ScoreBand.MODERATE, ScoreBand.STRONG)
        # Thin file → low or medium confidence.
        assert result["confidence_level"] in (
            ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM,
        )

    def test_empty_applicant_baseline(self, empty_applicant):
        """Empty applicant gets baseline score of 25 with low confidence."""
        result = score_applicant(empty_applicant)

        assert result["is_rule_based"] is True
        assert result["score"] == 25.0
        assert result["confidence_level"] == ConfidenceLevel.LOW
        assert result["categories_present"] == []
        assert result["months_of_data"] == 0

    def test_result_structure(self, full_applicant):
        """Verify the result dict has all required keys."""
        result = score_applicant(full_applicant)

        required_keys = [
            "score", "band", "confidence_level", "is_rule_based",
            "model_version", "feature_contributions",
            "data_sufficiency_summary", "categories_present", "months_of_data",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"


# ── Issue #1: Income normalisation must not display normalised values ─────


class TestIncomeNormalisation:
    def test_implausibly_low_income_no_positive_contribution(self):
        """An income of PKR 1 must never produce a positive contribution.

        The previous bug passed the normalised 0-1 value to a display
        template that expected raw PKR, turning 0.0 into 'PKR 1'.
        """
        applicant = MockApplicant(dependants=1)
        applicant.income_signals.append(MockIncomeSignal(
            applicant_id=applicant.id,
            source_type="wage",
            declared_monthly_amount=1, # PKR 1 — implausibly low
            evidence_type="self_declared",
            confidence_flag=False,
        ))
        feature_set = build_feature_vector(applicant)

        # The raw income must be stored as PKR 1, not the normalised value.
        assert feature_set.raw_values.get("total_income_normalised") == 1

        score, contributions = _score_rule_based(feature_set)

        # Find the income explanation (if any).
        income_expl = next(
            (e for e in contributions if e["feature"] == "total_income_normalised"),
            None,
        )
        if income_expl is not None and not income_expl.get("no_data"):
            # PKR 1 normalises to ~0 on a log scale, so it should NOT
            # contribute positively.
            assert income_expl["contribution"] <= 0.0, (
                f"PKR 1 income produced positive contribution "
                f"{income_expl['contribution']}"
            )

    def test_realistic_income_displays_raw_pkr(self):
        """A PKR 120 000 income must display as PKR 120,000, not 'PKR 1'."""
        applicant = MockApplicant(dependants=1)
        applicant.income_signals.append(MockIncomeSignal(
            applicant_id=applicant.id,
            source_type="salary",
            declared_monthly_amount=120_000,
            evidence_type="documented",
            confidence_flag=True,
        ))
        feature_set = build_feature_vector(applicant)
        _, contributions = _score_rule_based(feature_set)

        income_contrib = next(
            (c for c in contributions if c["feature"] == "total_income_normalised"),
            None,
        )
        assert income_contrib is not None

        # The explanation text must contain the raw PKR amount, not a
        # normalised 0-1 number rounded to 1.
        explanation = income_contrib["explanation"]
        assert "120,000" in explanation or "120000" in explanation, (
            f"Expected raw PKR amount in explanation, got: {explanation!r}"
        )


# ── Issue #3: Absent features must be tagged as no_data ───────────────────


class TestAbsentFeaturesNoData:
    def test_missing_features_flagged_no_data(self):
        """Features with no underlying data must be marked no_data=True."""
        fs = FeatureSet(
            features={name: None for name in RULE_WEIGHTS},
            raw_values={},
            categories_present=[],
        )
        explanations = explain_rule_based([], fs)

        # Every feature in the description catalogue must appear.
        assert len(explanations) > 0
        for expl in explanations:
            assert expl["no_data"] is True, (
                f"Feature {expl['feature']!r} has no data but no_data is False"
            )
            assert expl["contribution"] == 0.0
            assert expl["raw_value"] is None

    def test_present_features_not_flagged_no_data(self):
        """Features that have data must NOT be marked no_data."""
        fs = FeatureSet(
            features={
                "payment_on_time_ratio": 0.8,
                "longest_on_time_streak": 0.5,
                "mean_days_late": 0.7,
                "payment_consistency": None,
                "academic_signal": None,
                "household_burden": None,
                "income_confidence": None,
                "total_income_normalised": None,
            },
            raw_values={
                "longest_on_time_streak": 6.0,
                "mean_days_late": 3.0,
            },
            categories_present=["utility"],
        )
        contributions = [
            {"feature": "payment_on_time_ratio", "raw_value": 0.8, "weight": 0.30, "weighted_contribution": 0.24},
            {"feature": "longest_on_time_streak", "raw_value": 0.5, "weight": 0.10, "weighted_contribution": 0.05},
            {"feature": "mean_days_late", "raw_value": 0.7, "weight": 0.10, "weighted_contribution": 0.07},
        ]
        explanations = explain_rule_based(contributions, fs)

        present = [e for e in explanations if not e["no_data"]]
        absent = [e for e in explanations if e["no_data"]]

        assert len(present) == 3
        assert len(absent) == 5 # 8 total features - 3 present
        for e in absent:
            assert e["contribution"] == 0.0
            assert e["raw_value"] is None
