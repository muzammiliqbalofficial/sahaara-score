"""
Feature engineering — transforms raw applicant records into numerical features.

Design philosophy
─────────────────
1. Every function returns ``None`` when data is absent, NEVER a default like
    zero. This lets the scoring layer distinguish "no data" from "bad signal".
2. Features are normalised to a 0-1 range where possible so that the ML model
    and the rule-based path interpret them identically.
3. The ``build_feature_vector`` function returns a ``FeatureSet`` dataclass
    containing both the feature dict and metadata about which signal categories
    were present. This metadata drives the data-sufficiency confidence level.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from app.utils.enums import EvidenceType, ResultScale


# ── Feature set container ──────────────────────────────────────────────────


@dataclass
class FeatureSet:
    """All engineered features for one applicant, plus data-coverage metadata."""

    features: dict[str, float | None] = field(default_factory=dict)

    # Pre-normalisation raw values (e.g. PKR amounts, raw months, raw days).
    # Used by the explanation layer to display human-readable values instead
    # of normalised 0-1 numbers.
    raw_values: dict[str, float | None] = field(default_factory=dict)

    # How many distinct signal categories (utility, academic, income) are
    # present with at least one usable record.
    categories_present: list[str] = field(default_factory=list)

    # Maximum number of months of utility data available.
    months_of_utility_data: int = 0

    # Total non-null feature count (used for model-vs-rule routing).
    non_null_count: int = 0

    @property
    def data_sufficiency_summary(self) -> str:
        cats = ", ".join(self.categories_present) if self.categories_present else "none"
        return (
            f"{self.non_null_count} features computed from "
            f"{len(self.categories_present)} signal categories ({cats}); "
            f"{self.months_of_utility_data} months of utility data."
        )


# ── Payment reliability ─────────────────────────────────────────────────────


def payment_on_time_ratio(utility_records: list) -> float | None:
    """
    Fraction of utility bills paid on time (days_late == 0 or days_late is 0).

    Returns None if no records have a non-null days_late.
    """
    records_with_timing = [
        r for r in utility_records if r.days_late is not None
    ]
    if not records_with_timing:
        return None

    on_time = sum(1 for r in records_with_timing if r.days_late == 0)
    return on_time / len(records_with_timing)


def longest_on_time_streak(utility_records: list) -> float | None:
    """
    Longest consecutive run of on-time payments, sorted by billing month.

    Returns None if fewer than 2 records have timing data.
    """
    records_with_timing = sorted(
        [r for r in utility_records if r.days_late is not None and r.billing_month is not None],
        key=lambda r: r.billing_month,
    )
    if len(records_with_timing) < 2:
        return None

    max_streak = 0
    current_streak = 0
    for r in records_with_timing:
        if r.days_late == 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    return float(max_streak)


def mean_days_late(utility_records: list) -> float | None:
    """
    Average days late across all bills with known timing.

    Returns None if no records have days_late.
    """
    vals = [r.days_late for r in utility_records if r.days_late is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


# ── Payment consistency ─────────────────────────────────────────────────────


def billed_amount_cv(utility_records: list) -> float | None:
    """
    Coefficient of variation of billed amounts.

    Low CV → stable consumption → positive signal.
    High CV → erratic consumption → weaker signal.

    Returns None if fewer than 2 records have amount_billed.
    """
    vals = [r.amount_billed for r in utility_records if r.amount_billed is not None and r.amount_billed > 0]
    if len(vals) < 2:
        return None

    mean = sum(vals) / len(vals)
    if mean == 0:
        return None

    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
    std_dev = math.sqrt(variance)
    cv = std_dev / mean

    # Normalise to 0-1: CV of 0 → 1.0, CV of 1+ → ~0.
    # Using an exponential decay: normalised = exp(-2 * cv)
    return math.exp(-2 * cv)


# ── Academic signal ────────────────────────────────────────────────────────

# Mapping from division codes to normalised scores.
_DIVISION_MAP: dict[float, float] = {
    1.0: 0.85, # First Division ≈ A
    2.0: 0.65, # Second Division ≈ B
    3.0: 0.45, # Third Division ≈ C
}

# Qualification level weights (higher degrees get slightly more weight).
_QUALIFICATION_WEIGHT: dict[str, float] = {
    "matric": 0.8,
    "intermediate": 0.85,
    "diploma": 0.85,
    "bachelors": 0.95,
    "masters": 1.0,
}


def _normalise_result(value: float, scale: str | None) -> float | None:
    """Convert a raw academic result to a 0-1 normalised score."""
    if value is None or scale is None:
        return None

    if scale == ResultScale.PERCENTAGE or scale == "percentage":
        return min(value / 100.0, 1.0)
    elif scale == ResultScale.GPA or scale == "gpa":
        return min(value / 4.0, 1.0)
    elif scale == ResultScale.DIVISION or scale == "division":
        return _DIVISION_MAP.get(float(value))
    return None


def academic_signal(academic_records: list, current_year: int = 2026) -> float | None:
    """
    Best normalised academic result, weighted by qualification level and
    recency.

    Recency weight: 1.0 for current year, decaying by 0.05 per year.
    Minimum recency weight: 0.7 (so old results still count).

    Returns None if no records have both result_value and result_scale.
    """
    if not academic_records:
        return None

    scored: list[float] = []
    for rec in academic_records:
        normalised = _normalise_result(rec.result_value, rec.result_scale)
        if normalised is None:
            continue

        # Qualification weight
        qual_key = rec.qualification_level.value if hasattr(rec.qualification_level, "value") else str(rec.qualification_level)
        qual_weight = _QUALIFICATION_WEIGHT.get(qual_key, 0.85)

        # Recency weight
        if rec.year is not None:
            years_ago = max(0, current_year - rec.year)
            recency_weight = max(0.7, 1.0 - 0.05 * years_ago)
        else:
            recency_weight = 0.75 # Unknown year → slight penalty

        weighted_score = normalised * qual_weight * recency_weight
        scored.append(weighted_score)

    if not scored:
        return None

    # Return the best weighted score (applicants can submit multiple results).
    return max(scored)


# ── Household burden ────────────────────────────────────────────────────────


def household_burden(
    dependants: int | None,
    income_signals: list,
    utility_records: list,
) -> float | None:
    """
    Composite burden indicator (0-1, higher = less burden).

    Two sub-signals averaged when both are available:
      1. Inverse dependants-per-income-source ratio
      2. Utility-spend-to-income ratio (inverted)

    Returns None if neither sub-signal can be computed.
    """
    sub_signals: list[float] = []

    # Sub-signal 1: dependants per income source
    n_income = len(income_signals)
    if dependants is not None and n_income > 0:
        ratio = dependants / n_income
        # Normalise: 0 dependants per earner → 1.0, 5+ → ~0.
        sub_signals.append(math.exp(-0.4 * ratio))

    # Sub-signal 2: utility spend relative to income
    total_income = sum(
        s.declared_monthly_amount
        for s in income_signals
        if s.declared_monthly_amount is not None
    )
    utility_amounts = [
        r.amount_billed
        for r in utility_records
        if r.amount_billed is not None
    ]
    if total_income > 0 and utility_amounts:
        avg_utility = sum(utility_amounts) / len(utility_amounts)
        # Monthly utility as fraction of monthly income.
        spend_ratio = avg_utility / total_income
        # Normalise: 0% → 1.0, 50%+ → ~0.
        sub_signals.append(max(0, 1.0 - 2 * spend_ratio))

    if not sub_signals:
        return None

    return sum(sub_signals) / len(sub_signals)


# ── Data sufficiency ────────────────────────────────────────────────────────


def data_sufficiency(
    utility_records: list,
    academic_records: list,
    income_signals: list,
) -> tuple[list[str], int]:
    """
    Determine which signal categories have at least one usable record
    and how many months of utility data are available.

    Returns (categories_present, months_of_data).
    """
    categories: list[str] = []

    # Utility: need at least one record with amount_billed or days_late.
    usable_utility = [
        r for r in utility_records
        if r.amount_billed is not None or r.days_late is not None
    ]
    if usable_utility:
        categories.append("utility")

    # Academic: need at least one record with result_value and result_scale.
    usable_academic = [
        r for r in academic_records
        if r.result_value is not None and r.result_scale is not None
    ]
    if usable_academic:
        categories.append("academic")

    # Income: need at least one signal with a declared amount.
    usable_income = [
        s for s in income_signals
        if s.declared_monthly_amount is not None
    ]
    if usable_income:
        categories.append("income")

    # Months of utility data.
    months = len({
        r.billing_month
        for r in usable_utility
        if r.billing_month is not None
    })

    return categories, months


def income_confidence(income_signals: list) -> float | None:
    """
    Weighted confidence of declared income.

    Evidence weights: verified=1.0, documented=0.7, self_declared=0.4.
    The confidence_flag adds a 0.1 bonus (capped at 1.0).

    Returns None if no income signals exist.
    """
    if not income_signals:
        return None

    _evidence_weights = {
        EvidenceType.VERIFIED: 1.0,
        EvidenceType.DOCUMENTED: 0.7,
        EvidenceType.SELF_DECLARED: 0.4,
    }

    weighted_amounts: list[float] = []
    total_amount = 0.0

    for s in income_signals:
        if s.declared_monthly_amount is None:
            continue

        ev_key = s.evidence_type
        weight = _evidence_weights.get(ev_key, 0.4)

        if s.confidence_flag:
            weight = min(1.0, weight + 0.1)

        weighted_amounts.append(s.declared_monthly_amount * weight)
        total_amount += s.declared_monthly_amount

    if total_amount == 0:
        return None

    return sum(weighted_amounts) / total_amount


def total_declared_income(income_signals: list) -> float | None:
    """Sum of all declared monthly income amounts. None if no signals."""
    if not income_signals:
        return None
    total = sum(
        s.declared_monthly_amount
        for s in income_signals
        if s.declared_monthly_amount is not None
    )
    return total if total > 0 else None


# ── Master feature builder ─────────────────────────────────────────────────


def build_feature_vector(applicant) -> FeatureSet:
    """
    Compute all features from an applicant ORM object (with loaded relations).

    Returns a FeatureSet with features dict and data-coverage metadata.
    """
    utility_records = applicant.utility_records or []
    academic_records = applicant.academic_records or []
    income_signals = applicant.income_signals or []

    # Compute individual features.
    features: dict[str, float | None] = {
        "payment_on_time_ratio": payment_on_time_ratio(utility_records),
        "longest_on_time_streak": longest_on_time_streak(utility_records),
        "mean_days_late": mean_days_late(utility_records),
        "payment_consistency": billed_amount_cv(utility_records),
        "academic_signal": academic_signal(academic_records),
        "household_burden": household_burden(
            applicant.dependants, income_signals, utility_records
        ),
        "income_confidence": income_confidence(income_signals),
    }

    # Data sufficiency metadata.
    categories, months = data_sufficiency(
        utility_records, academic_records, income_signals
    )

    # Store raw (pre-normalisation) values for the explanation layer.
    # These let the UI display real PKR amounts, raw months, etc.
    raw_values: dict[str, float | None] = {
        "longest_on_time_streak": features.get("longest_on_time_streak"),
        "mean_days_late": features.get("mean_days_late"),
    }

    # Normalise longest streak to 0-1 (cap at 12 months).
    streak = features["longest_on_time_streak"]
    if streak is not None:
        features["longest_on_time_streak"] = min(streak / 12.0, 1.0)

    # Normalise mean_days_late to 0-1 (inverted: 0 days late → 1.0).
    mdl = features["mean_days_late"]
    if mdl is not None:
        features["mean_days_late"] = max(0.0, 1.0 - (mdl / 30.0))

    # Normalise total income to 0-1 using a log scale.
    # PKR 10,000 → ~0.23, PKR 50,000 → ~0.56, PKR 200,000 → ~0.86.
    total_inc = total_declared_income(income_signals)
    if total_inc is not None and total_inc > 0:
        features["total_income_normalised"] = min(
            math.log10(total_inc) / 5.3, 1.0
        )
        raw_values["total_income_normalised"] = total_inc # Raw PKR amount.
    else:
        features["total_income_normalised"] = None
        raw_values["total_income_normalised"] = None

    # Count non-null features.
    non_null = sum(1 for v in features.values() if v is not None)

    return FeatureSet(
        features=features,
        raw_values=raw_values,
        categories_present=categories,
        months_of_utility_data=months,
        non_null_count=non_null,
    )
