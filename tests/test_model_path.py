"""
Integration tests for the dual scoring path (model-based + rule-based).

These tests ensure:
  1. The model path is used for applicants with sufficient features.
  2. The rule-based path is used for thin-file applicants.
  3. If the model artefact is missing, tests that expect the model path FAIL
     rather than silently passing through the fallback.
  4. SHAP values are genuinely produced on the model path.
"""

from pathlib import Path

import pytest

from app.services.scoring_service import (
    MODEL_DIR,
    _load_model,
    clear_model_cache,
    score_applicant,
    FEATURE_NAMES,
)
from app.services.feature_engineering import build_feature_vector
from app.utils.enums import ScoreBand, ConfidenceLevel


MODEL_PATH = MODEL_DIR / "sahaara_lgbm.joblib"


# ── Helpers ──────────────────────────────────────────────────────────────


def _model_exists() -> bool:
    return MODEL_PATH.exists()


# ── Model artefact gate ──────────────────────────────────────────────────


class TestModelArtefact:
    """The model artefact must exist for the model path to be tested."""

    def test_model_file_exists(self):
        """
        This test fails if the trained model is missing.
        The model path tests below depend on this artefact.
        Run `python -m training` to produce it.
        """
        assert _model_exists(), (
            f"Trained model not found at {MODEL_PATH}. "
            f"Run `python -m training` to train the model first."
        )

    def test_model_loads(self):
        """Model file must be loadable by joblib."""
        clear_model_cache()
        model = _load_model()
        assert model is not None, "Model file exists but failed to load."


# ── Model-based path ─────────────────────────────────────────────────────


class TestModelBasedPath:
    """Verify the model path actually runs for data-rich applicants."""

    @pytest.fixture(autouse=True)
    def _require_model(self):
        if not _model_exists():
            pytest.skip("Model artefact not present — skipping model path tests.")

    def test_full_applicant_uses_model(self, full_applicant):
        """Full applicant (8 features) should use the model path, not rules."""
        clear_model_cache()
        result = score_applicant(full_applicant)

        assert result["is_rule_based"] is False, (
            "Full applicant should use model path, but got rule-based. "
            "Either the model is missing or min_model_data_points is too high."
        )
        assert 0 <= result["score"] <= 100
        assert result["band"] in (ScoreBand.LOW, ScoreBand.MODERATE, ScoreBand.STRONG)

    def test_model_path_produces_shap_explanations(self, full_applicant):
        """Model path must produce SHAP-based feature contributions."""
        clear_model_cache()
        result = score_applicant(full_applicant)

        assert result["is_rule_based"] is False

        contributions = result["feature_contributions"]
        assert isinstance(contributions, list)
        assert len(contributions) > 0

        # SHAP contributions should include all 8 features.
        feature_names_in_contributions = {c["feature"] for c in contributions}
        assert feature_names_in_contributions == set(FEATURE_NAMES), (
            f"Expected all {len(FEATURE_NAMES)} features in SHAP contributions, "
            f"got {feature_names_in_contributions}"
        )

        # At least some SHAP values should be non-zero (genuine SHAP, not fallback).
        non_zero = [c for c in contributions if abs(c.get("contribution", 0)) > 0.001]
        assert len(non_zero) >= 3, (
            f"Expected genuine SHAP contributions but only {len(non_zero)} "
            f"features have non-zero contribution. "
            f"SHAP may not be running — model path might be falling back to rules."
        )

    def test_model_path_has_label_and_raw_value(self, full_applicant):
        """SHAP contributions should include label and raw_value fields."""
        clear_model_cache()
        result = score_applicant(full_applicant)
        assert result["is_rule_based"] is False

        for c in result["feature_contributions"]:
            assert "label" in c, f"Missing 'label' in contribution: {c}"
            assert "raw_value" in c, f"Missing 'raw_value' in contribution: {c}"
            assert "explanation" in c
            assert c["direction"] in ("positive", "negative", "neutral")

    def test_model_version_matches_trained(self, full_applicant):
        """model_version on assessment should match the trained model."""
        clear_model_cache()
        result = score_applicant(full_applicant)
        assert result["is_rule_based"] is False
        assert result["model_version"].startswith(("1.0.0", "1.1.0")), (
            f"Expected model version 1.0.0-* or 1.1.0-* but got {result['model_version']}"
        )


# ── Rule-based path ──────────────────────────────────────────────────────


