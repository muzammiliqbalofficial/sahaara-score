"""
Document parsing endpoints — multimodal extraction via Alibaba Cloud Qwen-VL.

Field workers photograph an applicant's paper documents (utility bills,
marksheets, income affidavits) and upload them here.  Qwen-VL extracts the
structured values that feed the scoring engine, eliminating manual data
entry at intake.

Endpoints:
  POST /parse-utility-bill    — one bill → units, amount, provider, arrears
  POST /parse-academic-record — one marksheet → result, institution, year
  POST /parse-income-slip     — one affidavit/slip → income, source, dependants
  POST /parse-bundle          — many documents → parsed values, and when an
                                applicant_id is given, real records plus an
                                optional fresh assessment.

Every parse falls back to deterministic mock extraction when the DashScope
key is absent or the API call fails, so the flow is demo-safe offline.
"""

import uuid
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.academic_record import AcademicRecord
from app.models.assessment import Assessment
from app.models.income_signal import IncomeSignal
from app.models.utility_record import UtilityRecord
from app.repositories.applicant_repo import ApplicantRepository
from app.schemas.assessment import AssessmentRead
from app.schemas.documents import (
    AcademicRecordParseResult,
    BundleParseResult,
    IncomeSlipParseResult,
    UtilityBillParseResult,
)
from app.services.document_parser_service import DocumentParserService
from app.services.scoring_service import score_applicant
from app.utils.enums import EvidenceType

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_BUNDLE_FILES = 20


def _get_parser() -> DocumentParserService:
    """FastAPI dependency — one service instance per request."""
    return DocumentParserService()


async def _read_upload(file: UploadFile) -> tuple[bytes, str, str | None]:
    """Read an upload into memory with its filename and content type."""
    content = await file.read()
    return content, file.filename or "upload", file.content_type


# ── Single-document parsing (no persistence — review before attaching) ───────


