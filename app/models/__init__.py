"""
ORM models package.

Import every model here so Alembic's ``target_metadata`` sees them all
when auto-generating migrations.
"""

from app.models.applicant import Applicant
from app.models.utility_record import UtilityRecord
from app.models.academic_record import AcademicRecord
from app.models.income_signal import IncomeSignal
from app.models.assessment import Assessment
from app.models.reviewer_decision import ReviewerDecision

__all__ = [
    "Applicant",
    "UtilityRecord",
    "AcademicRecord",
    "IncomeSignal",
    "Assessment",
    "ReviewerDecision",
]
