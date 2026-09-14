"""
Document parser service — multimodal extraction via Alibaba Cloud Qwen-VL.

Sends uploaded document images/PDFs to DashScope (Model Studio) with strict
JSON extraction prompts, then coerces the model's output onto the domain
schemas so parsed results map directly onto UtilityRecord / AcademicRecord /
IncomeSignal.

Offline safety: when DASHSCOPE_API_KEY is empty — or the API call fails for
any reason (quota, network, bad scan) — the service falls back to
deterministic mock extraction seeded by the file's own bytes.  The same
file always parses to the same values, so demos and tests never depend on
network availability.  Every result reports its ``mode`` ('qwen_vl' or
'mock') so the caller can show provenance in the UI.

Pakistani document knowledge baked in:
  - Electricity distribution companies (K-Electric, LESCO, IESCO, FESCO,
    GEPCO, HESCO, PESCO, SEPCO, QESCO, TESCO).
  - Gas utilities (SNGPL, SSGC) and water boards (KWSB, WASA, CDA).
  - Grading scales: BISE percentages (matric/intermediate), HEC GPA
    (bachelors/masters), and legacy division results.
  - Informal income sources: freelance, daily-wage work, remittances,
    agriculture.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import re
from datetime import date, datetime, timezone

import httpx

from app.config import get_settings
from app.schemas.documents import (
    AcademicRecordParseResult,
    IncomeSlipParseResult,
    UtilityBillParseResult,
)
from app.utils.enums import (
    EvidenceType,
    IncomeSourceType,
    QualificationLevel,
    ResultScale,
    UtilityType,
)

logger = logging.getLogger(__name__)

# ── Provider knowledge ────────────────────────────────────────────────────────

_ELECTRICITY_PROVIDERS = [
    "K-Electric", "LESCO", "IESCO", "FESCO", "GEPCO",
    "HESCO", "PESCO", "SEPCO", "QESCO", "TESCO",
]
_GAS_PROVIDERS = ["SNGPL", "SSGC"]
_WATER_PROVIDERS = ["KWSB", "WASA Lahore", "CDA Water"]

_BOARD_INSTITUTIONS = [
    "BISE Lahore", "BISE Karachi", "BISE Rawalpindi", "BISE Multan",
    "BISE Peshawar", "BISE Quetta", "Federal Board (FBISE)",
]
_UNIVERSITIES = [
    "LUMS", "NUST", "FAST-NU", "Punjab University", "University of Karachi",
    "Aga Khan University", "Government College University, Lahore", "IBA Karachi",
]
_DIPLOMA_INSTITUTIONS = [
    "Govt. College of Technology", "Punjab Board of Technical Education",
    "Sindh Board of Technical Education", "TEVTA Institute",
]

_INCOME_SOURCES = [
    ("Upwork / Fiverr clients", IncomeSourceType.FREELANCE),
    ("Cotton cloth shop (Anarkali Bazaar)", IncomeSourceType.INFORMAL_WORK),
    ("Auto rickshaw driving", IncomeSourceType.INFORMAL_WORK),
    ("Remittance from brother in Dubai", IncomeSourceType.REMITTANCE),
    ("Wheat and sugarcane farmland", IncomeSourceType.AGRICULTURE),
    ("Tailoring workshop at home", IncomeSourceType.INFORMAL_WORK),
]

# Filename fragments -> provider/type sniffing (used by the mock so demo
# files like "kelectric_bill_march.jpg" parse to the right utility).
_PROVIDER_HINTS: list[tuple[str, str, UtilityType]] = [
    ("kelectric", "K-Electric", UtilityType.ELECTRICITY),
    ("k-electric", "K-Electric", UtilityType.ELECTRICITY),
    ("lesco", "LESCO", UtilityType.ELECTRICITY),
    ("iesco", "IESCO", UtilityType.ELECTRICITY),
    ("fesco", "FESCO", UtilityType.ELECTRICITY),
    ("gepco", "GEPCO", UtilityType.ELECTRICITY),
    ("hesco", "HESCO", UtilityType.ELECTRICITY),
    ("pesco", "PESCO", UtilityType.ELECTRICITY),
    ("sepco", "SEPCO", UtilityType.ELECTRICITY),
    ("qesco", "QESCO", UtilityType.ELECTRICITY),
    ("tesco", "TESCO", UtilityType.ELECTRICITY),
    ("sngpl", "SNGPL", UtilityType.GAS),
    ("ssgc", "SSGC", UtilityType.GAS),
    ("sui", "SNGPL", UtilityType.GAS),
    ("gas", "SNGPL", UtilityType.GAS),
    ("kwsb", "KWSB", UtilityType.WATER),
    ("wasa", "WASA Lahore", UtilityType.WATER),
    ("water", "KWSB", UtilityType.WATER),
]

# ── Extraction prompts (strict JSON, enum-constrained) ────────────────────────

UTILITY_BILL_PROMPT = """You are a document parsing assistant for Pakistani utility bills
(K-Electric, LESCO, IESCO, SNGPL, SSGC, KWSB, WASA, and other distribution companies).
Extract these fields from the attached document and return ONLY a JSON object:

