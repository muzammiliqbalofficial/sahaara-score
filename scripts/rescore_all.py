"""
Delete every assessment and re-score all applicants from scratch.

Use after a scoring-engine change (new features, new model, new anomaly
rules) so existing assessments carry the new output. Reviewer decisions
are cascade-deleted with their assessments — run this only when losing
the decision history is acceptable.

Usage:
    .venv\\Scripts\\python.exe -m scripts.rescore_all
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete

from app.database import _get_session_factory
from app.models.applicant import Applicant
from app.models.assessment import Assessment
from app.services.scoring_service import score_applicant


def main():
    SessionLocal = _get_session_factory()
    db = SessionLocal()

    try:
        # Cascade removes reviewer decisions attached to old assessments.
        deleted = db.execute(delete(Assessment))
        db.commit()
        print(f"Deleted {deleted.rowcount} old assessments.")

        applicants = db.query(Applicant).all()
        print(f"Re-scoring {len(applicants)} applicants...")

        risk_levels = Counter()
        actions = Counter()
        for i, applicant in enumerate(applicants):
            result = score_applicant(applicant)
            db.add(Assessment(
                applicant_id=applicant.id,
                score=result["score"],
                band=result["band"],
                feature_contributions=result["feature_contributions"],
                model_version=result["model_version"],
                is_rule_based=result["is_rule_based"],
                confidence_level=result["confidence_level"],
                signal_categories_count=result["signal_categories_count"],
                non_null_feature_count=result["non_null_feature_count"],
                anomaly_risk_score=result["anomaly_risk_score"],
                anomaly_risk_level=result["anomaly_risk_level"],
                anomaly_audit_required=result["anomaly_audit_required"],
                anomaly_flags_count=result["anomaly_flags_count"],
                anomaly_report=result["anomaly_report"],
            ))
            risk_levels[result["anomaly_risk_level"].value] += 1
            actions[
                result["anomaly_report"]["recommendation"]["action_type"]
            ] += 1

            if (i + 1) % 50 == 0:
                db.flush()
                print(f" Scored {i + 1}/{len(applicants)}...")

        db.commit()

        print(f"\nDone. Re-scored {len(applicants)} applicants.")
        print("\nAnomaly risk-level distribution:")
        for level, count in sorted(risk_levels.items()):
            print(f" {level:20s} {count:4d}")
        print("\nRecommended actions:")
        for action, count in sorted(actions.items()):
            print(f" {action:24s} {count:4d}")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
