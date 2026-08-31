"""Repository package — data access layer."""

from app.repositories.applicant_repo import ApplicantRepository
from app.repositories.assessment_repo import AssessmentRepository

__all__ = ["ApplicantRepository", "AssessmentRepository"]