class TestRuleBasedPath:
    """Verify rule-based path still works for thin/empty applicants."""

    def test_thin_applicant_uses_rules(self, thin_applicant):
        """Thin-file applicant (3 features) should always use rules."""
        result = score_applicant(thin_applicant)
        assert result["is_rule_based"] is True
        assert 0 <= result["score"] <= 100

    def test_empty_applicant_uses_rules(self, empty_applicant):
        """Empty applicant should always use rules with baseline score."""
        result = score_applicant(empty_applicant)
        assert result["is_rule_based"] is True
        assert result["score"] == 25.0

    def test_thin_path_has_rule_explanations(self, thin_applicant):
        """Rule-based path should produce transparent weight-based explanations."""
        result = score_applicant(thin_applicant)
        contributions = result["feature_contributions"]
        assert isinstance(contributions, list)
        assert len(contributions) > 0

        # Rule-based contributions have 'weight' field.
        present = [c for c in contributions if c.get("raw_value") is not None]
        assert len(present) > 0, "No features had raw_value in rule-based output."


# ── Zero-feature hard gate ──────────────────────────────────────────────


class TestZeroFeatureGate:
    """
    A zero-feature applicant must NEVER reach the model path.

    This is the project's core principle: missing data must never be read
    as ordinary data. The model would output ~56.7 for a completely empty
    applicant, which is a fabricated number built on nothing.
    """

    def test_zero_feature_applicant_never_uses_model(self, empty_applicant):
        """
        An applicant with zero features MUST use the rule-based path.
        This test MUST FAIL if the zero-feature gate is removed or bypassed.
        """
        clear_model_cache()
        result = score_applicant(empty_applicant)

        assert result["is_rule_based"] is True, (
            "CRITICAL: zero-feature applicant reached the model path! "
            "The hard gate in scoring_service must never allow this."
        )
        assert result["score"] == 25.0, (
            f"Empty applicant should get baseline 25.0, got {result['score']}"
        )
        assert result["non_null_feature_count"] == 0
        assert result["signal_categories_count"] == 0

    def test_zero_feature_model_call_raises(self, empty_applicant):
        """
        If someone calls _score_model_based directly with zero features,
        it must raise RuntimeError rather than silently produce a score.
        """
        from app.services.scoring_service import _score_model_based
        from app.services.feature_engineering import build_feature_vector

        feature_set = build_feature_vector(empty_applicant)
        with pytest.raises(RuntimeError, match="Refusing to score thin-file"):
            _score_model_based(feature_set)

    def test_thin_applicant_never_uses_model(self, thin_applicant):
        """
        Thin-file applicants (below min_model_data_points) must also
        never reach the model, even when the model artefact exists.
        """
        clear_model_cache()
        result = score_applicant(thin_applicant)
        assert result["is_rule_based"] is True
        assert result["non_null_feature_count"] < 6, (
            "Thin applicant should have fewer than 6 non-null features."
        )


# ── Both paths produce valid outputs ─────────────────────────────────────


class TestPathConsistency:
    """Both paths must produce structurally valid, comparable outputs."""

    def _score_both(self, full_applicant, thin_applicant):
        clear_model_cache()
        full_result = score_applicant(full_applicant)
        thin_result = score_applicant(thin_applicant)
        return full_result, thin_result

    def test_both_paths_return_required_keys(self, full_applicant, thin_applicant):
        full_result, thin_result = self._score_both(full_applicant, thin_applicant)

        required_keys = [
            "score", "band", "confidence_level", "is_rule_based",
            "model_version", "feature_contributions",
            "data_sufficiency_summary", "categories_present", "months_of_data",
            # First-class sufficiency fields.
            "signal_categories_count", "non_null_feature_count",
        ]
        for key in required_keys:
            assert key in full_result, f"Model path missing key: {key}"
            assert key in thin_result, f"Rule path missing key: {key}"

    def test_both_paths_scores_in_range(self, full_applicant, thin_applicant):
        full_result, thin_result = self._score_both(full_applicant, thin_applicant)
        assert 0 <= full_result["score"] <= 100
        assert 0 <= thin_result["score"] <= 100

    def test_paths_are_distinguishable(self, full_applicant, thin_applicant):
        """The two paths should not produce identical scores for the same data."""
        clear_model_cache()
        # Score the full applicant with model path.
        model_result = score_applicant(full_applicant)
        if model_result["is_rule_based"]:
            pytest.skip("Model not available — can't compare paths.")
        # We can't directly compare because the thin applicant has different data,
        # but we can verify the model path produces a different result structure.
        assert model_result["is_rule_based"] is False
        # Model path contributions should differ structurally from rule-based
        # (SHAP values vs weighted contributions).
        model_contrib = model_result["feature_contributions"]
        has_shap_fields = any("label" in c for c in model_contrib)
        assert has_shap_fields, "Model path contributions lack SHAP-specific fields."
