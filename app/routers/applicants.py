"""
Applicant endpoints — register, list, and attach records to applicants.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.applicant import Applicant
from app.models.academic_record import AcademicRecord
from app.models.income_signal import IncomeSignal
from app.models.utility_record import UtilityRecord
from app.repositories.applicant_repo import ApplicantRepository
from app.schemas.applicant import ApplicantCreate, ApplicantRead, ApplicantWithRecords
from app.schemas.records import (
    AcademicRecordCreate,
    AcademicRecordRead,
    IncomeSignalCreate,
    IncomeSignalRead,
    UtilityRecordCreate,
    UtilityRecordRead,
)

router = APIRouter(prefix="/applicants", tags=["applicants"])


# ── Applicant CRUD ──────────────────────────────────────────────────────────


@router.post("/", response_model=ApplicantRead, status_code=201)
def create_applicant(
    payload: ApplicantCreate,
    db: Session = Depends(get_db),
):
    """Register a new applicant."""
    repo = ApplicantRepository(db)
    applicant = Applicant(**payload.model_dump())
    return repo.create(applicant)


@router.get("/", response_model=list[ApplicantRead])
def list_applicants(
    offset: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List applicants (paginated)."""
    repo = ApplicantRepository(db)
    return repo.list_all(offset=offset, limit=limit)


@router.get("/{applicant_id}", response_model=ApplicantWithRecords)
def get_applicant(
    applicant_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Get a single applicant with all related records."""
    repo = ApplicantRepository(db)
    applicant = repo.get_by_id(applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Applicant not found")
    return applicant


# ── Child records ───────────────────────────────────────────────────────────


@router.post(
    "/{applicant_id}/utility",
    response_model=UtilityRecordRead,
    status_code=201,
)
def add_utility_record(
    applicant_id: uuid.UUID,
    payload: UtilityRecordCreate,
    db: Session = Depends(get_db),
):
    """Attach a utility bill record to an applicant."""
    repo = ApplicantRepository(db)
    if not repo.get_by_id(applicant_id):
        raise HTTPException(status_code=404, detail="Applicant not found")

    record = UtilityRecord(applicant_id=applicant_id, **payload.model_dump(exclude={"applicant_id"}))
    return repo.add_utility_record(record)


@router.get(
    "/{applicant_id}/utility",
    response_model=list[UtilityRecordRead],
)
def list_utility_records(
    applicant_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List all utility records for an applicant."""
    applicant = db.get(Applicant, applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Applicant not found")
    return applicant.utility_records


@router.post(
    "/{applicant_id}/academic",
    response_model=AcademicRecordRead,
    status_code=201,
)
def add_academic_record(
    applicant_id: uuid.UUID,
    payload: AcademicRecordCreate,
    db: Session = Depends(get_db),
):
    """Attach an academic record to an applicant."""
    repo = ApplicantRepository(db)
    if not repo.get_by_id(applicant_id):
        raise HTTPException(status_code=404, detail="Applicant not found")

    record = AcademicRecord(applicant_id=applicant_id, **payload.model_dump(exclude={"applicant_id"}))
    return repo.add_academic_record(record)


@router.get(
    "/{applicant_id}/academic",
    response_model=list[AcademicRecordRead],
)
def list_academic_records(
    applicant_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List all academic records for an applicant."""
    applicant = db.get(Applicant, applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Applicant not found")
    return applicant.academic_records


@router.post(
    "/{applicant_id}/income",
    response_model=IncomeSignalRead,
    status_code=201,
)
def add_income_signal(
    applicant_id: uuid.UUID,
    payload: IncomeSignalCreate,
    db: Session = Depends(get_db),
):
    """Attach an income signal to an applicant."""
    repo = ApplicantRepository(db)
    if not repo.get_by_id(applicant_id):
        raise HTTPException(status_code=404, detail="Applicant not found")

    signal = IncomeSignal(applicant_id=applicant_id, **payload.model_dump(exclude={"applicant_id"}))
    return repo.add_income_signal(signal)


@router.get(
    "/{applicant_id}/income",
    response_model=list[IncomeSignalRead],
)
def list_income_signals(
    applicant_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List all income signals for an applicant."""
    applicant = db.get(Applicant, applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Applicant not found")
    return applicant.income_signals