@router.post("/parse-utility-bill", response_model=UtilityBillParseResult)
async def parse_utility_bill(
    file: UploadFile = File(..., description="Bill photo or PDF"),
    parser: DocumentParserService = Depends(_get_parser),
):
    """
    Parse a Pakistani utility bill (K-Electric, LESCO, SNGPL, KWSB, …) into
    structured fields: provider, units consumed, billed amount, and arrears.
    """
    content, filename, content_type = await _read_upload(file)
    try:
        return parser.parse_utility_bill(content, filename, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/parse-academic-record", response_model=AcademicRecordParseResult)
async def parse_academic_record(
    file: UploadFile = File(..., description="Marksheet or transcript photo/PDF"),
    parser: DocumentParserService = Depends(_get_parser),
):
    """
    Parse an academic marksheet (BISE board, university transcript, technical
    diploma) into: institution, qualification level, result value + scale, year.
    """
    content, filename, content_type = await _read_upload(file)
    try:
        return parser.parse_academic_record(content, filename, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/parse-income-slip", response_model=IncomeSlipParseResult)
async def parse_income_slip(
    file: UploadFile = File(..., description="Income affidavit or salary slip photo/PDF"),
    parser: DocumentParserService = Depends(_get_parser),
):
    """
    Parse an income document (salary slip, stamp-paper affidavit, remittance
    receipt) into: monthly income, source type, dependants, employer/source.
    """
    content, filename, content_type = await _read_upload(file)
    try:
        return parser.parse_income_slip(content, filename, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Bundle parsing (auto-populates applicant data) ──────────────────────────


@router.post("/parse-bundle", response_model=BundleParseResult, status_code=201)
async def parse_bundle(
    utility_bills: list[UploadFile] | None = File(
        None, description="Utility bill photos/PDFs",
    ),
    academic_records: list[UploadFile] | None = File(
        None, description="Marksheet/transcript photos/PDFs",
    ),
    income_slips: list[UploadFile] | None = File(
        None, description="Income affidavit/slip photos/PDFs",
    ),
    applicant_id: uuid.UUID | None = Form(
        None, description="Attach parsed records to this applicant.",
    ),
    run_scoring: bool = Form(
        True, description="Score the applicant after records are created.",
    ),
    parser: DocumentParserService = Depends(_get_parser),
    db: Session = Depends(get_db),
):
    """
    Parse several documents in one call and auto-populate applicant data.

    Each file is parsed independently (any file can fall back to mock mode
    without failing the others).  When ``applicant_id`` is supplied the
    parsed values are written as real utility/academic/income records and,
    unless ``run_scoring=false``, a fresh assessment runs immediately —
    the one-shot intake path: three photographs in, one score out.
    """
    total_files = (
        len(utility_bills or []) + len(academic_records or []) + len(income_slips or [])
    )
    if total_files == 0:
        raise HTTPException(status_code=400, detail="Upload at least one document.")
    if total_files > MAX_BUNDLE_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Bundle limited to {MAX_BUNDLE_FILES} files per request.",
        )

    # ── Parse every document ────────────────────────────────────────────
    parsed_bills: list[UtilityBillParseResult] = []
    parsed_academics: list[AcademicRecordParseResult] = []
    parsed_incomes: list[IncomeSlipParseResult] = []
    failures: list[str] = []

    async def _parse_all(
        files: list[UploadFile] | None, parse_fn,
    ) -> list:
        results = []
        for upload in files or []:
            content, filename, content_type = await _read_upload(upload)
            try:
                results.append(parse_fn(content, filename, content_type))
            except ValueError as exc:
                failures.append(f"{filename}: {exc}")
        return results

    parsed_bills = await _parse_all(utility_bills, parser.parse_utility_bill)
    parsed_academics = await _parse_all(
        academic_records, parser.parse_academic_record,
    )
    parsed_incomes = await _parse_all(income_slips, parser.parse_income_slip)

    if not (parsed_bills or parsed_academics or parsed_incomes):
        raise HTTPException(
            status_code=400,
            detail=f"No document could be parsed. Issues: {'; '.join(failures)}",
        )

    result = BundleParseResult(
        utility_bills=parsed_bills,
        academic_records=parsed_academics,
        income_slips=parsed_incomes,
        applicant_id=applicant_id,
    )
    mode_counts = Counter(
        [p.mode for p in parsed_bills]
        + [p.mode for p in parsed_academics]
        + [p.mode for p in parsed_incomes]
    )
    result.mode_summary = dict(mode_counts)

    # ── Optionally persist as records + score ───────────────────────────
    if applicant_id is not None:
        repo = ApplicantRepository(db)
        applicant = repo.get_by_id(applicant_id)
        if not applicant:
            raise HTTPException(status_code=404, detail="Applicant not found")

        for bill in parsed_bills:
            record = UtilityRecord(
                applicant_id=applicant_id,
                utility_type=bill.utility_type,
                billing_month=bill.billing_month,
                amount_billed=bill.amount_billed,
            )
            result.created_utility_records.append(repo.add_utility_record(record))

        for academic in parsed_academics:
            record = AcademicRecord(
                applicant_id=applicant_id,
                institution=academic.institution,
                qualification_level=academic.qualification_level,
                result_value=academic.result_value,
                result_scale=academic.result_scale,
                year=academic.year,
            )
            result.created_academic_records.append(repo.add_academic_record(record))

        for slip in parsed_incomes:
            signal = IncomeSignal(
                applicant_id=applicant_id,
                source_type=slip.source_type,
                declared_monthly_amount=slip.monthly_income,
                evidence_type=slip.evidence_type or EvidenceType.DOCUMENTED,
            )
            result.created_income_signals.append(repo.add_income_signal(signal))

        if run_scoring and (
            result.created_utility_records
            or result.created_academic_records
            or result.created_income_signals
        ):
            db.refresh(applicant)  # pick up the records just created
            score = score_applicant(applicant)
            assessment = Assessment(
                applicant_id=applicant_id,
                score=score["score"],
                band=score["band"],
                feature_contributions=score["feature_contributions"],
                model_version=score["model_version"],
                is_rule_based=score["is_rule_based"],
                confidence_level=score["confidence_level"],
                signal_categories_count=score["signal_categories_count"],
                non_null_feature_count=score["non_null_feature_count"],
                anomaly_risk_score=score["anomaly_risk_score"],
                anomaly_risk_level=score["anomaly_risk_level"],
                anomaly_audit_required=score["anomaly_audit_required"],
                anomaly_flags_count=score["anomaly_flags_count"],
                anomaly_report=score["anomaly_report"],
            )
            db.add(assessment)
            db.commit()
            db.refresh(assessment)
            result.assessment = AssessmentRead(
                id=assessment.id,
                applicant_id=assessment.applicant_id,
                score=assessment.score,
                band=assessment.band,
                model_version=assessment.model_version,
                is_rule_based=assessment.is_rule_based,
                confidence_level=assessment.confidence_level,
                signal_categories_count=assessment.signal_categories_count,
                non_null_feature_count=assessment.non_null_feature_count,
                anomaly_risk_score=assessment.anomaly_risk_score,
                anomaly_risk_level=assessment.anomaly_risk_level,
                anomaly_audit_required=assessment.anomaly_audit_required,
                anomaly_flags_count=assessment.anomaly_flags_count,
                top_flags=assessment.top_flags,
                created_at=assessment.created_at,
            )

    return result
