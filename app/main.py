"""
Sahaara Score — FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload --port 8000

In production (Docker / Cloud Run):
    uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import get_engine
from app.routers import applicants_router, assessments_router
from app.routers.documents import router as documents_router
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
    docs_url="/docs" if settings.app_debug else None,
    redoc_url="/redoc" if settings.app_debug else None,
)

# ── CORS (origins from CORS_ORIGINS env var, localhost defaults for dev) ───

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ────────────────────────────────────────────────────────

app.include_router(applicants_router, prefix="/api/v1")
app.include_router(assessments_router, prefix="/api/v1")
app.include_router(review_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")


# ── Health check ────────────────────────────────────────────────────────────


@app.get("/health", tags=["health"])
def health_check():
    """Lightweight health endpoint for uptime checks.

    Confirms the database is reachable, not just that the process is alive.
    Cloud Run and Neon both scale to zero independently, so a static 200
    would miss the case where the database connection has gone stale.
    """
    db_status = "healthy"
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {type(e).__name__}"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": db_status,
        "version": settings.model_version,
        "env": settings.app_env,
    }
