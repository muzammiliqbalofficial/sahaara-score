"""
Scoring service — produces a 0-100 score, a band, and a confidence level.

Two scoring paths:
  1. Model-based (LightGBM + SHAP): used when enough features are present.
  2. Rule-based fallback: used for thin-file applicants.  Fully transparent
     weights, clearly flagged in the output.

The ``score_applicant`` method is the single entry point.  It decides which
path to use, computes the score, and delegates to the explainability service
for feature-level explanations.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import joblib

from app.config import get_settings
from app.models.assessment import Assessment
from app.services.anomaly_service import detect_anomalies
from app.services.explainability import (
    explain_model_prediction,
    explain_rule_based,
)
from app.services.feature_engineering import FeatureSet, build_feature_vector
from app.utils.enums import ConfidenceLevel, ScoreBand

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Feature order (must match training data column order) ──────────────────

FEATURE_NAMES = [
    "payment_on_time_ratio",
    "longest_on_time_streak",
    "mean_days_late",
    "payment_consistency",
    "academic_signal",
    "household_burden",
    "income_confidence",
    "total_income_normalised",
]

# ── Rule-based weights ─────────────────────────────────────────────────────
# These are hand-tuned to reflect domain priorities.  Payment reliability is
# the single strongest signal in the absence of a credit history.

RULE_WEIGHTS: dict[str, float] = {
    "payment_on_time_ratio": 0.30,
    "longest_on_time_streak": 0.10,
    "mean_days_late": 0.10,
    "payment_consistency": 0.10,
    "academic_signal": 0.15,
    "household_burden": 0.10,
    "income_confidence": 0.08,
    "total_income_normalised": 0.07,
}

# ── Model cache ─────────────────────────────────────────────────────────────

_MODEL_CACHE: dict = {}
_EXPLAINER_CACHE: dict = {}
_CALIBRATOR_CACHE: dict = {}

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "models_cache"


def _load_model_version() -> str:
    """Read the trained model's version from its metadata file."""
    meta_path = MODEL_DIR / "model_metadata.json"
    if meta_path.exists():
        import json
        try:
            meta = json.loads(meta_path.read_text())
            return meta.get("version", settings.model_version)
        except Exception:
            pass
    return settings.model_version


def _load_model():
    """Lazy-load the LightGBM model, returning None if not trained yet."""
    if "model" in _MODEL_CACHE:
        return _MODEL_CACHE["model"]

    model_path = MODEL_DIR / "sahaara_lgbm.joblib"
    if not model_path.exists():
        logger.warning(
            "No trained model found at %s — all scores will use the "
            "rule-based fallback until a model is trained.",
            model_path,
        )
        _MODEL_CACHE["model"] = None
        return None

    _MODEL_CACHE["model"] = None
    try:
        _MODEL_CACHE["model"] = joblib.load(model_path)
    except Exception as e:
        logger.warning(
            "Failed to load model from %s (%s) — falling back to "
            "rule-based scoring.",
            model_path, e,
        )
    return _MODEL_CACHE["model"]


def clear_model_cache() -> None:
    """Clear cached model, explainer, and calibrator so the next call reloads from disk."""
    _MODEL_CACHE.clear()
    _EXPLAINER_CACHE.clear()
    _CALIBRATOR_CACHE.clear()


def _load_explainer():
    """Lazy-load the SHAP explainer."""
    if "explainer" in _EXPLAINER_CACHE:
        return _EXPLAINER_CACHE["explainer"]

    model = _load_model()
    if model is None:
        _EXPLAINER_CACHE["explainer"] = None
        return None

    try:
        import shap
        explainer = shap.TreeExplainer(model)
        _EXPLAINER_CACHE["explainer"] = explainer
        return explainer
    except Exception as e:
        logger.warning("Failed to create SHAP explainer: %s", e)
        _EXPLAINER_CACHE["explainer"] = None
        return None


def _load_calibrator():
    """
    Lazy-load the isotonic calibrator fitted during training.

    The calibrator maps raw LightGBM regression outputs to calibrated
    probabilities.  Returns None if no calibrator file exists (old
    pre-v1.1 models).
    """
    if "calibrator" in _CALIBRATOR_CACHE:
        return _CALIBRATOR_CACHE["calibrator"]

    cal_path = MODEL_DIR / "calibrator.joblib"
    if not cal_path.exists():
        logger.info(
            "No calibrator found at %s -- scores will use raw model output.",
            cal_path,
        )
        _CALIBRATOR_CACHE["calibrator"] = None
        return None

    _CALIBRATOR_CACHE["calibrator"] = joblib.load(cal_path)
    return _CALIBRATOR_CACHE["calibrator"]


# ── Scoring functions ───────────────────────────────────────────────────────


def _score_to_band(score: float) -> ScoreBand:
    """Map a 0-100 score to a human-readable band."""
    if score >= 60:
        return ScoreBand.STRONG
    elif score >= 35:
        return ScoreBand.MODERATE
    return ScoreBand.LOW