{
  "provider": "name of the utility company, or null",
  "utility_type": "electricity" | "gas" | "water",
  "units_consumed": <number: kWh for electricity, cubic feet or MMBtu for gas, gallons for water>,
  "amount_billed": <number, total billed amount in PKR>,
  "arrears": <number, outstanding previous dues in PKR, 0 if none>,
  "billing_month": "<YYYY-MM of the billing period, or null>",
  "consumer_name": "<name printed on the bill, or null>"
}

Use null for any field you cannot read with confidence. Do not guess.
Respond with the JSON object only — no markdown fences, no commentary."""

ACADEMIC_RECORD_PROMPT = """You are a document parsing assistant for Pakistani academic documents
(marksheets, transcripts, diplomas from BISE boards, HEC-recognised universities, technical boards).
Extract these fields from the attached document and return ONLY a JSON object:

{
  "institution": "name of the board or university, or null",
  "qualification_level": "matric" | "intermediate" | "bachelors" | "masters" | "diploma",
  "result_value": <number: percentage (0-100), GPA (0.0-4.0), or division (1/2/3)>,
  "result_scale": "percentage" | "gpa" | "division",
  "year": <integer year the result was awarded>,
  "student_name": "<name printed on the document, or null>"
}

Use null for any field you cannot read with confidence. Do not guess.
Respond with the JSON object only — no markdown fences, no commentary."""

INCOME_SLIP_PROMPT = """You are a document parsing assistant for Pakistani income documents
(salary slips, income affidavits on stamp paper, freelancer payment statements, remittance receipts).
Extract these fields from the attached document and return ONLY a JSON object:

{
  "monthly_income": <number, monthly income in PKR>,
  "source_type": "freelance" | "informal_work" | "remittance" | "agriculture",
  "dependants": <integer number of dependants named or stated, or null>,
  "employer_or_source": "employer, client, or income source name, or null",
  "evidence_type": "documented"
}

