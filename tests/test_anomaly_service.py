"""
Anomaly & fraud shield engine tests.

All tests run against mock applicants (no database, no network).  Rule
behaviour, the risk-score ladder, policy recommendations, and the
score_applicant integration are covered end-to-end.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.services.anomaly_service import (
    AVG_TARIFF_PER_KWH,
    LOW_INCOME_THRESHOLD_PKR,
    detect_anomalies,
)
from app.services.feature_engineering import build_feature_vector
from app.services.scoring_service import score_applicant
from app.utils.enums import (
    AnomalySeverity,
    ConfidenceLevel,
    PolicyActionType,
    RiskLevel,
)
from tests.conftest import (
    MockAcademicRecord,
    MockApplicant,
    MockIncomeSignal,
    MockUtilityRecord,
)


# ── Builders ────────────────────────────────────────────────────────────────


def bill(
    amount: float,
    paid: float | None = None,
    month: date | None = None,
    utility_type: str = "electricity",
    days_late: int = 0,
) -> MockUtilityRecord:
    """One utility bill; fully paid unless a partial/None payment is given."""
    return MockUtilityRecord(
        utility_type=utility_type,
        billing_month=month or date(2026, 1, 1),
        amount_billed=amount,
        amount_paid=amount if paid is None else paid,
        days_late=days_late,
    )


def income(
    amount: float,
    evidence: str = "documented",
    source: str = "freelance",
) -> MockIncomeSignal:
    return MockIncomeSignal(
        source_type=source,
        declared_monthly_amount=amount,
        evidence_type=evidence,
        confidence_flag=False,
    )


def academic(
    value: float, scale: str, qualification: str = "matric", year: int = 2023,
) -> MockAcademicRecord:
    return MockAcademicRecord(
        qualification_level=qualification,
        result_value=value,
        result_scale=scale,
        year=year,
    )


def detect(applicant, **kwargs):
    """Run the fraud shield exactly as score_applicant does."""
    return detect_anomalies(
        applicant,
        applicant.utility_records,
        applicant.academic_records,
        applicant.income_signals,
        build_feature_vector(applicant),
        **kwargs,
    )


def codes(report) -> list[str]:
    return [f.code for f in report.flags]


MONTHS = [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]


# ── Clean applicants ────────────────────────────────────────────────────────


class TestCleanApplicant:
    def test_full_profile_is_clean(self, full_applicant):
        report = detect(full_applicant, score=70.0,
                        confidence=ConfidenceLevel.HIGH)
        assert report.flags == []
        assert report.risk_score == 0.0
        assert report.risk_level is RiskLevel.CLEAN
        assert report.audit_required is False
        assert report.top_flags == []

    def test_clean_gets_auto_approve_with_high_confidence(self, full_applicant):
        report = detect(full_applicant, score=70.0,
                        confidence=ConfidenceLevel.HIGH)
        rec = report.recommendation
        assert rec.action_type is PolicyActionType.AUTO_APPROVE
        assert rec.recommended_support == "Full Merit-Need Scholarship (100% Tuition)"
        # Two-sentence donor justification.
        assert rec.summary_justification.count(".") >= 2

    def test_thin_file_never_auto_approves(self, thin_applicant):
        """CLEAN but LOW confidence — the shield alone can't approve a thin file."""
        report = detect(thin_applicant, score=80.0,
                        confidence=ConfidenceLevel.LOW)
        assert report.risk_level is RiskLevel.CLEAN
        assert report.recommendation.action_type is PolicyActionType.STANDARD_REVIEW

    def test_empty_applicant_is_clean(self, empty_applicant):
        report = detect(empty_applicant)
        assert report.risk_level is RiskLevel.CLEAN
        assert report.risk_score == 0.0


# ── INCOME_BILL_MISMATCH ────────────────────────────────────────────────────