def _compute_confidence(feature_set: FeatureSet) -> ConfidenceLevel:
    """
    Derive a confidence level from data sufficiency.

    HIGH:   3 categories AND 6+ months of utility data
    MEDIUM: 2 categories OR 3+ months of data
    LOW:    everything else
    """
    n_cats = len(feature_set.categories_present)
    months = feature_set.months_of_utility_data

    if n_cats >= 3 and months >= 6:
        return ConfidenceLevel.HIGH
    elif n_cats >= 2 or months >= 3:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def _score_model_based(feature_set: FeatureSet) -> tuple[float, list[dict]]:
    """
    Score using the trained LightGBM model.

    Returns (score_0_100, feature_contributions).

    HARD GATE: If non_null_count is below the minimum data threshold this
    function refuses to run.  Missing data must never be read as ordinary
    data by the model — that is the core principle of this project.
    """
    # ── Hard gate ───────────────────────────────────────────────────────
    # This is a *fail-safe* in addition to the check in score_applicant.
    # If a caller ever bypasses the outer gate, this prevents the model
    # from scoring a thin-file applicant.
    if feature_set.non_null_count < settings.min_model_data_points:
        raise RuntimeError(
            f"Refusing to score thin-file applicant with model "
            f"(non_null_count={feature_set.non_null_count} < "
            f"min_model_data_points={settings.min_model_data_points}). "
            f"Route to rule-based path instead."
        )

    model = _load_model()
    explainer = _load_explainer()

    if model is None:
        raise RuntimeError("Model not available — should not reach this path")

    # Build feature array, substituting -1 for None (LightGBM handles -1
    # as a missing value indicator when trained with NaN handling).
    feature_array = np.array([
        [feature_set.features.get(name) if feature_set.features.get(name) is not None else np.nan
         for name in FEATURE_NAMES]
    ])

    raw_score = model.predict(feature_array)[0]

    # Apply isotonic calibrator if available (v1.1+).
    calibrator = _load_calibrator()
    if calibrator is not None:
        raw_score = float(calibrator.predict(np.array([raw_score]))[0])

    score = float(np.clip(raw_score * 100, 0, 100))

    contributions = explain_model_prediction(
        feature_set, feature_array, explainer, FEATURE_NAMES
    )

    return score, contributions


def _score_rule_based(feature_set: FeatureSet) -> tuple[float, list[dict]]:
    """
    Score using transparent, weighted rules.

    Only non-null features contribute; the denominator adjusts so that
    having fewer features doesn't penalise the applicant.
    """
    weighted_sum = 0.0
    total_weight = 0.0
    contributions: list[dict] = []

    for feature_name, weight in RULE_WEIGHTS.items():
        value = feature_set.features.get(feature_name)
        if value is None:
            continue

        weighted_sum += value * weight
        total_weight += weight

        contributions.append({
            "feature": feature_name,
            "raw_value": round(value, 3),
            "weight": weight,
            "weighted_contribution": round(value * weight, 3),
        })

    if total_weight == 0:
        # No features at all → return a neutral baseline.
        return 25.0, []

    # Normalise by total weight of *available* features so the score
    # isn't artificially low just because some data is missing.
    normalised_score = weighted_sum / total_weight
    score = float(np.clip(normalised_score * 100, 0, 100))

    explanations = explain_rule_based(contributions, feature_set)
    return score, explanations


# ── Public API ──────────────────────────────────────────────────────────────


def score_applicant(applicant) -> dict:
    """
    Compute a Sahaara Score for an applicant.

    Returns a dict ready for creating an Assessment ORM object:
    {
        "score": float,
        "band": ScoreBand,
        "confidence_level": ConfidenceLevel,
        "is_rule_based": bool,
        "model_version": str,
        "feature_contributions": list[dict],
        "data_sufficiency_summary": str,
        "categories_present": list[str],
        "months_of_data": int,
        "anomaly_risk_score": float,
        "anomaly_risk_level": RiskLevel,
        "anomaly_audit_required": bool,
        "anomaly_flags_count": int,
        "anomaly_report": dict,   # Full fraud-shield report (JSONB-ready)
    }
    """
    feature_set = build_feature_vector(applicant)
    confidence = _compute_confidence(feature_set)

    # Decide scoring path.
    model = _load_model()
    use_model = (
        model is not None
        and feature_set.non_null_count >= settings.min_model_data_points
    )

    if use_model:
        score, contributions = _score_model_based(feature_set)
        is_rule_based = False
        version = _load_model_version()
    else:
        score, contributions = _score_rule_based(feature_set)
        is_rule_based = True
        version = "rule-based"

    # Fraud shield — runs on the same records the score was computed from,
    # with the score and confidence as context for the policy recommendation.
    anomaly_report = detect_anomalies(
        applicant,
        applicant.utility_records or [],
        applicant.academic_records or [],
        applicant.income_signals or [],
        feature_set,
        score=score,
        confidence=confidence,
    )

    return {
        "score": round(score, 2),
        "band": _score_to_band(score),
        "confidence_level": confidence,
        "is_rule_based": is_rule_based,
        "model_version": version,
        "feature_contributions": contributions,
        "data_sufficiency_summary": feature_set.data_sufficiency_summary,
        "categories_present": feature_set.categories_present,
        "months_of_data": feature_set.months_of_utility_data,
        # First-class sufficiency fields — not side metadata.
        "signal_categories_count": len(feature_set.categories_present),
        "non_null_feature_count": feature_set.non_null_count,
        # Fraud shield verdict.
        "anomaly_risk_score": anomaly_report.risk_score,
        "anomaly_risk_level": anomaly_report.risk_level,
        "anomaly_audit_required": anomaly_report.audit_required,
        "anomaly_flags_count": anomaly_report.flags_count,
        "anomaly_report": anomaly_report.to_dict(),
    }
