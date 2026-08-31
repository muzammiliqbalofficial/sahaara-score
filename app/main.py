"""
Sahaara Score — FastAPI application entry point.

Run with:
    uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import applicants_router, assessments_router
from app.routers.review import router as review_router

settings = get_settings()

app = FastAPI(
    title="Sahaara Score",
    description=(
        "Alternative credit scoring platform for financially invisible "
        "Pakistanis.  Assesses eligibility using utility bills, academic "
        "records, and income signals instead of bank statements."
    ),
    version=settings.model_version,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (allow frontend dev server) ───────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ────────────────────────────────────────────────────────

app.include_router(applicants_router, prefix="/api/v1")
app.include_router(assessments_router, prefix="/api/v1")
app.include_router(review_router, prefix="/api/v1")


# ── Health check ────────────────────────────────────────────────────────────


@app.get("/health", tags=["health"])
def health_check():
    return {
        "status": "healthy",
        "version": settings.model_version,
        "env": settings.app_env,
    }