class TestIncomeBillMismatch:
    def _applicant(self, income_amount, bills):
        return MockApplicant(
            dependants=2,
            income_signals=[income(income_amount)],
            utility_records=bills,
        )

    def test_bill_exceeding_income_is_critical(self):
        applicant = self._applicant(20000, [bill(25000, month=m) for m in MONTHS])
        report = detect(applicant)
        assert "INCOME_BILL_MISMATCH" in codes(report)
        flag = next(f for f in report.flags if f.code == "INCOME_BILL_MISMATCH")
        assert flag.severity is AnomalySeverity.CRITICAL
        assert report.risk_level is RiskLevel.CRITICAL_MISMATCH
        assert report.audit_required is True

    def test_critical_mismatch_requires_field_audit(self):
        applicant = self._applicant(20000, [bill(25000, month=m) for m in MONTHS])
        report = detect(applicant, score=50.0, confidence=ConfidenceLevel.MEDIUM)
        assert report.risk_level is RiskLevel.CRITICAL_MISMATCH
        assert report.recommendation.action_type is PolicyActionType.FIELD_AUDIT_REQUIRED
        assert report.recommendation.recommended_support == "Physical Verification Required"

    def test_bill_over_60_percent_of_income_is_warning(self):
        # Mixed utilities: electricity 8000 + gas 6000 → 14000 total per month.
        bills = []
        for m in MONTHS:
            bills.append(bill(8000, month=m, utility_type="electricity"))
            bills.append(bill(6000, month=m, utility_type="gas"))
        report = detect(self._applicant(20000, bills))
        flag = next(f for f in report.flags if f.code == "INCOME_BILL_MISMATCH")
        assert flag.severity is AnomalySeverity.WARNING
        assert report.risk_level is RiskLevel.MODERATE_FLAG
        assert report.recommendation.action_type is PolicyActionType.STANDARD_REVIEW

    def test_bill_around_half_of_income_is_info(self):
        applicant = self._applicant(20000, [bill(9500, month=m) for m in MONTHS])
        report = detect(applicant)
        flag = next(f for f in report.flags if f.code == "INCOME_BILL_MISMATCH")
        assert flag.severity is AnomalySeverity.INFO
        assert report.risk_level is RiskLevel.LOW_RISK

    def test_modest_bill_ratio_not_flagged(self):
        applicant = self._applicant(40000, [bill(4000, month=m) for m in MONTHS])
        report = detect(applicant)
        assert "INCOME_BILL_MISMATCH" not in codes(report)

    def test_no_income_claim_not_flagged(self):
        """No declared income → the ratio is unknowable, never a flag."""
        applicant = MockApplicant(
            dependants=2,
            utility_records=[bill(25000, month=m) for m in MONTHS],
        )
        report = detect(applicant)
        assert "INCOME_BILL_MISMATCH" not in codes(report)


# ── LUXURY_TARIFF_INDICATOR ─────────────────────────────────────────────────


class TestLuxuryTariff:
    def _applicant(self, income_amount, electricity_amount):
        return MockApplicant(
            dependants=2,
            income_signals=[income(income_amount)],
            utility_records=[bill(electricity_amount, month=m) for m in MONTHS],
        )

    def test_over_400_units_with_low_income_flagged(self):
        electricity = 13000  # ~448 kWh at the blended tariff
        applicant = self._applicant(24000, electricity)
        report = detect(applicant)
        assert "LUXURY_TARIFF_INDICATOR" in codes(report)
        flag = next(f for f in report.flags if f.code == "LUXURY_TARIFF_INDICATOR")
        assert flag.severity is AnomalySeverity.WARNING
        assert flag.evidence["estimated_units_kwh"] == pytest.approx(
            electricity / AVG_TARIFF_PER_KWH, abs=1.0,
        )
        assert report.risk_level is RiskLevel.MODERATE_FLAG

    def test_consumption_below_threshold_not_flagged(self):
        report = detect(self._applicant(24000, 10000))  # ~345 kWh
        assert "LUXURY_TARIFF_INDICATOR" not in codes(report)

    def test_high_income_not_extreme_need(self):
        report = detect(self._applicant(50000, 15000))  # ~517 kWh, but not poor
        assert "LUXURY_TARIFF_INDICATOR" not in codes(report)

    def test_gas_bills_never_trigger_luxury(self):
        applicant = MockApplicant(
            dependants=2,
            income_signals=[income(20000)],
            utility_records=[bill(15000, month=m, utility_type="gas") for m in MONTHS],
        )
        report = detect(applicant)
        assert "LUXURY_TARIFF_INDICATOR" not in codes(report)


# ── CHRONIC_DEFAULT_BURDEN ──────────────────────────────────────────────────


