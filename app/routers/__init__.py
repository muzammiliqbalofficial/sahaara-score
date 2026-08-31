"""Router package."""

from app.routers.applicants import router as applicants_router
from app.routers.assessments import router as assessments_router

__all__ = ["applicants_router", "assessments_router"]