Use null for any field you cannot read with confidence. Do not guess.
Respond with the JSON object only — no markdown fences, no commentary."""


class DocumentParserService:
    """Multimodal document parsing backed by Alibaba Cloud Model Studio.

    With ``DASHSCOPE_API_KEY`` configured, each parse call sends the uploaded
    file to Qwen-VL with a strict JSON extraction prompt.  Without a key —
    or when the API call, JSON parse, or field coercion fails — the service
    falls back to deterministic mock extraction seeded by the file content.
    """

    DASHSCOPE_URL = (
        "https://dashscope.aliyuncs.com/api/v1/services/"
        "aigc/multimodal-generation/generation"
    )

    MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
    ALLOWED_CONTENT_TYPES = {
        "image/jpeg", "image/png", "image/webp", "application/pdf",
    }

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        _settings = get_settings()
        self._api_key = (
            _settings.dashscope_api_key if api_key is None else api_key
        )
        self._model = (
            _settings.alibaba_qwen_model if model is None else model
        )
        self._timeout = timeout

    @property
    def live(self) -> bool:
        """True when a DashScope key is configured and Qwen-VL will be used."""
        return bool(self._api_key)

    # ── Public parse API ─────────────────────────────────────────────────────

    def parse_utility_bill(
        self, content: bytes, filename: str, content_type: str | None,
    ) -> UtilityBillParseResult:
        """Parse an electricity/gas/water bill into structured fields."""
        self._validate_upload(content, content_type)
        payload = self._extract(content, content_type, UTILITY_BILL_PROMPT)
        mode = "qwen_vl"
        if payload is None:
            payload = self._mock_utility_bill(content, filename)
            mode = "mock"

        return UtilityBillParseResult(
            mode=mode,
            source_filename=filename,
            parsed_at=datetime.now(timezone.utc),
            provider=self._clean_str(payload.get("provider"))
            or self._sniff_provider(filename)[0],
            utility_type=self._coerce_utility_type(
                payload.get("utility_type"), filename,
            ),
            units_consumed=self._coerce_amount(payload.get("units_consumed")),
            amount_billed=self._coerce_amount(payload.get("amount_billed")),
            arrears=self._coerce_amount(payload.get("arrears")),
            billing_month=self._coerce_month(payload.get("billing_month")),
            consumer_name=self._clean_str(payload.get("consumer_name")),
        )

    def parse_academic_record(
        self, content: bytes, filename: str, content_type: str | None,
    ) -> AcademicRecordParseResult:
        """Parse a marksheet, transcript, or diploma into structured fields."""
        self._validate_upload(content, content_type)
        payload = self._extract(content, content_type, ACADEMIC_RECORD_PROMPT)
        mode = "qwen_vl"
        if payload is None:
            payload = self._mock_academic_record(content, filename)
            mode = "mock"

        qualification = self._coerce_qualification(
            payload.get("qualification_level"), filename,
        )
        scale = self._coerce_result_scale(
            payload.get("result_scale"), payload.get("result_value"),
        )
        return AcademicRecordParseResult(
            mode=mode,
            source_filename=filename,
            parsed_at=datetime.now(timezone.utc),
            institution=self._clean_str(payload.get("institution"))
            or self._mock_institution(qualification, content),
            qualification_level=qualification,
            result_value=self._coerce_amount(payload.get("result_value")),
            result_scale=scale,
            year=self._coerce_year(payload.get("year")),
            student_name=self._clean_str(payload.get("student_name")),
        )

    def parse_income_slip(
        self, content: bytes, filename: str, content_type: str | None,
    ) -> IncomeSlipParseResult:
        """Parse a salary slip or income affidavit into structured fields."""
        self._validate_upload(content, content_type)
        payload = self._extract(content, content_type, INCOME_SLIP_PROMPT)
        mode = "qwen_vl"
        if payload is None:
            payload = self._mock_income_slip(content, filename)
            mode = "mock"

        source = self._coerce_income_source(
            payload.get("source_type"), filename,
        )
        return IncomeSlipParseResult(
            mode=mode,
            source_filename=filename,
            parsed_at=datetime.now(timezone.utc),
            monthly_income=self._coerce_amount(payload.get("monthly_income")),
            source_type=source,
            dependants=self._coerce_int(payload.get("dependants")),
            employer_or_source=self._clean_str(
                payload.get("employer_or_source")
            ),
            # A physically supplied document is documented evidence by
            # definition — even when values needed the mock fallback.
            evidence_type=self._coerce_evidence(payload.get("evidence_type"))
            or EvidenceType.DOCUMENTED,
        )

    # ── Qwen-VL call ─────────────────────────────────────────────────────────

    def _extract(
        self, content: bytes, content_type: str | None, prompt: str,
    ) -> dict | None:
        """Call Qwen-VL and return the parsed JSON payload, or None on failure."""
        if not self.live:
            return None

        media_type = content_type or "application/octet-stream"
        data_url = (
            f"data:{media_type};base64,"
            f"{base64.b64encode(content).decode('ascii')}"
        )
        body = {
            "model": self._model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"image": data_url},
                            {"text": prompt},
                        ],
                    }
                ]
            },
            "parameters": {
                "result_format": "message",
                "temperature": 0.1,
                "seed": 42,  # deterministic extraction across retries
            },
        }

        try:
            response = httpx.post(
                self.DASHSCOPE_URL,
                json=body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            text = self._extract_text(response.json())
            return self._parse_json_block(text)
        except Exception as exc:  # noqa: BLE001 — any failure falls back to mock
            logger.warning(
                "Qwen-VL extraction failed (%s: %s) — falling back to mock "
                "extraction for this document.",
                type(exc).__name__, exc,
            )
            return None

    @staticmethod
    def _extract_text(response_body: dict) -> str | None:
        """Pull the assistant message text out of a DashScope response."""
        try:
            choices = response_body["output"]["choices"]
            message = choices[0]["message"]
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict)
                ]
                return "".join(parts) or None
        except (KeyError, IndexError, TypeError, AttributeError):
            pass
        return None

    @staticmethod
    def _parse_json_block(text: str | None) -> dict | None:
        """Parse a JSON object out of model output, tolerating markdown fences."""
        if not text:
            return None
        cleaned = text.strip()
        # Strip ```json ... ``` fences if the model added them despite orders.
        fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
        if fence:
            cleaned = fence.group(1).strip()
        # Take the outermost { ... } block to drop any stray prose.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    # ── Upload validation ────────────────────────────────────────────────────

    def _validate_upload(
        self, content: bytes, content_type: str | None,
    ) -> None:
        if not content:
            raise ValueError("Uploaded file is empty.")
        if len(content) > self.MAX_FILE_BYTES:
            raise ValueError(
                f"File exceeds the {self.MAX_FILE_BYTES // (1024 * 1024)} MB limit."
            )
        normalised = (content_type or "").split(";")[0].strip().lower()
        if normalised and normalised not in self.ALLOWED_CONTENT_TYPES:
            raise ValueError(
                f"Unsupported file type '{content_type}'. "
                "Upload a JPEG, PNG, WebP image, or a PDF."
            )

    # ── Mock extraction (deterministic, seeded by file content) ──────────────

    @staticmethod
    def _rng(content: bytes) -> random.Random:
        """Deterministic RNG — the same file always parses to the same values."""
        return random.Random(hashlib.sha256(content).hexdigest())

    @staticmethod
    def _sniff_provider(filename: str) -> tuple[str | None, UtilityType | None]:
        """Guess provider and utility type from filename fragments."""
        lowered = filename.lower()
        for hint, provider, utility in _PROVIDER_HINTS:
            if hint in lowered:
                return provider, utility
        return None, None

    def _mock_utility_bill(self, content: bytes, filename: str) -> dict:
        rng = self._rng(content)
        provider, utility = self._sniff_provider(filename)
        if utility is None:
            utility = rng.choice(
                [UtilityType.ELECTRICITY] * 8
                + [UtilityType.GAS] * 3
                + [UtilityType.WATER]
            )
        if provider is None:
            provider = {
                UtilityType.ELECTRICITY: rng.choice(_ELECTRICITY_PROVIDERS),
                UtilityType.GAS: rng.choice(_GAS_PROVIDERS),
                UtilityType.WATER: rng.choice(_WATER_PROVIDERS),
            }[utility]

        # A recent billing month, 1–6 months back from today.
        today = date.today()
        month_index = today.month - rng.randint(1, 6)
        if month_index <= 0:
            month_index += 12
        billing_month = date(today.year, month_index, 1)

        if utility == UtilityType.ELECTRICITY:
            units = float(rng.randint(120, 580))
            rate = rng.uniform(24.0, 42.0)
            amount = round(units * rate + rng.uniform(200, 900))
            arrears = float(rng.choice([0, 0, 0, rng.randint(500, 6000)]))
        elif utility == UtilityType.GAS:
            units = float(rng.randint(60, 320))
            amount = float(rng.randint(1500, 12000))
            arrears = float(rng.choice([0, 0, rng.randint(300, 3000)]))
        else:
            units = float(rng.randint(800, 4500))
            amount = float(rng.randint(500, 3500))
            arrears = float(rng.choice([0, 0, rng.randint(100, 800)]))

        return {
            "provider": provider,
            "utility_type": utility.value,
            "units_consumed": units,
            "amount_billed": amount,
            "arrears": arrears,
            "billing_month": billing_month.isoformat(),
            "consumer_name": None,
        }

    def _mock_academic_record(self, content: bytes, filename: str) -> dict:
        rng = self._rng(content)
        lowered = filename.lower()

        qualification = None
        for hint, level in [
            ("matric", QualificationLevel.MATRIC),
            ("ssc", QualificationLevel.MATRIC),
            ("inter", QualificationLevel.INTERMEDIATE),
            ("fsc", QualificationLevel.INTERMEDIATE),
            ("fa", QualificationLevel.INTERMEDIATE),
            ("hssc", QualificationLevel.INTERMEDIATE),
            ("bachelor", QualificationLevel.BACHELORS),
            ("bsc", QualificationLevel.BACHELORS),
            ("bs", QualificationLevel.BACHELORS),
            ("bba", QualificationLevel.BACHELORS),
            ("master", QualificationLevel.MASTERS),
            ("msc", QualificationLevel.MASTERS),
            ("ms", QualificationLevel.MASTERS),
            ("diploma", QualificationLevel.DIPLOMA),
        ]:
            if hint in lowered:
                qualification = level
                break
        if qualification is None:
            qualification = rng.choice(list(QualificationLevel))

        # Board results use percentages; university results use GPA.
        if qualification in (QualificationLevel.MATRIC,
                             QualificationLevel.INTERMEDIATE):
            scale, value = (
                ResultScale.PERCENTAGE, float(rng.randint(45, 92)),
            )
        elif qualification == QualificationLevel.DIPLOMA:
            scale, value = (
                ResultScale.PERCENTAGE, float(rng.randint(55, 88)),
            )
        else:
            scale, value = (
                ResultScale.GPA, round(rng.uniform(2.1, 3.9), 2),
            )

        return {
            "institution": self._mock_institution(qualification, content),
            "qualification_level": qualification.value,
            "result_value": value,
            "result_scale": scale.value,
            "year": rng.randint(2019, 2025),
            "student_name": None,
        }

    @staticmethod
    def _mock_institution(
        qualification: QualificationLevel | None, content: bytes,
    ) -> str:
        rng = DocumentParserService._rng(content)
        if qualification == QualificationLevel.DIPLOMA:
            return rng.choice(_DIPLOMA_INSTITUTIONS)
        if qualification in (QualificationLevel.BACHELORS,
                             QualificationLevel.MASTERS):
            return rng.choice(_UNIVERSITIES)
        if qualification in (QualificationLevel.MATRIC,
                             QualificationLevel.INTERMEDIATE):
            return rng.choice(_BOARD_INSTITUTIONS)
        return rng.choice(_BOARD_INSTITUTIONS + _UNIVERSITIES)

    def _mock_income_slip(self, content: bytes, filename: str) -> dict:
        rng = self._rng(content)
        lowered = filename.lower()

        source = None
        for hint, income_type in [
            ("freelance", IncomeSourceType.FREELANCE),
            ("upwork", IncomeSourceType.FREELANCE),
            ("fiverr", IncomeSourceType.FREELANCE),
            ("remittance", IncomeSourceType.REMITTANCE),
            ("dubai", IncomeSourceType.REMITTANCE),
            ("abroad", IncomeSourceType.REMITTANCE),
            ("farm", IncomeSourceType.AGRICULTURE),
            ("agri", IncomeSourceType.AGRICULTURE),
            ("land", IncomeSourceType.AGRICULTURE),
            ("salary", IncomeSourceType.INFORMAL_WORK),
            ("slip", IncomeSourceType.INFORMAL_WORK),
            ("shop", IncomeSourceType.INFORMAL_WORK),
        ]:
            if hint in lowered:
                source = income_type
                break
        employer, source = rng.choice(
            [s for s in _INCOME_SOURCES if source is None or s[1] == source]
        )

        # Informal incomes cluster low; freelance/remittance skew higher.
        base = {
            IncomeSourceType.FREELANCE: (25000, 140000),
            IncomeSourceType.REMITTANCE: (30000, 120000),
            IncomeSourceType.AGRICULTURE: (18000, 85000),
            IncomeSourceType.INFORMAL_WORK: (12000, 65000),
        }[source]
        income = round(rng.uniform(*base) / 500) * 500

        return {
            "monthly_income": float(income),
            "source_type": source.value,
            "dependants": rng.randint(0, 8),
            "employer_or_source": employer,
            "evidence_type": EvidenceType.DOCUMENTED.value,
        }

    # ── Field coercion helpers ───────────────────────────────────────────────

    _CURRENCY_RE = re.compile(r"(?:rs\.?|pkr|₨)\s*", re.IGNORECASE)
    _NON_NUMERIC_RE = re.compile(r"[^0-9.\-]")

    @classmethod
    def _coerce_amount(cls, value: object) -> float | None:
        """Coerce 'Rs. 12,345', '7,800/-', 12345.0 → float; junk → None."""
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = cls._CURRENCY_RE.sub("", str(value))
        cleaned = cls._NON_NUMERIC_RE.sub("", cleaned)
        # Trailing dashes from the '/-' suffix common on Pakistani bills.
        cleaned = cleaned.rstrip("-")
        if not cleaned or cleaned in {".", "-"}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    @classmethod
    def _coerce_int(cls, value: object) -> int | None:
        amount = cls._coerce_amount(value)
        return int(amount) if amount is not None else None

    @classmethod
    def _coerce_year(cls, value: object) -> int | None:
        year = cls._coerce_int(value)
        return year if year is not None and 1970 <= year <= 2035 else None

    @classmethod
    def _coerce_month(cls, value: object) -> date | None:
        """Coerce '2024-06', 'June 2024', '06/2024', ISO dates → first of month."""
        if value is None:
            return None
        raw = str(value).strip()
        if not raw or raw.lower() in {"null", "none", "n/a"}:
            return None

        # ISO or YYYY-MM directly.
        iso = re.match(r"^(\d{4})-(\d{1,2})(?:-\d{1,2})?$", raw)
        if iso:
            return cls._safe_date(int(iso.group(1)), int(iso.group(2)))

        # MM/YYYY or MM/DD/YYYY.
        slash = re.match(r"^(\d{1,2})/(\d{4})$", raw)
        if slash:
            return cls._safe_date(int(slash.group(2)), int(slash.group(1)))

        # '<Month> YYYY' / '<Mon> YYYY' — English month names.
        month_names = {
            m.lower()[:3]: i
            for i, m in enumerate(
                ["January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November",
                 "December"], start=1,
            )
        }
        words = re.match(r"^([A-Za-z]+)\s+(\d{4})$", raw)
        if words and words.group(1).lower()[:3] in month_names:
            return cls._safe_date(
                int(words.group(2)), month_names[words.group(1).lower()[:3]],
            )
        return None

    @staticmethod
    def _safe_date(year: int, month: int) -> date | None:
        try:
            return date(year, month, 1)
        except ValueError:
            return None

    @staticmethod
    def _clean_str(value: object) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned or cleaned.lower() in {"null", "none", "n/a", "-"}:
            return None
        return cleaned

    @staticmethod
    def _coerce_utility_type(
        value: object, filename: str = "",
    ) -> UtilityType | None:
        if value is not None:
            lowered = str(value).lower()
            if "elec" in lowered:
                return UtilityType.ELECTRICITY
            if "gas" in lowered:
                return UtilityType.GAS
            if "water" in lowered:
                return UtilityType.WATER
            try:
                return UtilityType(lowered)
            except ValueError:
                pass
        _, sniffed = DocumentParserService._sniff_provider(filename)
        return sniffed

    @staticmethod
    def _coerce_qualification(
        value: object, filename: str = "",
    ) -> QualificationLevel | None:
        if value is not None:
            lowered = str(value).lower()
            if "matric" in lowered or lowered == "ssc":
                return QualificationLevel.MATRIC
            if "inter" in lowered or lowered in {"fsc", "fa", "hssc", "fs.c"}:
                return QualificationLevel.INTERMEDIATE
            if "master" in lowered or lowered in {"msc", "ms", "mphil"}:
                return QualificationLevel.MASTERS
            if "diploma" in lowered:
                return QualificationLevel.DIPLOMA
            if "bachelor" in lowered or lowered in {"bsc", "bs", "ba", "bba", "be"}:
                return QualificationLevel.BACHELORS
            try:
                return QualificationLevel(lowered)
            except ValueError:
                pass
        return None

    @staticmethod
    def _coerce_result_scale(value: object, result_value: object = None) -> ResultScale | None:
        if value is not None:
            lowered = str(value).lower()
            if "percent" in lowered or lowered in {"%", "marks"}:
                return ResultScale.PERCENTAGE
            if "gpa" in lowered or lowered == "cgpa":
                return ResultScale.GPA
            if "division" in lowered:
                return ResultScale.DIVISION
            try:
                return ResultScale(lowered)
            except ValueError:
                pass
        # Infer from magnitude: >4.5 can only be a percentage.
        numeric = DocumentParserService._coerce_amount(result_value)
        if numeric is not None:
            if numeric > 4.5:
                return ResultScale.PERCENTAGE
            if 0 < numeric <= 4.0 and numeric == int(numeric) and numeric in (1, 2, 3):
                return ResultScale.DIVISION
            return ResultScale.GPA
        return None

    @staticmethod
    def _coerce_income_source(
        value: object, filename: str = "",
    ) -> IncomeSourceType | None:
        if value is not None:
            lowered = str(value).lower()
            if "freelance" in lowered or "self-employ" in lowered:
                return IncomeSourceType.FREELANCE
            if "remit" in lowered or "abroad" in lowered or "overseas" in lowered:
                return IncomeSourceType.REMITTANCE
            if "agri" in lowered or "farm" in lowered:
                return IncomeSourceType.AGRICULTURE
            if "informal" in lowered or "wage" in lowered or "salary" in lowered:
                return IncomeSourceType.INFORMAL_WORK
            try:
                return IncomeSourceType(lowered)
            except ValueError:
                pass
        return None

    @staticmethod
    def _coerce_evidence(value: object) -> EvidenceType | None:
        if value is None:
            return None
        lowered = str(value).lower()
        if "verif" in lowered:
            return EvidenceType.VERIFIED
        if "document" in lowered:
            return EvidenceType.DOCUMENTED
        if "self" in lowered or "declar" in lowered:
            return EvidenceType.SELF_DECLARED
        try:
            return EvidenceType(lowered)
        except ValueError:
            return None
