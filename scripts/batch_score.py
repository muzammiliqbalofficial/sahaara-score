"""
Batch-score all applicants that don't have an assessment yet.

Usage:
    .venv\\Scripts\\python.exe -m scripts.batch_score
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import _get_session_factory
from app.models.applicant import Applicant
from app.models.assessment import Assessment
from app.services.scoring_service import score_applicant


def main():
    SessionLocal = _get_session_factory()
    db = SessionLocal()

    try:
        # Find applicants without assessments.
        scored_ids = {
            row[0]
            for row in db.query(Assessment.applicant_id).distinct().all()
        }
        all_applicants = db.query(Applicant).all()
        unscored = [a for a in all_applicants if a.id not in scored_ids]

        print(f"Total applicants: {len(all_applicants)}")
        print(f"Already scored:   {len(scored_ids)}")
        print(f"To score:         {len(unscored)}")
        print()

        for i, applicant in enumerate(unscored):
            result = score_applicant(applicant)
            assessment = Assessment(
                applicant_id=applicant.id,
                score=result["score"],
                band=result["band"],
                feature_contributions=result["feature_contributions"],
                model_version=result["model_version"],
                is_rule_based=result["is_rule_based"],
                confidence_level=result["confidence_level"],
                signal_categories_count=result["signal_categories_count"],
                non_null_feature_count=result["non_null_feature_count"],
            )
            db.add(assessment)

            if (i + 1) % 50 == 0:
                db.flush()
                print(f"  Scored {i + 1}/{len(unscored)}...")

        db.commit()
        print(f"\nDone. Scored {len(unscored)} applicants.")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