class TestChronicDefault:
    def _applicant(self, bills):
        return MockApplicant(
            dependants=2,
            income_signals=[income(50000)],
            utility_records=bills,
        )

    def test_arrears_over_2x_bill_is_warning(self):
        bills = [
            bill(5000, month=MONTHS[0]),
            bill(5000, month=MONTHS[1], paid=0),   # unpaid
            bill(5000, month=MONTHS[2], paid=0),   # unpaid
            bill(5000, month=date(2026, 4, 1), paid=0),  # unpaid
        ]
        report = detect(self._applicant(bills))
        assert "CHRONIC_DEFAULT_BURDEN" in codes(report)
        flag = next(f for f in report.flags if f.code == "CHRONIC_DEFAULT_BURDEN")
        assert flag.severity is AnomalySeverity.WARNING
        assert flag.evidence["arrears_to_bill_multiple"] == pytest.approx(3.0)

    def test_arrears_between_1x_and_2x_is_info(self):
        bills = [
            bill(5000, month=MONTHS[0]),
            bill(5000, month=MONTHS[1], paid=0),
            bill(5000, month=MONTHS[2], paid=0),
        ]
        report = detect(self._applicant(bills))
        flag = next(f for f in report.flags if f.code == "CHRONIC_DEFAULT_BURDEN")
        assert flag.severity is AnomalySeverity.INFO

    def test_paid_bills_no_flag(self):
        report = detect(self._applicant([bill(5000, month=m) for m in MONTHS]))
        assert "CHRONIC_DEFAULT_BURDEN" not in codes(report)

    def test_partial_payments_count_toward_arrears(self):
        bills = [
            bill(6000, month=MONTHS[0], paid=1000),  # 5000 outstanding
            bill(6000, month=MONTHS[1], paid=1000),
            bill(6000, month=MONTHS[2], paid=1000),
        ]
        report = detect(self._applicant(bills))
        flag = next(f for f in report.flags if f.code == "CHRONIC_DEFAULT_BURDEN")
        # 15000 outstanding vs 6000 avg bill = 2.5x → warning.
        assert flag.severity is AnomalySeverity.WARNING


# ── INCOME_EVIDENCE_GAP ─────────────────────────────────────────────────────


class TestIncomeEvidenceGap:
    def test_extreme_need_self_declared_flagged(self):
        applicant = MockApplicant(
            dependants=3,
            income_signals=[income(18000, evidence="self_declared",
                                   source="informal_work")],
            utility_records=[bill(2000, month=m) for m in MONTHS],
        )
        report = detect(applicant)
        assert "INCOME_EVIDENCE_GAP" in codes(report)
        flag = next(f for f in report.flags if f.code == "INCOME_EVIDENCE_GAP")
        assert flag.severity is AnomalySeverity.WARNING

    def test_documented_income_not_flagged(self):
        applicant = MockApplicant(
            dependants=3,
            income_signals=[income(18000, evidence="documented")],
            utility_records=[bill(2000, month=m) for m in MONTHS],
        )
        report = detect(applicant)
        assert "INCOME_EVIDENCE_GAP" not in codes(report)

    def test_verified_daily_wager_not_flagged(self):
        applicant = MockApplicant(
            dependants=3,
            income_signals=[income(30000, evidence="verified",
                                   source="informal_work")],
            utility_records=[bill(2000, month=m) for m in MONTHS],
        )
        report = detect(applicant)
        assert "INCOME_EVIDENCE_GAP" not in codes(report)

    def test_high_income_self_declared_daily_wager_flagged(self):
        """Daily-wager income without proof flags even above the low-income line."""
        applicant = MockApplicant(
            dependants=3,
            income_signals=[income(40000, evidence="self_declared",
                                   source="informal_work")],
            utility_records=[bill(2000, month=m) for m in MONTHS],
        )
        report = detect(applicant)
        assert "INCOME_EVIDENCE_GAP" in codes(report)

    def test_high_income_self_declared_freelance_not_flagged(self):
        """Self-declared freelance income above the extreme-need line is fine."""
        applicant = MockApplicant(
            dependants=3,
            income_signals=[income(40000, evidence="self_declared",
                                   source="freelance")],
            utility_records=[bill(2000, month=m) for m in MONTHS],
        )
        report = detect(applicant)
        assert "INCOME_EVIDENCE_GAP" not in codes(report)


# ── ACADEMIC_MERIT_DISCORDANCE ──────────────────────────────────────────────


