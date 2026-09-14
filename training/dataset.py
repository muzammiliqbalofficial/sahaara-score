"""
Dataset builder — pulls applicants from the database and runs them through
the existing feature engineering layer so training and inference use
*identical* feature code. No duplicated feature logic.

Missing values are preserved as NaN — LightGBM handles them natively, and
imputation would destroy the "missing = informative" signal that is central
to this domain.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import _get_session_factory
from app.models.applicant import Applicant
from app.services.feature_engineering import build_feature_vector
from app.services.scoring_service import FEATURE_NAMES

logger = logging.getLogger(__name__)


def _completeness_tier(non_null_count: int) -> str:
    """Classify an applicant into a data completeness tier."""
    if non_null_count <= 3:
        return "thin"
    elif non_null_count <= 5:
        return "medium"
    return "full"


def load_dataset() -> dict:
    """
    Load all labelled applicants from the database, compute features via
    the shared feature engineering pipeline, and return a structured dict.

    Returns
    -------
    dict with keys:
        X : np.ndarray — (n_samples, n_features) matrix, NaN for missing
        y : np.ndarray — continuous approval_score (0-1)
        y_binary : np.ndarray — reviewer_approved (0/1)
        feature_names : list[str]
        tiers : np.ndarray — "thin" / "medium" / "full" per sample
        applicant_ids : np.ndarray
    """
    SessionLocal = _get_session_factory()
    db: Session = SessionLocal()

    try:
        stmt = (
            select(Applicant)
            .where(Applicant.approval_score.isnot(None))
            .options(
                selectinload(Applicant.utility_records),
                selectinload(Applicant.academic_records),
                selectinload(Applicant.income_signals),
            )
        )
        applicants = list(db.execute(stmt).scalars().all())
    finally:
        db.close()

    if not applicants:
        raise RuntimeError(
            "No labelled applicants found. Run `python -m scripts.seed` first."
        )

    logger.info("Loaded %d labelled applicants from database.", len(applicants))

    X_rows: list[list[float]] = []
    y_vals: list[float] = []
    y_binary_vals: list[int] = []
    tiers: list[str] = []
    ids: list[str] = []

    for applicant in applicants:
        feature_set = build_feature_vector(applicant)
        row = [
            feature_set.features.get(name) if feature_set.features.get(name) is not None else np.nan
            for name in FEATURE_NAMES
        ]
        X_rows.append(row)
        y_vals.append(applicant.approval_score)
        y_binary_vals.append(1 if applicant.reviewer_approved else 0)
        tiers.append(_completeness_tier(feature_set.non_null_count))
        ids.append(str(applicant.id))

    return {
        "X": np.array(X_rows, dtype=np.float64),
        "y": np.array(y_vals, dtype=np.float64),
        "y_binary": np.array(y_binary_vals, dtype=np.int32),
        "feature_names": list(FEATURE_NAMES),
        "tiers": np.array(tiers),
        "applicant_ids": np.array(ids),
    }


def stratified_split(
    X: np.ndarray,
    y: np.ndarray,
    y_binary: np.ndarray,
    tiers: np.ndarray,
    applicant_ids: np.ndarray,
    test_size: float = 0.2,
    random_state: int = 42,
) -> dict:
    """
    Stratified train/test split that preserves the distribution of data
    completeness tiers. Thin-file applicants appear in both sets.
    """
    from sklearn.model_selection import train_test_split

    indices = np.arange(len(X))
    train_idx, test_idx = train_test_split(
        indices,
        test_size=test_size,
        stratify=tiers,
        random_state=random_state,
    )

    return {
        "X_train": X[train_idx],
        "X_test": X[test_idx],
        "y_train": y[train_idx],
        "y_test": y[test_idx],
        "y_binary_train": y_binary[train_idx],
        "y_binary_test": y_binary[test_idx],
        "tiers_train": tiers[train_idx],
        "tiers_test": tiers[test_idx],
        "ids_train": applicant_ids[train_idx],
        "ids_test": applicant_ids[test_idx],
    }
