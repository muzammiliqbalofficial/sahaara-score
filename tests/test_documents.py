"""
Document parser tests — service unit tests plus API tests for the endpoints.

No network and no database: the DashScope key is empty in tests so every
parse uses the deterministic mock, and the API tests hit only the
parse-only endpoints (the bundle is exercised without an applicant_id,
which skips all persistence).
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.routers.documents import _get_parser
from app.services.document_parser_service import DocumentParserService
from app.utils.enums import (
    IncomeSourceType,
    QualificationLevel,
    ResultScale,
    UtilityType,
)

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body" * 100
PDF_BYTES = b"%PDF-1.4 fake pdf body" + b"0" * 200


@pytest.fixture
def parser() -> DocumentParserService:
    """Parser with no API key — guaranteed mock mode."""
    return DocumentParserService(api_key="")


@pytest.fixture
def client() -> TestClient:
    """API client with the DB and parser dependencies overridden.

    Keeps tests hermetic: no Neon connection, and parsing stays in mock
    mode even if a real DASHSCOPE_API_KEY is present in .env.
    """

    def _fake_db():
        db = MagicMock()
        db.get.return_value = None  # applicant lookups find nothing
        yield db

    def _mock_parser() -> DocumentParserService:
        return DocumentParserService(api_key="")

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[_get_parser] = _mock_parser
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ── Service: mock determinism ───────────────────────────────────────────────


class TestMockDeterminism:
    def test_same_file_parses_identically(self, parser):
        """The mock is seeded by file bytes — identical input, identical output."""
        first = parser.parse_utility_bill(JPEG_BYTES, "bill.jpg", "image/jpeg")
        second = parser.parse_utility_bill(JPEG_BYTES, "bill.jpg", "image/jpeg")
        assert first.model_dump(exclude={"parsed_at"}) == (
            second.model_dump(exclude={"parsed_at"})
        )

    def test_different_files_parse_differently(self, parser):
        a = parser.parse_utility_bill(b"file-a", "bill.jpg", "image/jpeg")
        b = parser.parse_utility_bill(b"file-b" * 3, "bill.jpg", "image/jpeg")
        assert (a.amount_billed, a.units_consumed) != (
            b.amount_billed, b.units_consumed
        )

    def test_mode_is_mock_without_key(self, parser):
        result = parser.parse_academic_record(JPEG_BYTES, "marksheet.jpg", "image/jpeg")
        assert result.mode == "mock"
        assert parser.live is False


# ── Service: filename sniffing ──────────────────────────────────────────────


class TestFilenameSniffing:
    @pytest.mark.parametrize(
        ("filename", "expected_provider", "expected_type"),
        [
            ("kelectric_bill.jpg", "K-Electric", UtilityType.ELECTRICITY),
            ("LESCO_March.png", "LESCO", UtilityType.ELECTRICITY),
            ("sngpl_gas_bill.pdf", "SNGPL", UtilityType.GAS),
            ("kwsb_water.jpg", "KWSB", UtilityType.WATER),
        ],
    )
    def test_provider_sniffed_from_filename(
        self, parser, filename, expected_provider, expected_type,
    ):
        result = parser.parse_utility_bill(JPEG_BYTES, filename, "image/jpeg")
        assert result.provider == expected_provider
        assert result.utility_type == expected_type

    def test_matric_sniffed_from_filename(self, parser):
        result = parser.parse_academic_record(
            JPEG_BYTES, "matric_result.jpg", "image/jpeg",
        )
        assert result.qualification_level == QualificationLevel.MATRIC
        # Board results use the percentage scale.
        assert result.result_scale == ResultScale.PERCENTAGE
        assert result.result_value is not None and 0 <= result.result_value <= 100

    def test_bachelors_sniffed_from_filename(self, parser):
        result = parser.parse_academic_record(
            JPEG_BYTES, "bachelors_transcript.jpg", "image/jpeg",
        )
        assert result.qualification_level == QualificationLevel.BACHELORS
        assert result.result_scale == ResultScale.GPA

    def test_remittance_sniffed_from_filename(self, parser):
        result = parser.parse_income_slip(
            JPEG_BYTES, "remittance_receipt.jpg", "image/jpeg",
        )
        assert result.source_type == IncomeSourceType.REMITTANCE

    def test_freelance_sniffed_from_filename(self, parser):
        result = parser.parse_income_slip(
            JPEG_BYTES, "upwork_statement.jpg", "image/jpeg",
        )
        assert result.source_type == IncomeSourceType.FREELANCE


# ── Service: value coercion ─────────────────────────────────────────────────


class TestCoercion:
    def test_currency_strings(self, parser):
        assert parser._coerce_amount("Rs. 12,345") == 12345.0
        assert parser._coerce_amount("PKR 7,800/-") == 7800.0
        assert parser._coerce_amount("₨ 500") == 500.0
        assert parser._coerce_amount(12345) == 12345.0
        assert parser._coerce_amount("not a number") is None
        assert parser._coerce_amount(None) is None

    def test_month_formats(self, parser):
        assert parser._coerce_month("2024-06") == date(2024, 6, 1)
        assert parser._coerce_month("2024-06-15") == date(2024, 6, 1)
        assert parser._coerce_month("06/2024") == date(2024, 6, 1)
        assert parser._coerce_month("June 2024") == date(2024, 6, 1)
        assert parser._coerce_month("garbage") is None

    def test_year_bounds(self, parser):
        assert parser._coerce_year(2023) == 2023
        assert parser._coerce_year("2023") == 2023
        assert parser._coerce_year(1899) is None
        assert parser._coerce_year(2100) is None

    def test_utility_type_aliases(self, parser):
        assert parser._coerce_utility_type("Electricity") == UtilityType.ELECTRICITY
        assert parser._coerce_utility_type("gas supply") == UtilityType.GAS

    def test_qualification_aliases(self, parser):
        assert parser._coerce_qualification("FSc") == QualificationLevel.INTERMEDIATE
        assert parser._coerce_qualification("Bachelors of Science") == (
            QualificationLevel.BACHELORS
        )

    def test_result_scale_inference_from_magnitude(self, parser):
        # 78 can only be a percentage; 3.4 must be GPA.
        assert parser._coerce_result_scale(None, 78) == ResultScale.PERCENTAGE
        assert parser._coerce_result_scale(None, 3.4) == ResultScale.GPA
        assert parser._coerce_result_scale("CGPA", None) == ResultScale.GPA


# ── Service: upload validation ──────────────────────────────────────────────


class TestValidation:
    def test_empty_file_rejected(self, parser):
        with pytest.raises(ValueError, match="empty"):
            parser.parse_utility_bill(b"", "bill.jpg", "image/jpeg")

    def test_oversized_file_rejected(self, parser):
        huge = b"x" * (DocumentParserService.MAX_FILE_BYTES + 1)
        with pytest.raises(ValueError, match="limit"):
            parser.parse_utility_bill(huge, "bill.jpg", "image/jpeg")

    def test_bad_content_type_rejected(self, parser):
        with pytest.raises(ValueError, match="Unsupported"):
            parser.parse_utility_bill(b"stuff", "bill.txt", "text/plain")

    def test_pdf_allowed(self, parser):
        result = parser.parse_utility_bill(PDF_BYTES, "bill.pdf", "application/pdf")
        assert result.mode == "mock"


# ── Service: Qwen payload handling (no network — direct method tests) ───────


class TestQwenResponseParsing:
    def test_json_block_plain(self, parser):
        text = '{"provider": "LESCO", "amount_billed": 4500}'
        assert parser._parse_json_block(text) == {
            "provider": "LESCO", "amount_billed": 4500,
        }

    def test_json_block_fenced(self, parser):
        text = 'Here you go:\n```json\n{"provider": "LESCO"}\n```\nDone.'
        assert parser._parse_json_block(text) == {"provider": "LESCO"}

    def test_json_block_with_stray_prose(self, parser):
        text = 'The bill shows {"arrears": 1200} per the attached.'
        assert parser._parse_json_block(text) == {"arrears": 1200}

    def test_json_block_garbage(self, parser):
        assert parser._parse_json_block("no json here") is None
        assert parser._parse_json_block("") is None

    def test_dashscope_text_extraction(self, parser):
        # Multimodal content format (list of parts).
        body = {"output": {"choices": [{"message": {"content": [
            {"text": '{"amount_billed": 9000}'},
        ]}}]}}
        assert parser._extract_text(body) == '{"amount_billed": 9000}'

        # Plain string content format.
        body_str = {"output": {"choices": [
            {"message": {"content": '{"arrears": 0}'}},
        ]}}
        assert parser._extract_text(body_str) == '{"arrears": 0}'

    def test_live_key_falls_back_to_mock_on_api_failure(self, monkeypatch):
        """With a key present, a failed API call still falls back to mock."""
        def _fail_post(*args, **kwargs):
            raise httpx.ConnectError("simulated network failure")

        monkeypatch.setattr(
            "app.services.document_parser_service.httpx.post", _fail_post,
        )
        live_parser = DocumentParserService(api_key="sk-test-key")
        assert live_parser.live is True
        result = live_parser.parse_utility_bill(JPEG_BYTES, "bill.jpg", "image/jpeg")
        assert result.mode == "mock"
        assert result.amount_billed is not None

    def test_successful_qwen_call_reports_qwen_mode(self, monkeypatch):
        """A mocked DashScope response flows through as mode='qwen_vl'."""

        def _fake_response(text: str) -> MagicMock:
            response = MagicMock()
            response.raise_for_status.return_value = None
            response.json.return_value = {
                "output": {"choices": [{"message": {
                    "content": [{"text": text}],
                }}]},
            }
            return response

        monkeypatch.setattr(
            "app.services.document_parser_service.httpx.post",
            lambda *a, **k: _fake_response(
                '{"provider": "LESCO", "utility_type": "electricity", '
                '"units_consumed": "412", "amount_billed": "Rs. 18,450", '
                '"arrears": "1,200/-", "billing_month": "2026-05", '
                '"consumer_name": null}'
            ),
        )
        live_parser = DocumentParserService(api_key="sk-test-key")
        result = live_parser.parse_utility_bill(
            JPEG_BYTES, "lesco_bill.jpg", "image/jpeg",
        )
        assert result.mode == "qwen_vl"
        assert result.provider == "LESCO"
        assert result.utility_type == UtilityType.ELECTRICITY
        # Currency-formatted strings coerce to clean numbers.
        assert result.units_consumed == 412.0
        assert result.amount_billed == 18450.0
        assert result.arrears == 1200.0
        assert result.billing_month == date(2026, 5, 1)

    def test_extract_returns_none_when_not_live(self, parser):
        assert parser._extract(JPEG_BYTES, "image/jpeg", "prompt") is None


# ── API: single-document endpoints ──────────────────────────────────────────


class TestUtilityBillEndpoint:
    def test_parses_jpeg_upload(self, client):
        response = client.post(
            "/api/v1/documents/parse-utility-bill",
            files={"file": ("kelectric_bill.jpg", JPEG_BYTES, "image/jpeg")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "mock"
        assert body["source_filename"] == "kelectric_bill.jpg"
        assert body["provider"] == "K-Electric"
        assert body["utility_type"] == "electricity"
        assert isinstance(body["amount_billed"], (int, float))
        assert body["units_consumed"] is not None
        assert body["arrears"] is not None

    def test_rejects_unsupported_type(self, client):
        response = client.post(
            "/api/v1/documents/parse-utility-bill",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 400
        assert "Unsupported" in response.json()["detail"]

    def test_rejects_empty_file(self, client):
        response = client.post(
            "/api/v1/documents/parse-utility-bill",
            files={"file": ("empty.jpg", b"", "image/jpeg")},
        )
        assert response.status_code == 400


class TestAcademicRecordEndpoint:
    def test_parses_marksheet_upload(self, client):
        response = client.post(
            "/api/v1/documents/parse-academic-record",
            files={"file": ("matric_marksheet.jpg", JPEG_BYTES, "image/jpeg")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "mock"
        assert body["qualification_level"] == "matric"
        assert body["result_scale"] == "percentage"
        assert 0 <= body["result_value"] <= 100
        assert body["year"] is not None
        assert body["institution"] is not None


class TestIncomeSlipEndpoint:
    def test_parses_affidavit_upload(self, client):
        response = client.post(
            "/api/v1/documents/parse-income-slip",
            files={"file": ("income_affidavit.jpg", JPEG_BYTES, "image/jpeg")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "mock"
        assert body["monthly_income"] > 0
        assert body["source_type"] in {
            "freelance", "informal_work", "remittance", "agriculture",
        }
        assert body["dependants"] >= 0
        # A supplied document is documented evidence by definition.
        assert body["evidence_type"] == "documented"


# ── API: bundle endpoint (no applicant_id — no persistence) ─────────────────


class TestBundleEndpoint:
    def test_bundle_without_applicant_parses_all(self, client):
        response = client.post(
            "/api/v1/documents/parse-bundle",
            files=[
                ("utility_bills", ("lesco_bill.jpg", JPEG_BYTES, "image/jpeg")),
                ("academic_records", ("matric.jpg", JPEG_BYTES, "image/jpeg")),
                ("income_slips", ("affidavit.jpg", JPEG_BYTES, "image/jpeg")),
            ],
            data={"run_scoring": "false"},
        )
        assert response.status_code == 201
        body = response.json()
        assert len(body["utility_bills"]) == 1
        assert len(body["academic_records"]) == 1
        assert len(body["income_slips"]) == 1
        assert body["applicant_id"] is None
        assert body["created_utility_records"] == []
        assert body["assessment"] is None
        assert body["mode_summary"] == {"mock": 3}

    def test_bundle_requires_at_least_one_file(self, client):
        response = client.post(
            "/api/v1/documents/parse-bundle", data={"run_scoring": "false"},
        )
        assert response.status_code == 400
        assert "at least one document" in response.json()["detail"]

    def test_bundle_bad_file_fails_cleanly(self, client):
        response = client.post(
            "/api/v1/documents/parse-bundle",
            files=[("utility_bills", ("bill.txt", b"text", "text/plain"))],
        )
        assert response.status_code == 400

    def test_bundle_unknown_applicant_404s(self, client):
        response = client.post(
            "/api/v1/documents/parse-bundle",
            files=[
                ("utility_bills", ("bill.jpg", JPEG_BYTES, "image/jpeg")),
            ],
            data={"applicant_id": str(uuid.uuid4()), "run_scoring": "false"},
        )
        assert response.status_code == 404
