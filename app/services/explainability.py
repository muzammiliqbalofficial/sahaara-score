"""
Explainability service — translates numerical contributions into plain-language
explanations that a human reviewer can read and act on.

Two paths:
  1. SHAP-based: uses the TreeExplainer to decompose the model prediction.
  2. Rule-based: uses the known weights to describe each feature's contribution.

Every explanation includes:
  - Feature name (humanised)
  - Direction (positive / negative / neutral)
  - Magnitude (how many points this feature added or subtracted)
  - A plain-language sentence a non-technical reviewer can understand
"""

from __future__ import annotations

import numpy as np

from app.services.feature_engineering import FeatureSet

# ── Human-readable feature descriptions ────────────────────────────────────

FEATURE_DESCRIPTIONS: dict[str, dict] = {
    "payment_on_time_ratio": {
        "label": "Payment Reliability",
        "positive": (
            "The applicant pays bills on time {value:.0%} of the time, "
            "showing strong financial discipline."
        ),
        "negative": (
            "Only {value:.0%} of bills were paid on time, "
            "suggesting difficulty meeting payment deadlines."
        ),
        "neutral": "No payment timing data available.",
    },
    "longest_on_time_streak": {
        "label": "Consistent Payment Streak",
        "positive": (
            "The applicant had a streak of {raw} consecutive months "
            "of on-time payments."
        ),
        "negative": (
            "The longest on-time payment streak was only {raw} months, "
            "indicating inconsistency."
        ),
        "neutral": "Not enough billing months to measure streaks.",
    },
    "mean_days_late": {
        "label": "Average Lateness",
        "positive": (
            "Bills are paid within {raw:.0f} days of the due date on average, "
            "which is prompt."
        ),
        "negative": (
            "Bills are an average of {raw:.0f} days late, "
            "which may indicate cash flow pressure."
        ),
        "neutral": "No payment timing data available.",
    },
    "payment_consistency": {
        "label": "Consumption Stability",
        "positive": (
            "Utility bill amounts are stable month-to-month, "
            "suggesting consistent household usage."
        ),
        "negative": (
            "Utility bill amounts fluctuate significantly, "
            "which may indicate irregular living arrangements."
        ),
        "neutral": "Not enough bills to assess consistency.",
    },
    "academic_signal": {
        "label": "Academic Performance",
        "positive": (
            "Academic record shows {value:.0%} performance (normalised), "
            "demonstrating commitment to education."
        ),
        "negative": (
            "Academic performance is at {value:.0%} (normalised), "
            "which is below average."
        ),
        "neutral": "No academic records available.",
    },
    "household_burden": {
        "label": "Household Financial Pressure",
        "positive": (
            "Household appears to have manageable financial obligations "
            "relative to income."
        ),
        "negative": (
            "Household has high financial pressure from dependants "
            "or utility costs relative to income."
        ),
        "neutral": "Insufficient data to assess household burden.",
    },
    "income_confidence": {
        "label": "Income Verification",
        "positive": (
            "Income sources are well-documented or verified, "
            "giving high confidence in declared amounts."
        ),
        "negative": (
            "Income is primarily self-declared with limited supporting "
            "evidence."
        ),
        "neutral": "No income signals recorded.",
    },
    "total_income_normalised": {
        "label": "Declared Income Level",
        "positive": (
            "Total declared monthly income of PKR {raw:,.0f} is "
            "above the reference threshold."
        ),
        "negative": (
            "Total declared monthly income of PKR {raw:,.0f} is "
            "below the reference threshold."
        ),
        "neutral": "No income data available.",
    },
}


def _direction_from_value(value: float) -> str:
    """Classify a normalised feature value as positive/negative/neutral."""
    if value >= 0.6:
        return "positive"
    elif value <= 0.4:
        return "negative"
    return "neutral"