class TestAcademicDiscordance:
    def _applicant(self, records):
        return MockApplicant(
            dependants=2,
            income_signals=[income(40000)],
            utility_records=[bill(3000, month=m) for m in MONTHS],
            academic_records=records,
        )

    def test_high_claim_conflicting_result_flagged(self):
        records = [
            academic(92, "percentage", "matric", 2022),
            academic(55, "percentage", "intermediate", 2024),
        ]
        report = detect(self._applicant(records))
        assert "ACADEMIC_MERIT_DISCORDANCE" in codes(report)
        flag = next(f for f in report.flags if f.code == "ACADEMIC_MERIT_DISCORDANCE")
        assert flag.severity is AnomalySeverity.WARNING
        assert flag.evidence["drop"] == pytest.approx(0.37, abs=0.001)

    def test_consistent_merit_not_flagged(self):
        records = [
            academic(90, "percentage", "matric", 2022),
            academic(82, "percentage", "intermediate", 2024),
        ]
        report = detect(self._applicant(records))
        assert "ACADEMIC_MERIT_DISCORDANCE" not in codes(report)

    def test_scale_impossible_value_flagged(self):
        records = [academic(4.5, "gpa", "bachelors", 2024)]
        report = detect(self._applicant(records))
        assert "ACADEMIC_MERIT_DISCORDANCE" in codes(report)

    def test_single_record_not_flagged(self):
        """A lone high result has nothing to conflict with."""
        report = detect(self._applicant([academic(90, "percentage")]))
        assert "ACADEMIC_MERIT_DISCORDANCE" not in codes(report)


# ── DEPENDENCY_INFLATION ────────────────────────────────────────────────────


class TestDependencyInflation:
    def _applicant(self, dependants, signals):
        return MockApplicant(
            dependants=dependants,
            income_signals=signals,
            utility_records=[bill(3000, month=m) for m in MONTHS],
        )

    def test_nine_dependants_single_earner_flagged(self):
        applicant = self._applicant(9, [income(30000)])
        report = detect(applicant)
        assert "DEPENDENCY_INFLATION" in codes(report)
        flag = next(f for f in report.flags if f.code == "DEPENDENCY_INFLATION")
        assert flag.severity is AnomalySeverity.WARNING

    def test_many_dependants_multi_earner_not_flagged(self):
        applicant = self._applicant(10, [income(30000), income(20000)])
        report = detect(applicant)
        assert "DEPENDENCY_INFLATION" not in codes(report)

    def test_small_household_not_flagged(self):
        applicant = self._applicant(5, [income(30000)])
        report = detect(applicant)
        assert "DEPENDENCY_INFLATION" not in codes(report)

    def test_null_dependants_not_flagged(self):
        applicant = MockApplicant(
            dependants=None,
            income_signals=[income(30000)],
            utility_records=[bill(3000, month=m) for m in MONTHS],
        )
        report = detect(applicant)
        assert "DEPENDENCY_INFLATION" not in codes(report)


# ── Risk score ladder ───────────────────────────────────────────────────────


class TestRiskScoreLadder:
    def test_info_only_is_low_risk(self):
        applicant = MockApplicant(
            dependants=2,
            income_signals=[income(20000)],
            utility_records=[bill(9500, month=m) for m in MONTHS],  # 47.5% → INFO
        )
        report = detect(applicant)
        assert all(f.severity is AnomalySeverity.INFO for f in report.flags)
        assert report.risk_score == 8.0
        assert report.risk_level is RiskLevel.LOW_RISK
        assert report.audit_required is False

    def test_single_warning_is_moderate_flag(self):
        # Gas bills alone: the income-bill warning fires with no luxury flag.
        applicant = MockApplicant(
            dependants=2,
            income_signals=[income(20000)],
            utility_records=[
                bill(14000, month=m, utility_type="gas") for m in MONTHS
            ],
        )
        report = detect(applicant)
        assert len(report.flags) == 1
        assert report.risk_score == 22.0
        assert report.risk_level is RiskLevel.MODERATE_FLAG
        assert report.audit_required is False

    def test_two_warnings_is_high_suspicion_with_audit(self):
        # Income-bill warning (65% of income) + luxury warning; documented
        # income keeps the evidence-gap rule quiet.
        applicant = MockApplicant(
            dependants=2,
            income_signals=[income(20000)],
            utility_records=[bill(13000, month=m) for m in MONTHS],
        )
        report = detect(applicant)
        assert len(report.flags) == 2
        assert report.risk_score == 44.0
        assert report.risk_level is RiskLevel.HIGH_SUSPICION
        assert report.audit_required is True
        assert report.recommendation.action_type is PolicyActionType.FIELD_AUDIT_REQUIRED

    def test_compounded_risk_reaches_high_risk_reject(self):
        """Critical mismatch plus several warnings → recommendation to reject."""
        applicant = MockApplicant(
            dependants=2,
            income_signals=[income(20000, evidence="self_declared",
                                   source="informal_work")],
            utility_records=[bill(25000, month=m, paid=0) for m in MONTHS],
        )
        report = detect(applicant, score=40.0, confidence=ConfidenceLevel.MEDIUM)
        # Critical: bill > income. Warnings: luxury, chronic default, evidence gap.
        assert report.risk_level is RiskLevel.CRITICAL_MISMATCH
        assert report.risk_score >= 90
        assert report.recommendation.action_type is PolicyActionType.HIGH_RISK_REJECT

    def test_top_flags_ranked_worst_first(self):
        # Critical mismatch + three warnings: the critical flag leads even
        # though the luxury rule would otherwise head the warning list.
        applicant = MockApplicant(
            dependants=9,
            income_signals=[income(20000, evidence="self_declared")],
            utility_records=[bill(25000, month=m) for m in MONTHS],
        )
        report = detect(applicant)
        assert report.flags_count == 4
        assert report.top_flags[0] == "INCOME_BILL_MISMATCH"
        assert set(report.top_flags) == {
            "INCOME_BILL_MISMATCH", "LUXURY_TARIFF_INDICATOR",
            "INCOME_EVIDENCE_GAP",
        }


