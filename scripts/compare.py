"""
Comparison script — runs both the model-based and rule-based scorers across
the full seeded population and reports where they disagree.

Usage:
    python -m scripts.compare

This tells us whether the model adds anything beyond the hand-weighted rules,
or merely reproduces them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import _get_session_factory
from app.models.applicant import Applicant
from app.services.feature_engineering import build_feature_vector
from app.services.scoring_service import (
    FEATURE_NAMES,
    RULE_WEIGHTS,
    _load_model,
    _score_model_based,
    _score_rule_based,
    _score_to_band,
    clear_model_cache,
)


def main():
    clear_model_cache()

    model = _load_model()
    if model is None:
        print("ERROR: No trained model found.  Run `python -m training` first.")
        sys.exit(1)

    # Load all applicants.
    SessionLocal = _get_session_factory()
    db: Session = SessionLocal()
    try:
        stmt = (
            select(Applicant)
            .options(
                selectinload(Applicant.utility_records),
                selectinload(Applicant.academic_records),
                selectinload(Applicant.income_signals),
            )
        )
        applicants = list(db.execute(stmt).scalars().all())
    finally:
        db.close()

    print(f"Loaded {len(applicants)} applicants.\n")

    # Score each applicant with both paths.
    model_scores: list[float] = []
    rule_scores: list[float] = []
    diffs: list[float] = []
    non_null_counts: list[int] = []
    tiers: list[str] = []

    for applicant in applicants:
        feature_set = build_feature_vector(applicant)
        nn = feature_set.non_null_count
        non_null_counts.append(nn)

        tier = "thin" if nn <= 3 else ("medium" if nn <= 5 else "full")
        tiers.append(tier)

        # Force model-based score for ALL applicants (even thin ones).
        m_score, _ = _score_model_based(feature_set)

        # Force rule-based score for ALL applicants.
        r_score, _ = _score_rule_based(feature_set)

        model_scores.append(m_score)
        rule_scores.append(r_score)
        diffs.append(m_score - r_score)

    model_scores = np.array(model_scores)
    rule_scores = np.array(rule_scores)
    diffs = np.array(diffs)
    non_null_counts = np.array(non_null_counts)
    tiers = np.array(tiers)

    abs_diffs = np.abs(diffs)

    print("=" * 70)
    print("  MODEL vs RULE-BASED COMPARISON")
    print("=" * 70)

    print(f"\n  Population: {len(applicants)} applicants")
    print(f"  Mean model score:  {model_scores.mean():.2f}")
    print(f"  Mean rule score:   {rule_scores.mean():.2f}")
    print(f"  Mean difference:   {diffs.mean():+.2f}  (model - rule)")
    print(f"  Median |diff|:     {np.median(abs_diffs):.2f}")
    print(f"  Max |diff|:        {abs_diffs.max():.2f}")

    # Correlation.
    corr = np.corrcoef(model_scores, rule_scores)[0, 1]
    print(f"  Pearson correlation: {corr:.4f}")

    if corr > 0.95:
        print(
            "\n  VERDICT: The model nearly perfectly reproduces the rules."
            "\n  The model is adding very little beyond the hand-weighted rules."
        )
    elif corr > 0.85:
        print(
            "\n  VERDICT: The model mostly agrees with the rules but adds"
            "\n  some independent signal."
        )
    else:
        print(
            "\n  VERDICT: The model diverges meaningfully from the rules."
            "\n  This suggests the model learned patterns the rules miss."
        )

    # Per-tier breakdown.
    print(f"\n  PER-TIER COMPARISON")
    print("-" * 70)
    for tier in ["thin", "medium", "full"]:
        mask = tiers == tier
        n = int(mask.sum())
        if n == 0:
            continue
        t_model = model_scores[mask]
        t_rule = rule_scores[mask]
        t_diff = diffs[mask]
        t_abs = abs_diffs[mask]
        t_corr = np.corrcoef(t_model, t_rule)[0, 1] if n > 2 else 0.0
        print(f"\n  {tier.upper():8s}  (n={n})")
        print(f"    Mean model: {t_model.mean():.2f}  Mean rule: {t_rule.mean():.2f}")
        print(f"    Mean diff:  {t_diff.mean():+.2f}  Median |diff|: {np.median(t_abs):.2f}")
        print(f"    Correlation: {t_corr:.4f}")

    # Top-10 largest disagreements.
    print(f"\n  TOP 10 LARGEST DISAGREEMENTS")
    print("-" * 70)
    top_idx = np.argsort(abs_diffs)[-10:][::-1]
    for rank, idx in enumerate(top_idx, 1):
        nn = non_null_counts[idx]
        tier = tiers[idx]
        m = model_scores[idx]
        r = rule_scores[idx]
        d = diffs[idx]
        direction = "model higher" if d > 0 else "rule higher"
        print(f"    {rank:2d}.  Model={m:6.2f}  Rule={r:6.2f}  "
              f"Diff={d:+7.2f} ({direction})  "
              f"Tier={tier}  Features={nn}")

    # Band disagreement rate.
    band_disagree = 0
    for m, r in zip(model_scores, rule_scores):
        if _score_to_band(m) != _score_to_band(r):
            band_disagree += 1

    print(f"\n  BAND DISAGREEMENT")
    print("-" * 70)
    print(f"    {band_disagree}/{len(applicants)} "
          f"({band_disagree / len(applicants):.1%}) applicants "
          f"get a different band from the two paths.")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