def _build_explanation(
    feature_name: str, value: float, raw_value: float | None = None
) -> str:
    """Build a plain-language explanation for one feature."""
    desc = FEATURE_DESCRIPTIONS.get(feature_name)
    if desc is None:
        return f"Feature '{feature_name}' has a value of {value:.3f}."

    direction = _direction_from_value(value)
    template = desc[direction]

    try:
        return template.format(value=value, raw=raw_value if raw_value is not None else value)
    except (KeyError, ValueError):
        return f"{desc['label']}: {value:.3f}."


# ── SHAP-based explanations ────────────────────────────────────────────────


def explain_model_prediction(
    feature_set: FeatureSet,
    feature_array: np.ndarray,
    explainer,
    feature_names: list[str],
) -> list[dict]:
    """
    Use SHAP values to explain a model prediction.

    Returns a list of contribution dicts sorted by absolute magnitude.
    """
    if explainer is None:
        # Fall back to rule-based explanation style.
        return explain_rule_based([], feature_set)

    try:
        shap_values = explainer.shap_values(feature_array)
        # shap_values may be a list (for classification) or array (regression).
        if isinstance(shap_values, list):
            shap_values = shap_values[0]

        contributions = []
        for i, name in enumerate(feature_names):
            norm_val = feature_set.features.get(name)
            # Use pre-normalisation raw value for display templates.
            raw_display = feature_set.raw_values.get(name, norm_val)
            shap_val = float(shap_values[0][i])

            direction = "positive" if shap_val > 0.01 else (
                "negative" if shap_val < -0.01 else "neutral"
            )

            desc = FEATURE_DESCRIPTIONS.get(name, {})
            label = desc.get("label", name)

            if norm_val is not None:
                explanation = _build_explanation(name, norm_val, raw_display)
            elif direction == "neutral":
                explanation = desc.get("neutral", f"No data for {label}.")
            else:
                explanation = f"{label} is missing, which reduced the score."

            contributions.append({
                "feature": name,
                "label": label,
                "contribution": round(shap_val * 100, 2),
                "direction": direction,
                "explanation": explanation,
                "raw_value": round(raw_display, 3) if raw_display is not None else None,
                "no_data": norm_val is None,
            })

        # Sort by absolute contribution, descending.
        contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)
        return contributions

    except Exception:
        # If SHAP fails, fall back gracefully.
        return explain_rule_based([], feature_set)


# ── Rule-based explanations ────────────────────────────────────────────────


def explain_rule_based(
    raw_contributions: list[dict],
    feature_set: FeatureSet,
) -> list[dict]:
    """
    Build explanations from the rule-based weighted contributions.

    Present features get real contributions with raw display values.
    Missing features are included separately with ``no_data: true`` so the
    interface can show them in a distinct section rather than pretending
    they contributed zero.
    """
    explanations: list[dict] = []

    # First, add contributions for features that ARE present.
    for contrib in raw_contributions:
        name = contrib["feature"]
        norm_value = contrib["raw_value"]  # Normalised 0-1 value.
        desc = FEATURE_DESCRIPTIONS.get(name, {})
        label = desc.get("label", name)

        # Use pre-normalisation raw value for display templates (e.g. PKR amounts).
        raw_display = feature_set.raw_values.get(name, norm_value)

        direction = _direction_from_value(norm_value)
        explanation = _build_explanation(name, norm_value, raw_display)

        explanations.append({
            "feature": name,
            "label": label,
            "contribution": round(contrib["weighted_contribution"] * 100, 2),
            "direction": direction,
            "explanation": explanation,
            "raw_value": round(raw_display, 3) if raw_display is not None else round(norm_value, 3),
            "no_data": False,
        })

    # Then, add features that are MISSING — tagged so the UI can separate them.
    for name in FEATURE_DESCRIPTIONS:
        if feature_set.features.get(name) is None:
            desc = FEATURE_DESCRIPTIONS[name]
            explanations.append({
                "feature": name,
                "label": desc["label"],
                "contribution": 0.0,
                "direction": "neutral",
                "explanation": desc["neutral"],
                "raw_value": None,
                "no_data": True,
            })

    # Sort: present features first (by contribution), then missing ones.
    explanations.sort(
        key=lambda e: (e.get("no_data", False), -abs(e["contribution"]))
    )

    return explanations