# ── Policy recommendation support tiers ─────────────────────────────────────


class TestSupportTiers:
    def _clean(self) -> MockApplicant:
        return MockApplicant(
            dependants=2,
            income_signals=[income(40000)],
            utility_records=[bill(3000, month=m) for m in MONTHS],
        )

    def test_high_score_full_scholarship(self):
        report = detect(self._clean(), score=72.0,
                        confidence=ConfidenceLevel.HIGH)
        assert report.recommendation.recommended_support == (
            "Full Merit-Need Scholarship (100% Tuition)"
        )

    def test_mid_score_partial_support(self):
        report = detect(self._clean(), score=50.0,
                        confidence=ConfidenceLevel.HIGH)
        assert report.recommendation.recommended_support == "Partial Fee Support (50%)"

    def test_low_score_emergency_micro_grant(self):
        report = detect(self._clean(), score=25.0,
                        confidence=ConfidenceLevel.HIGH)
        assert report.recommendation.recommended_support == "Emergency Micro-Grant"


# ── Scoring service integration ─────────────────────────────────────────────


class TestScoringIntegration:
    def test_result_dict_carries_anomaly_fields(self, full_applicant):
        result = score_applicant(full_applicant)
        assert result["anomaly_risk_score"] == 0.0
        assert result["anomaly_risk_level"] is RiskLevel.CLEAN
        assert result["anomaly_audit_required"] is False
        assert result["anomaly_flags_count"] == 0
        assert result["anomaly_report"]["risk_level"] == "clean"
        assert result["anomaly_report"]["flags"] == []
        assert result["anomaly_report"]["recommendation"] is not None

    def test_anomaly_report_is_json_serialisable(self, full_applicant):
        result = score_applicant(full_applicant)
        # JSONB round-trip: everything must be plain JSON types.
        parsed = json.loads(json.dumps(result["anomaly_report"]))
        assert parsed["risk_score"] == 0.0
        assert parsed["recommendation"]["action_type"] == "auto_approve"

    def test_critical_applicant_flagged_through_scoring(self):
        applicant = MockApplicant(
            dependants=2,
            income_signals=[income(20000)],
            utility_records=[bill(25000, month=m) for m in MONTHS],
        )
        result = score_applicant(applicant)
        assert result["anomaly_risk_level"] is RiskLevel.CRITICAL_MISMATCH
        assert result["anomaly_audit_required"] is True
        assert "INCOME_BILL_MISMATCH" in result["anomaly_report"]["top_flags"]
        assert result["anomaly_report"]["recommendation"]["action_type"] == (
            "field_audit_required"
        )

    def test_report_flags_carry_evidence(self):
        applicant = MockApplicant(
            dependants=2,
            income_signals=[income(20000)],
            utility_records=[bill(25000, month=m) for m in MONTHS],
        )
        result = score_applicant(applicant)
        flag = next(
            f for f in result["anomaly_report"]["flags"]
            if f["code"] == "INCOME_BILL_MISMATCH"
        )
        assert flag["severity"] == "critical"
        assert flag["evidence"]["spend_to_income_ratio"] == pytest.approx(1.25)
        assert flag["evidence"]["total_declared_income_pkr"] == 20000.0

    def test_rule_failure_never_blocks_scoring(self, full_applicant, monkeypatch):
        """A crashing rule is skipped, not fatal — scoring must always finish."""
        from app.services import anomaly_service

        def _boom(*args, **kwargs):
            raise RuntimeError("rule exploded")

        monkeypatch.setattr(anomaly_service, "_rule_chronic_default", _boom)
        result = score_applicant(full_applicant)
        assert result["anomaly_risk_level"] is RiskLevel.CLEAN
