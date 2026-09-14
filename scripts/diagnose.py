"""
Model diagnostic — honest investigation into why the model underperforms.

This script does NOT tune until the metrics look better. It diagnoses first,
reports what it finds, and makes one honest attempt at improvement.

Investigations:
  1. Mutual information: does the signal exist in the data at all?
  2. Sample size: does performance scale with more data?
  3. Label noise: did we over-noise the labels?
  4. Class weighting: does addressing class imbalance help precision?
  5. Calibration: do predicted scores correspond to real approval rates?

If the model still does not beat the rule-based baseline after this, the
conclusion is clear and we stop.

Usage:
    .venv\\Scripts\\python.exe -m scripts.diagnose
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.seed import generate_applicants, generate_labels, _LABEL_WEIGHTS
from app.services.feature_engineering import build_feature_vector
from app.services.scoring_service import FEATURE_NAMES

RANDOM_SEED = 42


# ── Data generation ────────────────────────────────────────────────────────


def _build_features_and_labels(applicants):
    """Build X, y, y_binary, tiers arrays from in-memory applicants."""
    X_rows, y_rows, y_bin_rows, tier_rows = [], [], [], []

    for a in applicants:
        fs = build_feature_vector(a)
        row = [
            fs.features.get(name) if fs.features.get(name) is not None else np.nan
            for name in FEATURE_NAMES
        ]
        non_null = sum(1 for v in row if not np.isnan(v))
        if non_null <= 3:
            tier = "thin"
        elif non_null <= 5:
            tier = "medium"
        else:
            tier = "full"

        X_rows.append(row)
        y_rows.append(a.approval_score if a.approval_score is not None else 0.5)
        y_bin_rows.append(1 if a.reviewer_approved else 0)
        tier_rows.append(tier)

    return (
        np.array(X_rows),
        np.array(y_rows),
        np.array(y_bin_rows),
        np.array(tier_rows),
    )


def _generate_dataset(n: int, noise_flip: float = 0.08, contrarian: float = 0.05):
    """Generate n applicants with configurable noise, return features + labels."""
    # Reset seed for reproducibility within each call.
    import random
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    applicants = generate_applicants(n)

    # Override noise params on generate_labels by monkey-patching the noise.
    # We need to generate labels with custom noise, so we do it inline.
    _generate_labels_custom(applicants, noise_flip, contrarian)

    X, y, y_bin, tiers = _build_features_and_labels(applicants)
    return {"X": X, "y": y, "y_binary": y_bin, "tiers": tiers, "n": n}


def _generate_labels_custom(applicants, noise_flip: float, contrarian: float):
    """Same as seed.generate_labels but with configurable noise levels."""
    import math

    for applicant in applicants:
        feature_set = build_feature_vector(applicant)
        features = feature_set.features

        from scripts.seed import _FEATURE_MEANS
        latent = 0.0
        for name, weight in _LABEL_WEIGHTS.items():
            val = features.get(name)
            latent += weight * (val if val is not None else _FEATURE_MEANS.get(name, 0.5))

        noise = np.random.normal(0, 0.10)
        latent = max(0.0, min(1.0, latent + noise))

        approval_prob = 1.0 / (1.0 + math.exp(-8.0 * (latent - 0.48)))
        approved = bool(np.random.random() < approval_prob)

        if np.random.random() < noise_flip:
            approved = not approved

        non_null = feature_set.non_null_count
        if non_null >= 5 and np.random.random() < contrarian:
            approved = not approved

        score_noise = np.random.normal(0, 0.06)
        continuous = max(0.05, min(0.95, latent * 0.85 + score_noise + 0.08))

        applicant.reviewer_approved = approved
        applicant.approval_score = round(continuous, 4)


# ── Mutual information ─────────────────────────────────────────────────────


def mutual_information_analysis(data):
    """Report mutual information between each feature and the binary label."""
    from sklearn.feature_selection import mutual_info_classif

    X, y_bin = data["X"], data["y_binary"]

    # Replace NaN with median for MI computation (MI can't handle NaN).
    X_filled = np.copy(X)
    for col in range(X.shape[1]):
        mask = np.isnan(X[:, col])
        if mask.any():
            median = np.nanmedian(X[:, col])
            X_filled[mask, col] = median

    mi_scores = mutual_info_classif(X_filled, y_bin, random_state=RANDOM_SEED)

    print("\n" + "=" * 70)
    print(" 1. MUTUAL INFORMATION ANALYSIS")
    print(" Does the signal exist in the data at all?")
    print("=" * 70)
    print()
    sorted_features = sorted(
        zip(FEATURE_NAMES, mi_scores), key=lambda x: x[1], reverse=True
    )
    for name, mi in sorted_features:
        bar = "#" * int(mi / max(mi_scores) * 30) if max(mi_scores) > 0 else ""
        print(f" {name:30s} MI={mi:.4f} {bar}")

    avg_mi = np.mean(mi_scores)
    print(f"\n Average MI: {avg_mi:.4f}")
    if avg_mi < 0.01:
        print(" VERDICT: Features carry very little information about the label.")
        print(" The signal may be too weak for any model to learn from.")
    elif avg_mi < 0.05:
        print(" VERDICT: Features carry weak but non-trivial signal.")
        print(" With more data or better features, the model may improve.")
    else:
        print(" VERDICT: Features carry meaningful signal.")
        print(" The model should be able to learn if given enough data.")

    return mi_scores


# ── Training helper ────────────────────────────────────────────────────────


def _train_and_evaluate(data, label: str, class_weight=None, calibrate=False):
    """Train LightGBM on data dict and return metrics."""
    import lightgbm as lgb
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score

    X, y, y_bin, tiers = data["X"], data["y"], data["y_binary"], data["tiers"]

    # Stratified split by tier.
    stratify_labels = tiers
    X_train, X_test, y_train, y_test, yb_train, yb_test, t_train, t_test = (
        train_test_split(
            X, y, y_bin, tiers,
            test_size=0.2, random_state=RANDOM_SEED,
            stratify=stratify_labels,
        )
    )

    params = {
        "objective": "regression",
        "metric": "mse",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": -1,
        "min_child_samples": max(5, len(y_train) // 50),
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 0.1,
        "n_estimators": 300,
        "random_state": RANDOM_SEED,
        "verbose": -1,
        "force_col_wise": True,
    }

    if class_weight == "balanced":
        # Compute sample weights for class balancing.
        n_pos = yb_train.sum()
        n_neg = len(yb_train) - n_pos
        weight_pos = len(yb_train) / (2 * n_pos) if n_pos > 0 else 1.0
        weight_neg = len(yb_train) / (2 * n_neg) if n_neg > 0 else 1.0
        sample_weights = np.where(yb_train == 1, weight_pos, weight_neg)
    else:
        sample_weights = None

    model = lgb.LGBMRegressor(**params)
    model.fit(
        X_train, y_train,
        sample_weight=sample_weights,
    )

    # Predict.
    y_pred = np.clip(model.predict(X_test), 0, 1)
    y_pred_bin = (y_pred >= 0.5).astype(int)

    # Calibration (isotonic).
    calibrator = None
    y_pred_calibrated = y_pred
    if calibrate:
        from sklearn.isotonic import IsotonicRegression
        calibrator = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
        calibrator.fit(y_pred, yb_test)
        y_pred_calibrated = calibrator.predict(y_pred)
        y_pred_bin = (y_pred_calibrated >= 0.5).astype(int)

    # Metrics.
    try:
        auc = roc_auc_score(yb_test, y_pred_calibrated)
    except ValueError:
        auc = 0.0
    acc = accuracy_score(yb_test, y_pred_bin)
    prec = precision_score(yb_test, y_pred_bin, zero_division=0)
    rec = recall_score(yb_test, y_pred_bin, zero_division=0)

    # Per-tier AUC.
    tier_auc = {}
    for tier in ["thin", "medium", "full"]:
        mask = t_test == tier
        if mask.sum() > 10 and len(np.unique(yb_test[mask])) > 1:
            tier_auc[tier] = roc_auc_score(yb_test[mask], y_pred_calibrated[mask])
        else:
            tier_auc[tier] = None

    # Calibration: ECE.
    n_bins = 5
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (y_pred_calibrated >= lo) & (y_pred_calibrated < hi) if i < n_bins - 1 else (y_pred_calibrated >= lo) & (y_pred_calibrated <= hi)
        n = mask.sum()
        if n > 0:
            avg_pred = y_pred_calibrated[mask].mean()
            approval_rate = yb_test[mask].mean()
            ece += (n / len(yb_test)) * abs(avg_pred - approval_rate)

    # Class balance.
    pos_rate = yb_train.mean()

    result = {
        "label": label,
        "n": len(y),
        "n_train": len(y_train),
        "n_test": len(y_test),
        "pos_rate": pos_rate,
        "auc": auc,
        "accuracy": acc,
        "precision": prec,
        "recall": rec,
        "ece": ece,
        "tier_auc": tier_auc,
    }
    return result, model


# ── Reporting ──────────────────────────────────────────────────────────────


def _print_result(r: dict):
    """Print a single result row."""
    print(f"\n {r['label']}")
    print(f" n={r['n']} train={r['n_train']} test={r['n_test']} pos_rate={r['pos_rate']:.2%}")
    print(f" ROC AUC: {r['auc']:.4f}")
    print(f" Accuracy: {r['accuracy']:.4f}")
    print(f" Precision: {r['precision']:.4f}")
    print(f" Recall: {r['recall']:.4f}")
    print(f" ECE: {r['ece']:.4f}")
    tier_auc_str = " ".join(
        f"{t}={v:.4f}" if v is not None else f"{t}=N/A"
        for t, v in r["tier_auc"].items()
    )
    print(f" Tier AUC: {tier_auc_str}")


# ── Main diagnostic flow ──────────────────────────────────────────────────


def main():
    print("=" * 70)
    print(" SAHAARA SCORE — MODEL DIAGNOSTIC")
    print(" Honest investigation into why the model underperforms.")
    print("=" * 70)

    # ── 1. Load current 500-record dataset ─────────────────────────────────
    print("\n Generating 500-record baseline dataset...")
    data_500 = _generate_dataset(500)
    pos_500 = data_500["y_binary"].sum()
    print(f" 500 records: {pos_500} approved, {500 - pos_500} denied ({pos_500/500:.1%} positive)")

    # ── 2. Mutual information analysis ─────────────────────────────────────
    mi_scores = mutual_information_analysis(data_500)

    # ── 3. Sample size scaling ─────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(" 2. SAMPLE SIZE SCALING")
    print(" Does performance improve with more data?")
    print("=" * 70)

    print("\n Training on 500 records...")
    r_500, model_500 = _train_and_evaluate(data_500, "500 records (baseline)")

    print(" Generating 2000 records...")
    data_2000 = _generate_dataset(2000)
    pos_2000 = data_2000["y_binary"].sum()
    print(f" 2000 records: {pos_2000} approved ({pos_2000/2000:.1%} positive)")
    print(" Training on 2000 records...")
    r_2000, model_2000 = _train_and_evaluate(data_2000, "2000 records")

    print(" Generating 5000 records...")
    data_5000 = _generate_dataset(5000)
    pos_5000 = data_5000["y_binary"].sum()
    print(f" 5000 records: {pos_5000} approved ({pos_5000/5000:.1%} positive)")
    print(" Training on 5000 records...")
    r_5000, model_5000 = _train_and_evaluate(data_5000, "5000 records")

    print("\n Sample size scaling results:")
    _print_result(r_500)
    _print_result(r_2000)
    _print_result(r_5000)

    auc_trend = [r_500["auc"], r_2000["auc"], r_5000["auc"]]
    if auc_trend[2] > auc_trend[0] + 0.05:
        print("\n VERDICT: ROC AUC scales with data volume.")
        print(" The ceiling is sample size, not model design.")
        print(" More data would help, but 500 records is too few for 8 features.")
    else:
        print("\n VERDICT: ROC AUC does NOT scale meaningfully with data volume.")
        print(" The ceiling is likely label noise or weak features, not sample size.")

    # ── 4. Noise sensitivity ───────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(" 3. LABEL NOISE SENSITIVITY")
    print(" Is 8% flip + 5% contrarian too much noise?")
    print("=" * 70)

    print("\n Training with current noise (8% flip + 5% contrarian)...")
    r_noisy, _ = _train_and_evaluate(data_500, "Noisy (8% flip + 5% contrarian)")

    print(" Generating low-noise dataset (2% flip + 1% contrarian)...")
    data_low_noise = _generate_dataset(500, noise_flip=0.02, contrarian=0.01)
    print(" Training with low noise...")
    r_low_noise, _ = _train_and_evaluate(data_low_noise, "Low noise (2% flip + 1% contrarian)")

    print(" Generating zero-noise dataset...")
    data_no_noise = _generate_dataset(500, noise_flip=0.0, contrarian=0.0)
    print(" Training with zero noise...")
    r_no_noise, _ = _train_and_evaluate(data_no_noise, "Zero noise")

    print("\n Noise comparison:")
    _print_result(r_noisy)
    _print_result(r_low_noise)
    _print_result(r_no_noise)

    noise_delta = r_no_noise["auc"] - r_noisy["auc"]
    if noise_delta > 0.10:
        print(f"\n VERDICT: Noise destroyed significant signal (delta_AUC={noise_delta:.4f}).")
        print(" 8% flip + 5% contrarian may be more than real reviewer inconsistency.")
        print(" Consider reducing noise to 2-3% flip + 1-2% contrarian.")
    elif noise_delta > 0.03:
        print(f"\n VERDICT: Noise has moderate impact (delta_AUC={noise_delta:.4f}).")
        print(" Noise is a factor but not the primary cause of underperformance.")
    else:
        print(f"\n VERDICT: Noise has minimal impact (delta_AUC={noise_delta:.4f}).")
        print(" The problem lies elsewhere (weak features or model design).")

    # ── 5. Class weighting + calibration ──────────────────────────────────
    print("\n" + "=" * 70)
    print(" 4. ONE HONEST ATTEMPT AT IMPROVEMENT")
    print(" Class weighting + isotonic calibration")
    print("=" * 70)

    print("\n Training with class weighting (balanced)...")
    r_weighted, _ = _train_and_evaluate(data_500, "Class-weighted", class_weight="balanced")

    print(" Training with class weighting + calibration...")
    r_weighted_cal, _ = _train_and_evaluate(
        data_500, "Class-weighted + calibrated",
        class_weight="balanced", calibrate=True,
    )

    print(" Training with calibration only (no class weight)...")
    r_calibrated, _ = _train_and_evaluate(
        data_500, "Calibrated only",
        calibrate=True,
    )

    print("\n Before vs after:")
    _print_result(r_500)
    _print_result(r_weighted)
    _print_result(r_weighted_cal)
    _print_result(r_calibrated)

    # ── 6. Final verdict ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(" 5. FINAL VERDICT")
    print("=" * 70)

    best_improved = max(
        r_weighted["auc"], r_weighted_cal["auc"], r_calibrated["auc"]
    )
    best_label = max(
        [("Class-weighted", r_weighted["auc"]),
         ("Class-weighted + calibrated", r_weighted_cal["auc"]),
         ("Calibrated only", r_calibrated["auc"])],
        key=lambda x: x[1],
    )

    print(f"\n Baseline (500 records): AUC = {r_500['auc']:.4f}")
    print(f" Best improved ({best_label[0]}): AUC = {best_label[1]:.4f}")
    print(f" Best with more data (5000): AUC = {r_5000['auc']:.4f}")

    # Rule-based baseline comparison.
    # We can compute the rule-based AUC by scoring all test applicants with
    # the rule-based scorer and comparing to ground truth.
    from app.services.scoring_service import _score_rule_based
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score

    X_test_5000 = data_5000["X"]
    yb_test_5000 = data_5000["y_binary"]
    tiers_5000 = data_5000["tiers"]

    # Use a subset for rule-based comparison (test split).
    _, X_test_rb, _, yb_test_rb = train_test_split(
        X_test_5000, yb_test_5000, test_size=0.2, random_state=RANDOM_SEED,
    )

    # Compute rule-based scores for these applicants.
    # We need to reconstruct FeatureSets — simpler to just score all 5000
    # and use the rule-based path scores.
    rule_scores = []
    rule_labels = []
    import random
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    all_5000 = generate_applicants(5000)
    _generate_labels_custom(all_5000, 0.08, 0.05)
    for applicant in all_5000:
        fs = build_feature_vector(applicant)
        score, _ = _score_rule_based(fs)
        rule_scores.append(score / 100.0) # normalise to 0-1
        rule_labels.append(1 if applicant.reviewer_approved else 0)

    try:
        rule_auc = roc_auc_score(rule_labels, rule_scores)
    except ValueError:
        rule_auc = 0.0

    print(f" Rule-based baseline AUC: AUC = {rule_auc:.4f}")

    print()
    if best_improved > rule_auc + 0.02:
        print(" CONCLUSION: The improved model BEATS the rule-based baseline.")
        print(" The model path is worth deploying, but with caution.")
    elif r_5000["auc"] > rule_auc + 0.02:
        print(" CONCLUSION: The model with more data BEATS the rule-based baseline,")
        print(" but the 500-record model does not. Scale up data collection.")
    else:
        print(" CONCLUSION: The model does NOT beat the rule-based baseline.")
        print(" We keep the rule-based path as primary and present the model as a")
        print(" supplementary signal. This is the honest finding.")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
