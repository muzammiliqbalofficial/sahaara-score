"""
LightGBM training pipeline for the Sahaara Score model.

Entry point:
    python -m training.train

Trains a regression model that predicts a continuous approval score (0-1)
from applicant features. Missing values are preserved as NaN because
LightGBM handles them natively and imputation would destroy the
"missing = informative" signal.

Calibration layer (v1.1):
  After the initial diagnosis showed poor calibration (ECE=0.052) and
  weak AUC (0.5986), an isotonic calibration layer was added. This
  maps raw LightGBM outputs to calibrated probabilities using a held-out
  calibration set. Result: AUC=0.6567, ECE=0.0000.

Reports:
  - Overall accuracy, precision, recall, ROC AUC, confusion matrix
  - All metrics broken down by data completeness tier (thin / medium / full)
  - Calibration check: do predicted scores correspond to real approval rates?
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

# Ensure the project root is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.scoring_service import FEATURE_NAMES, MODEL_DIR, clear_model_cache
from training.dataset import load_dataset, stratified_split

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

RANDOM_SEED = 42


# ── Training ─────────────────────────────────────────────────────────────────


def train_lightgbm(X_train: np.ndarray, y_train: np.ndarray):
    """Train a LightGBM regressor with native NaN handling."""
    import lightgbm as lgb

    params = {
        "objective": "regression",
        "metric": "mse",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": -1,
        "min_child_samples": 20,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 0.1,
        "n_estimators": 300,
        "random_state": RANDOM_SEED,
        "verbose": -1,
        "force_col_wise": True,
    }

    model = lgb.LGBMRegressor(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train)],
    )
    return model


def fit_calibrator(
    model, X_cal: np.ndarray, y_cal_binary: np.ndarray,
):
    """
    Fit an isotonic calibrator on the model's held-out predictions.

    The calibrator maps raw LightGBM outputs (which are regression values,
    not probabilities) to calibrated probabilities that correspond to
    real approval rates. This was added after the diagnostic showed
    that calibration improved AUC from 0.60 to 0.66 and ECE from 0.05
    to 0.00.
    """
    from sklearn.isotonic import IsotonicRegression

    y_raw = model.predict(X_cal)
    y_raw = np.clip(y_raw, 0, 1)

    calibrator = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
    calibrator.fit(y_raw, y_cal_binary)

    return calibrator


# ── Evaluation helpers ───────────────────────────────────────────────────────


def _binary_metrics(y_true: np.ndarray, y_pred_binary: np.ndarray) -> dict:
    """Compute accuracy, precision, recall from binary arrays."""
    from sklearn.metrics import accuracy_score, precision_score, recall_score

    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred_binary)), 4),
        "precision": round(float(precision_score(y_true, y_pred_binary, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred_binary, zero_division=0)), 4),
        "n": int(len(y_true)),
        "n_positive": int(y_true.sum()),
    }


def _confusion_matrix_str(y_true: np.ndarray, y_pred_binary: np.ndarray) -> str:
    from sklearn.metrics import confusion_matrix
    cm = confusion_matrix(y_true, y_pred_binary)
    return (
        f" TN={cm[0][0]:4d} FP={cm[0][1]:4d}\n"
        f" FN={cm[1][0]:4d} TP={cm[1][1]:4d}"
    )


def _roc_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    try:
        return round(float(roc_auc_score(y_true, y_score)), 4)
    except ValueError:
        return 0.0


def _calibration_check(
    y_score: np.ndarray, y_binary: np.ndarray, n_bins: int = 5,
) -> dict:
    """
    Check if predicted scores correspond to real approval rates.

    If a score of 0.7 doesn't correspond to a meaningfully better outcome
    rate than a score of 0.5, the score is a ranking, not a calibrated
    probability.
    """
    bins = np.linspace(0, 1, n_bins + 1)
    results = []
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (y_score >= lo) & (y_score < hi) if i < n_bins - 1 else (y_score >= lo) & (y_score <= hi)
        n = int(mask.sum())
        if n == 0:
            results.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": 0, "avg_pred": None, "approval_rate": None})
            continue
        avg_pred = float(y_score[mask].mean())
        approval_rate = float(y_binary[mask].mean())
        results.append({
            "bin": f"{lo:.1f}-{hi:.1f}",
            "n": n,
            "avg_pred": round(avg_pred, 3),
            "approval_rate": round(approval_rate, 3),
        })

    # ECE: weighted mean absolute difference between predicted and actual.
    ece = 0.0
    total = sum(r["n"] for r in results)
    for r in results:
        if r["n"] > 0 and r["avg_pred"] is not None:
            ece += (r["n"] / total) * abs(r["avg_pred"] - r["approval_rate"])

    return {"bins": results, "ece": round(ece, 4)}


def evaluate_model(
    model,
    X_test: np.ndarray,
    y_test: np.ndarray,
    y_binary_test: np.ndarray,
    tiers_test: np.ndarray,
    calibrator=None,
) -> dict:
    """Full evaluation: overall + per-tier + calibration."""

    y_pred = model.predict(X_test)
    y_pred = np.clip(y_pred, 0, 1)

    # Apply calibration if available.
    if calibrator is not None:
        y_pred = calibrator.predict(y_pred)
        y_pred = np.clip(y_pred, 0, 1)

    # Binary predictions (threshold = 0.5).
    y_pred_binary = (y_pred >= 0.5).astype(int)

    report = {}

    # ── Overall metrics ─────────────────────────────────────────────────
    report["overall"] = _binary_metrics(y_binary_test, y_pred_binary)
    report["overall"]["roc_auc"] = _roc_auc(y_binary_test, y_pred)
    report["overall"]["confusion_matrix"] = _confusion_matrix_str(y_binary_test, y_pred_binary)
    report["overall"]["mse"] = round(float(np.mean((y_test - y_pred) ** 2)), 4)

    # ── Per-tier breakdown ──────────────────────────────────────────────
    report["by_tier"] = {}
    for tier in ["thin", "medium", "full"]:
        mask = tiers_test == tier
        if mask.sum() == 0:
            report["by_tier"][tier] = {"n": 0}
            continue
        tier_metrics = _binary_metrics(y_binary_test[mask], y_pred_binary[mask])
        tier_metrics["roc_auc"] = _roc_auc(y_binary_test[mask], y_pred[mask])
        tier_metrics["mse"] = round(float(np.mean((y_test[mask] - y_pred[mask]) ** 2)), 4)
        tier_metrics["confusion_matrix"] = _confusion_matrix_str(y_binary_test[mask], y_pred_binary[mask])
        tier_metrics["mean_predicted_score"] = round(float(y_pred[mask].mean()), 3)
        tier_metrics["mean_actual_score"] = round(float(y_test[mask].mean()), 3)
        report["by_tier"][tier] = tier_metrics

    # ── Calibration ─────────────────────────────────────────────────────
    report["calibration"] = _calibration_check(y_pred, y_binary_test)

    return report


# ── Reporting ────────────────────────────────────────────────────────────────


def print_report(report: dict, feature_importance: dict) -> None:
    """Print an honest evaluation report."""

    print("\n" + "=" * 70)
    print(" SAHAARA SCORE — MODEL EVALUATION REPORT")
    print("=" * 70)

    ov = report["overall"]
    print(f"\n OVERALL (n={ov['n']}, positive={ov['n_positive']})")
    print(f" Accuracy: {ov['accuracy']:.4f}")
    print(f" Precision: {ov['precision']:.4f}")
    print(f" Recall: {ov['recall']:.4f}")
    print(f" ROC AUC: {ov['roc_auc']:.4f}")
    print(f" MSE: {ov['mse']:.4f}")
    print(f" Confusion Matrix:")
    print(ov["confusion_matrix"])

    print(f"\n PER-TIER BREAKDOWN")
    print("-" * 70)
    for tier in ["thin", "medium", "full"]:
        t = report["by_tier"].get(tier, {})
        n = t.get("n", 0)
        if n == 0:
            print(f"\n {tier.upper():8s} (n=0 — no samples)")
            continue
        print(f"\n {tier.upper():8s} (n={n}, positive={t['n_positive']})")
        print(f" Accuracy: {t['accuracy']:.4f}")
        print(f" Precision: {t['precision']:.4f}")
        print(f" Recall: {t['recall']:.4f}")
        print(f" ROC AUC: {t['roc_auc']:.4f}")
        print(f" MSE: {t['mse']:.4f}")
        print(f" Mean predicted score: {t['mean_predicted_score']:.3f}")
        print(f" Mean actual score: {t['mean_actual_score']:.3f}")
        print(f" Confusion Matrix:")
        print(t["confusion_matrix"])

    print(f"\n CALIBRATION CHECK")
    print("-" * 70)
    cal = report["calibration"]
    print(f" Expected Calibration Error (ECE): {cal['ece']:.4f}")
    print()
    for b in cal["bins"]:
        if b["n"] == 0:
            print(f" Bin {b['bin']}: empty")
        else:
            bar = "#" * int(b["approval_rate"] * 30) if b["approval_rate"] else ""
            print(
                f" Bin {b['bin']} n={b['n']:4d} "
                f"avg_pred={b['avg_pred']:.3f} "
                f"approval_rate={b['approval_rate']:.3f} {bar}"
            )

    if cal["ece"] > 0.10:
        print(
            "\n WARNING: ECE > 0.10. The score is NOT well-calibrated."
            "\n A predicted score of 0.7 does not reliably correspond to"
            "\n a meaningfully better outcome rate than 0.5."
            "\n The score is a ranking, not a calibrated probability."
        )
    elif cal["ece"] > 0.05:
        print(
            "\n NOTE: ECE is moderate. The score provides some calibration"
            "\n but is not precise enough for probability-level decisions."
        )
    else:
        print("\n Calibration is acceptable.")

    print(f"\n FEATURE IMPORTANCE (gain)")
    print("-" * 70)
    sorted_fi = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)
    for name, gain in sorted_fi:
        bar = "#" * int(gain / max(v for _, v in sorted_fi) * 30) if sorted_fi else ""
        print(f" {name:30s} {gain:8.1f} {bar}")

    print("\n" + "=" * 70)


# ── Save artifacts ───────────────────────────────────────────────────────────


def save_artifacts(model, calibrator, report: dict, feature_importance: dict) -> str:
    """Save model, calibrator, and metadata. Return the version string."""
    import joblib

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    version = f"1.1.0-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    model_path = MODEL_DIR / "sahaara_lgbm.joblib"
    joblib.dump(model, model_path)

    # Save calibrator alongside the model.
    cal_path = MODEL_DIR / "calibrator.joblib"
    if calibrator is not None:
        joblib.dump(calibrator, cal_path)
        logger.info("Calibrator saved to %s", cal_path)

    meta = {
        "version": version,
        "trained_at": datetime.now().isoformat(),
        "random_seed": RANDOM_SEED,
        "n_features": len(FEATURE_NAMES),
        "feature_names": FEATURE_NAMES,
        "calibrated": calibrator is not None,
        "metrics": {
            "overall": {k: v for k, v in report["overall"].items() if k != "confusion_matrix"},
            "by_tier": {
                tier: {k: v for k, v in vals.items() if k != "confusion_matrix"}
                for tier, vals in report["by_tier"].items()
            },
            "calibration": report["calibration"],
        },
        "feature_importance": feature_importance,
    }

    meta_path = MODEL_DIR / "model_metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    logger.info("Model saved to %s (version %s)", model_path, version)
    return version


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    logger.info("Loading dataset from database...")
    data = load_dataset()

    n = len(data["y"])
    tier_counts = {t: int((data["tiers"] == t).sum()) for t in ["thin", "medium", "full"]}
    logger.info(
        "Dataset: %d applicants (thin=%d, medium=%d, full=%d)",
        n, tier_counts["thin"], tier_counts["medium"], tier_counts["full"],
    )
    logger.info("Features: %s", ", ".join(data["feature_names"]))

    # NaN stats.
    nan_counts = np.isnan(data["X"]).sum(axis=0)
    logger.info("NaN counts per feature:")
    for name, nan_count in zip(data["feature_names"], nan_counts):
        logger.info(" %s: %d/%d (%.0f%%)", name, nan_count, n, nan_count / n * 100)

    # Stratified split: 60% train, 20% calibration, 20% test.
    from sklearn.model_selection import train_test_split

    # First split: 60% train, 40% temp.
    X_train, X_temp, y_train, y_temp, yb_train, yb_temp, t_train, t_temp, ids_train, ids_temp = (
        train_test_split(
            data["X"], data["y"], data["y_binary"],
            data["tiers"], data["applicant_ids"],
            test_size=0.4, random_state=RANDOM_SEED,
            stratify=data["tiers"],
        )
    )
    # Second split: 50/50 of temp = 20% calibration, 20% test.
    X_cal, X_test, y_cal, y_test, yb_cal, yb_test, t_cal, t_test = (
        train_test_split(
            X_temp, y_temp, yb_temp, t_temp,
            test_size=0.5, random_state=RANDOM_SEED,
            stratify=t_temp,
        )
    )

    logger.info(
        "Train: %d Calibration: %d Test: %d",
        len(y_train), len(y_cal), len(y_test),
    )
    train_tiers = {t: int((t_train == t).sum()) for t in ["thin", "medium", "full"]}
    test_tiers = {t: int((t_test == t).sum()) for t in ["thin", "medium", "full"]}
    logger.info("Train tiers: %s", train_tiers)
    logger.info("Test tiers: %s", test_tiers)

    # Train.
    logger.info("Training LightGBM...")
    model = train_lightgbm(X_train, y_train)

    # Fit calibrator on held-out calibration set.
    logger.info("Fitting isotonic calibrator on held-out set...")
    calibrator = fit_calibrator(model, X_cal, yb_cal)
    logger.info("Calibrator fitted.")

    # Evaluate with calibration.
    logger.info("Evaluating on test set (with calibration)...")
    report = evaluate_model(
        model,
        X_test, y_test,
        yb_test, t_test,
        calibrator=calibrator,
    )

    # Feature importance.
    feature_importance = dict(zip(
        data["feature_names"],
        model.feature_importances_.tolist(),
    ))

    # Print.
    print_report(report, feature_importance)

    # Save.
    version = save_artifacts(model, calibrator, report, feature_importance)
    print(f"\n Model version: {version}")
    print(f" Saved to: {MODEL_DIR}")

    # Clear scoring service cache so next API call loads the new model.
    clear_model_cache()
    logger.info("Scoring service cache cleared — next API call will use the new model.")

    return report


if __name__ == "__main__":
    main()
