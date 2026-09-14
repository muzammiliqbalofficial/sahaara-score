"""
Anomaly & fraud shield service — detects contradictory, suspicious, or
high-risk claims in an applicant's file and produces a transparent policy
recommendation for institutional reviewers.

Design philosophy
─────────────────
1. Every rule compares data the applicant (or their documents) supplied
    against *other* data in the same file. No rule relies on external
    registries — the shield catches internal contradictions.
2. Flags are evidence, not verdicts. Each flag carries its severity, a
    reviewer-readable message, and the numeric evidence behind it, so a
    human can audit every automated recommendation.
3. Missing data never triggers a flag. "We don't know" is not "this is
    suspicious" — the same principle as the nullable-first feature layer.
4. The policy recommendation is deterministic given the flags and score:
    the same file always yields the same recommendation.

Rules (2026):
  INCOME_BILL_MISMATCH utility spend > 60% of income (WARNING)
                            or exceeding income entirely (CRITICAL)
  LUXURY_TARIFF_INDICATOR ~400+ kWh consumption while claiming
                            extreme-low income (WARNING)
  CHRONIC_DEFAULT_BURDEN accumulated arrears > 2x monthly bill (WARNING;
                            1–2x is an INFO observation)
  INCOME_EVIDENCE_GAP extreme-need or daily-wager income claim with
                            no documented/verified proof (WARNING)
  ACADEMIC_MERIT_DISCORDANCE best result > 85% conflicting with another
                            submitted result, or a scale-impossible value
                            (WARNING)
  DEPENDENCY_INFLATION 9+ dependants with no multi-earner evidence
                            (WARNING)

Because UtilityRecord does not store meter units or printed arrears (the
document parser extracts them but they are not persisted yet), those
quantities are *estimated* from billed amounts: units ≈ electricity bill /
AVG_TARIFF_PER_KWH, arrears ≈ accumulated unpaid portions of bills. Both
estimates are conservative and recorded in the flag evidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.feature_engineering import FeatureSet, _normalise_result
from app.utils.enums import (
    AnomalySeverity,
    ConfidenceLevel,
    EvidenceType,
    IncomeSourceType,
    PolicyActionType,
    ResultScale,
    RiskLevel,
    UtilityType,
)

logger = logging.getLogger(__name__)

# ── Policy thresholds ────────────────────────────────────────────────────────

# Household income below this (PKR/month) counts as an "extreme need" claim.
LOW_INCOME_THRESHOLD_PKR = 25_000

# Blended NEPRA slab rate used to estimate consumption from billed amounts.
AVG_TARIFF_PER_KWH = 29.0

# Electricity consumption above this (kWh/month) is luxury-tier usage.
LUXURY_UNITS_THRESHOLD = 400

# Utility-spend-to-income ratios.
INCOME_BILL_CRITICAL_RATIO = 1.0 # bill exceeds income entirely
INCOME_BILL_WARNING_RATIO = 0.60 # spec threshold: 60% of income
INCOME_BILL_INFO_RATIO = 0.45 # notable burden, worth recording

# Accumulated arrears as a multiple of the average monthly utility bill.
ARREARS_WARNING_MULTIPLE = 2.0
ARREARS_INFO_MULTIPLE = 1.0

# Dependants above this without multi-earner evidence suggests inflation.
DEPENDANTS_THRESHOLD = 8

# Academic merit thresholds (normalised 0-1 scale).
HIGH_MERIT_THRESHOLD = 0.85
MERIT_DROP_THRESHOLD = 0.30

# Risk score contribution per severity.
_SEVERITY_WEIGHTS: dict[AnomalySeverity, int] = {
    AnomalySeverity.INFO: 8,
    AnomalySeverity.WARNING: 22,
    AnomalySeverity.CRITICAL: 45,
}

# Sorting weight for ranking flags (higher = more prominent).
_SEVERITY_RANK: dict[AnomalySeverity, int] = {
    AnomalySeverity.INFO: 0,
    AnomalySeverity.WARNING: 1,
    AnomalySeverity.CRITICAL: 2,
}

_TOP_FLAGS_SHOWN = 3


# ── Result containers ────────────────────────────────────────────────────────


@dataclass
class AnomalyFlag:
    """One rule firing on an applicant's file."""

    code: str
    severity: AnomalySeverity
    title: str
    message: str # Reviewer-readable explanation
    evidence: dict = field(default_factory=dict) # The numbers behind the flag


@dataclass
class PolicyRecommendation:
    """The institutional action recommended for the applicant."""

    action_type: PolicyActionType
    recommended_support: str
    summary_justification: str # Two sentences, explainable to donors


@dataclass
class AnomalyReport:
    """Full fraud-shield output for one scoring run."""

    flags: list[AnomalyFlag] = field(default_factory=list)
    risk_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.CLEAN
    audit_required: bool = False
    recommendation: PolicyRecommendation | None = None

    @property
    def flags_count(self) -> int:
        return len(self.flags)

    @property
    def top_flags(self) -> list[str]:
        """Flag codes of the most severe findings, worst first."""
        ranked = sorted(
            self.flags,
            key=lambda f: _SEVERITY_RANK[f.severity],
            reverse=True,
        )
        return [f.code for f in ranked[:_TOP_FLAGS_SHOWN]]

    def to_dict(self) -> dict:
        """JSONB-serialisable representation stored on the Assessment."""
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level.value,
            "audit_required": self.audit_required,
            "flags_count": self.flags_count,
            "flags": [
                {
                    "code": f.code,
                    "severity": f.severity.value,
                    "title": f.title,
                    "message": f.message,
                    "evidence": f.evidence,
                }
                for f in self.flags
            ],
            "top_flags": self.top_flags,
            "recommendation": {
                "action_type": self.recommendation.action_type.value,
                "recommended_support": self.recommendation.recommended_support,
                "summary_justification": (
                    self.recommendation.summary_justification
                ),
            }
            if self.recommendation
            else None,
        }


# ── Evidence helpers ─────────────────────────────────────────────────────────


def _avg_monthly_utility_spend(records: list) -> float | None:
    """
    Average total utility spend per month, in PKR.

    Bills are grouped by billing month and summed, so a household holding
    electricity and gas bills for the same month is measured correctly.
    Records without a billing month each count as one month's observation.
    """
    amounts = [
        (r.billing_month, r.amount_billed)
        for r in records
        if r.amount_billed is not None
    ]
    if not amounts:
        return None

    by_month: dict = {}
    unmonthed: list[float] = []
    for month, amount in amounts:
        if month is not None:
            by_month.setdefault(month, []).append(amount)
        else:
            unmonthed.append(amount)

    monthly_totals = [sum(v) for v in by_month.values()] + unmonthed
    return sum(monthly_totals) / len(monthly_totals)


def _electricity_avg_bill(records: list) -> float | None:
    """Average electricity bill amount, in PKR (None if no electricity bills)."""
    amounts = [
        r.amount_billed
        for r in records
        if r.amount_billed is not None
        and r.utility_type == UtilityType.ELECTRICITY
    ]
    return sum(amounts) / len(amounts) if amounts else None


def _total_outstanding(records: list) -> float:
    """
    Accumulated arrears, estimated from billed vs paid amounts.

    A bill with no recorded payment counts fully; a partial payment counts
    its unpaid remainder; overpayments contribute nothing.
    """
    outstanding = 0.0
    for r in records:
        if r.amount_billed is None:
            continue
        if r.amount_paid is None:
            outstanding += r.amount_billed
        elif r.amount_paid < r.amount_billed:
            outstanding += r.amount_billed - r.amount_paid
    return outstanding


def _total_declared_income(signals: list) -> float | None:
    """Sum of declared monthly income in PKR (None when nothing is declared)."""
    if not signals:
        return None
    total = sum(
        s.declared_monthly_amount
        for s in signals
        if s.declared_monthly_amount is not None
    )
    return total if total > 0 else None


def _has_documented_income(signals: list) -> bool:
    """True if any income signal carries documented or verified evidence."""
    return any(
        s.evidence_type in (EvidenceType.DOCUMENTED, EvidenceType.VERIFIED)
        for s in signals
    )


# ── Rules ────────────────────────────────────────────────────────────────────


def _rule_income_bill_mismatch(
    utility_records: list, income_signals: list,
) -> list[AnomalyFlag]:
    """
    INCOME_BILL_MISMATCH — utility spending vs declared household income.

    Ladder: > 45% of income → INFO (notable burden), > 60% → WARNING,
    > 100% → CRITICAL (the declared figures cannot both be accurate).
    """
    total_income = _total_declared_income(income_signals)
    avg_spend = _avg_monthly_utility_spend(utility_records)
    if total_income is None or avg_spend is None or total_income <= 0:
        return []

    ratio = avg_spend / total_income
    evidence = {
        "avg_monthly_utility_spend_pkr": round(avg_spend, 2),
        "total_declared_income_pkr": round(total_income, 2),
        "spend_to_income_ratio": round(ratio, 3),
    }

    if ratio > INCOME_BILL_CRITICAL_RATIO:
        return [AnomalyFlag(
            code="INCOME_BILL_MISMATCH",
            severity=AnomalySeverity.CRITICAL,
            title="Utility spending exceeds declared income",
            message=(
                f"Monthly utility spending (PKR {avg_spend:,.0f}) exceeds the "
                f"total declared household income (PKR {total_income:,.0f}) — "
                f"the declared figures cannot both be accurate as submitted."
            ),
            evidence=evidence,
        )]
    if ratio > INCOME_BILL_WARNING_RATIO:
        return [AnomalyFlag(
            code="INCOME_BILL_MISMATCH",
            severity=AnomalySeverity.WARNING,
            title="Utility spending consumes most of declared income",
            message=(
                f"Monthly utility spending (PKR {avg_spend:,.0f}) is "
                f"{ratio:.0%} of declared household income "
                f"(PKR {total_income:,.0f})."
            ),
            evidence=evidence,
        )]
    if ratio > INCOME_BILL_INFO_RATIO:
        return [AnomalyFlag(
            code="INCOME_BILL_MISMATCH",
            severity=AnomalySeverity.INFO,
            title="High utility burden relative to income",
            message=(
                f"Monthly utility spending (PKR {avg_spend:,.0f}) is "
                f"{ratio:.0%} of declared household income "
                f"(PKR {total_income:,.0f}) — a heavy, but plausible, burden."
            ),
            evidence=evidence,
        )]
    return []


def _rule_luxury_tariff(utility_records: list, income_signals: list) -> list[AnomalyFlag]:
    """
    LUXURY_TARIFF_INDICATOR — luxury-tier electricity consumption while
    claiming extreme-low income.

    Consumption is estimated from the electricity bill at a blended tariff
    (UtilityRecord does not persist meter units), and "extreme need" is the
    declared household income falling below LOW_INCOME_THRESHOLD_PKR.
    """
    total_income = _total_declared_income(income_signals)
    if total_income is None or total_income >= LOW_INCOME_THRESHOLD_PKR:
        return []

    avg_electricity = _electricity_avg_bill(utility_records)
    if avg_electricity is None or avg_electricity <= 0:
        return []

    estimated_units = avg_electricity / AVG_TARIFF_PER_KWH
    if estimated_units <= LUXURY_UNITS_THRESHOLD:
        return []

    return [AnomalyFlag(
        code="LUXURY_TARIFF_INDICATOR",
        severity=AnomalySeverity.WARNING,
        title="Luxury consumption contradicts extreme-need claim",
        message=(
            f"Electricity bills imply roughly {estimated_units:,.0f} kWh of "
            f"monthly consumption — luxury-tier usage — while declared income "
            f"(PKR {total_income:,.0f}/month) signals extreme need."
        ),
        evidence={
            "avg_electricity_bill_pkr": round(avg_electricity, 2),
            "estimated_units_kwh": round(estimated_units, 1),
            "assumed_tariff_pkr_per_kwh": AVG_TARIFF_PER_KWH,
            "units_threshold": LUXURY_UNITS_THRESHOLD,
            "total_declared_income_pkr": round(total_income, 2),
        },
    )]


def _rule_chronic_default(utility_records: list) -> list[AnomalyFlag]:
    """
    CHRONIC_DEFAULT_BURDEN — accumulated arrears vs the monthly bill.

    Ladder: arrears above one monthly bill → INFO (accumulating arrears
    worth monitoring), above two → WARNING (chronic default, or a
    landlord/tenant billing dispute).
    """
    avg_spend = _avg_monthly_utility_spend(utility_records)
    if avg_spend is None or avg_spend <= 0:
        return []

    arrears = _total_outstanding(utility_records)
    if arrears <= 0:
        return []

    multiple = arrears / avg_spend
    evidence = {
        "estimated_arrears_pkr": round(arrears, 2),
        "avg_monthly_utility_spend_pkr": round(avg_spend, 2),
        "arrears_to_bill_multiple": round(multiple, 2),
    }

    if multiple > ARREARS_WARNING_MULTIPLE:
        return [AnomalyFlag(
            code="CHRONIC_DEFAULT_BURDEN",
            severity=AnomalySeverity.WARNING,
            title="Arrears far exceed the monthly bill",
            message=(
                f"Accumulated utility arrears (est. PKR {arrears:,.0f}) are "
                f"{multiple:.1f}x the average monthly bill "
                f"(PKR {avg_spend:,.0f}) — chronic default or a possible "
                f"landlord/tenant billing dispute."
            ),
            evidence=evidence,
        )]
    if multiple > ARREARS_INFO_MULTIPLE:
        return [AnomalyFlag(
            code="CHRONIC_DEFAULT_BURDEN",
            severity=AnomalySeverity.INFO,
            title="Arrears accumulating",
            message=(
                f"Utility arrears (est. PKR {arrears:,.0f}) have reached "
                f"{multiple:.1f}x the average monthly bill "
                f"(PKR {avg_spend:,.0f}) and are worth monitoring."
            ),
            evidence=evidence,
        )]
    return []


def _rule_income_evidence_gap(income_signals: list) -> list[AnomalyFlag]:
    """
    INCOME_EVIDENCE_GAP — an extreme-need or daily-wager income claim with
    no documented or verified proof behind it.
    """
    if not income_signals:
        return []
    if _has_documented_income(income_signals):
        return []

    total_income = _total_declared_income(income_signals)
    extreme_need = (
        total_income is not None and total_income < LOW_INCOME_THRESHOLD_PKR
    )
    daily_wager = any(
        s.source_type == IncomeSourceType.INFORMAL_WORK for s in income_signals
    )
    if not (extreme_need or daily_wager):
        return []

    if extreme_need and daily_wager:
        message = (
            f"An extreme-need income claim (PKR {total_income:,.0f}/month, "
            f"daily-wager work) is backed only by self-declaration, with no "
            f"documented or verified proof."
        )
    elif extreme_need:
        message = (
            f"An extreme-need income claim (PKR {total_income:,.0f}/month) "
            f"is backed only by self-declaration, with no documented or "
            f"verified proof."
        )
    else:
        message = (
            "Daily-wager income is claimed without documented or verified "
            "proof — the amount cannot be corroborated from the file."
        )

    return [AnomalyFlag(
        code="INCOME_EVIDENCE_GAP",
        severity=AnomalySeverity.WARNING,
        title="Income claim lacks documentary proof",
        message=message,
        evidence={
            "total_declared_income_pkr": (
                round(total_income, 2) if total_income is not None else None
            ),
            "extreme_need_claim": extreme_need,
            "daily_wager_claim": daily_wager,
            "has_documented_evidence": False,
        },
    )]


def _rule_academic_discordance(academic_records: list) -> list[AnomalyFlag]:
    """
    ACADEMIC_MERIT_DISCORDANCE — high academic claim vs other submitted
    results, or a value that is impossible on its declared scale.
    """
    if not academic_records:
        return []

    # (a) Scale-impossible values — the marksheet data contradicts itself.
    for r in academic_records:
        if r.result_value is None or r.result_scale is None:
            continue
        scale = (
            r.result_scale.value
            if hasattr(r.result_scale, "value") else r.result_scale
        )
        value = float(r.result_value)
        impossible = (
            (scale == ResultScale.PERCENTAGE.value and value > 100)
            or (scale == ResultScale.GPA.value and value > 4.0)
            or (
                scale == ResultScale.DIVISION.value
                and value not in (1.0, 2.0, 3.0)
            )
        )
        if impossible:
            return [AnomalyFlag(
                code="ACADEMIC_MERIT_DISCORDANCE",
                severity=AnomalySeverity.WARNING,
                title="Marksheet value impossible on its scale",
                message=(
                    f"A submitted result records {value:g} on a {scale} "
                    f"scale, which exceeds what that scale allows — the "
                    f"marksheet data is internally inconsistent."
                ),
                evidence={
                    "result_value": value,
                    "result_scale": scale,
                    "qualification_level": (
                        r.qualification_level.value
                        if hasattr(r.qualification_level, "value")
                        else r.qualification_level
                    ),
                },
            )]

    # (b) Merit trajectory discordance — best result > 85% while another
    # submitted result collapses by 30+ points.
    normalised = [
        (r, _normalise_result(r.result_value, r.result_scale))
        for r in academic_records
    ]
    normalised = [(r, v) for r, v in normalised if v is not None]
    if len(normalised) < 2:
        return []

    best_rec, best = max(normalised, key=lambda rv: rv[1])
    if best <= HIGH_MERIT_THRESHOLD:
        return []

    worst_rec, worst = min(normalised, key=lambda rv: rv[1])
    if best - worst < MERIT_DROP_THRESHOLD:
        return []

    return [AnomalyFlag(
        code="ACADEMIC_MERIT_DISCORDANCE",
        severity=AnomalySeverity.WARNING,
        title="Academic results conflict with each other",
        message=(
            f"The best submitted result ({best:.0%}) conflicts with another "
            f"submitted result ({worst:.0%}) — a {(best - worst):.0%} decline "
            f"that is atypical for a genuine merit trajectory."
        ),
        evidence={
            "best_result_normalised": round(best, 3),
            "best_qualification": (
                best_rec.qualification_level.value
                if hasattr(best_rec.qualification_level, "value")
                else best_rec.qualification_level
            ),
            "conflicting_result_normalised": round(worst, 3),
            "conflicting_qualification": (
                worst_rec.qualification_level.value
                if hasattr(worst_rec.qualification_level, "value")
                else worst_rec.qualification_level
            ),
            "drop": round(best - worst, 3),
        },
    )]


def _rule_dependency_inflation(applicant, income_signals: list) -> list[AnomalyFlag]:
    """
    DEPENDENCY_INFLATION — a large declared household with no multi-earner
    or elder-income evidence to corroborate it.
    """
    dependants = getattr(applicant, "dependants", None)
    if dependants is None or dependants <= DEPENDANTS_THRESHOLD:
        return []

    earners = sum(
        1
        for s in income_signals
        if s.declared_monthly_amount is not None
        and s.declared_monthly_amount > 0
    )
    if earners > 1:
        return [] # Multiple income sources corroborate a multi-family home.

    return [AnomalyFlag(
        code="DEPENDENCY_INFLATION",
        severity=AnomalySeverity.WARNING,
        title="Large household without supporting income evidence",
        message=(
            f"{dependants} dependants are declared against "
            f"{earners} income source{'s' if earners == 1 else ''}, with no "
            f"multi-earner or elder-income evidence to corroborate the "
            f"household size."
        ),
        evidence={
            "declared_dependants": dependants,
            "income_sources_with_amounts": earners,
        },
    )]


# ── Risk aggregation ─────────────────────────────────────────────────────────


def _risk_score(flags: list[AnomalyFlag]) -> float:
    return float(min(100, sum(_SEVERITY_WEIGHTS[f.severity] for f in flags)))


def _risk_level(flags: list[AnomalyFlag], score: float) -> RiskLevel:
    if not flags:
        return RiskLevel.CLEAN
    if any(f.severity == AnomalySeverity.CRITICAL for f in flags):
        return RiskLevel.CRITICAL_MISMATCH
    warnings = sum(1 for f in flags if f.severity == AnomalySeverity.WARNING)
    if warnings >= 2 or score >= 50:
        return RiskLevel.HIGH_SUSPICION
    if warnings == 1:
        return RiskLevel.MODERATE_FLAG
    return RiskLevel.LOW_RISK


# ── Policy recommendation ────────────────────────────────────────────────────


def _support_package(action: PolicyActionType, score: float | None) -> str:
    """Map the action (and score, when known) to a concrete support package."""
    if action in (PolicyActionType.FIELD_AUDIT_REQUIRED,
                  PolicyActionType.HIGH_RISK_REJECT):
        return "Physical Verification Required"
    if action == PolicyActionType.STANDARD_REVIEW:
        return "Partial Fee Support (50%)"
    # AUTO_APPROVE — tiered by the Sahaara Score itself.
    if score is None:
        return "Partial Fee Support (50%)"
    if score >= 60:
        return "Full Merit-Need Scholarship (100% Tuition)"
    if score >= 35:
        return "Partial Fee Support (50%)"
    return "Emergency Micro-Grant"


def _build_recommendation(
    flags: list[AnomalyFlag],
    risk_level: RiskLevel,
    risk_score: float,
    score: float | None,
    confidence: ConfidenceLevel | None,
) -> PolicyRecommendation:
    criticals = [f for f in flags if f.severity == AnomalySeverity.CRITICAL]
    warnings = [f for f in flags if f.severity == AnomalySeverity.WARNING]
    score_str = f"{score:.0f}" if score is not None else "not yet computed"
    conf_str = confidence.value if confidence else "unknown"

    # ── Action ──────────────────────────────────────────────────────────
    if risk_level in (RiskLevel.CLEAN, RiskLevel.LOW_RISK):
        # A clean file on thin data is still not auto-approvable — the
        # anomaly shield says nothing is contradictory, not that enough
        # evidence exists. LOW confidence caps at standard review.
        action = (
            PolicyActionType.STANDARD_REVIEW
            if confidence == ConfidenceLevel.LOW
            else PolicyActionType.AUTO_APPROVE
        )
    elif risk_level == RiskLevel.MODERATE_FLAG:
        action = PolicyActionType.STANDARD_REVIEW
    elif risk_level == RiskLevel.HIGH_SUSPICION:
        action = PolicyActionType.FIELD_AUDIT_REQUIRED
    else: # CRITICAL_MISMATCH
        action = (
            PolicyActionType.HIGH_RISK_REJECT
            if len(criticals) >= 2 or risk_score >= 90
            else PolicyActionType.FIELD_AUDIT_REQUIRED
        )

    support = _support_package(action, score)
    top_titles = ", ".join(f.title.lower() for f in flags[:_TOP_FLAGS_SHOWN])

    # ── Two-sentence justification for donors ───────────────────────────
    if action == PolicyActionType.AUTO_APPROVE:
        justification = (
            f"The applicant's file shows no data inconsistencies across "
            f"utility, academic, and income records. A Sahaara Score of "
            f"{score_str} with {conf_str} data confidence supports "
            f"{support.lower()}."
        )
    elif action == PolicyActionType.STANDARD_REVIEW and risk_level == RiskLevel.CLEAN:
        justification = (
            f"No data inconsistencies were detected, but the file is thin "
            f"({conf_str} data confidence) and warrants a standard review "
            f"before approval. Pending review, {support.lower()} is the "
            f"appropriate provisional package."
        )
    elif action == PolicyActionType.STANDARD_REVIEW:
        justification = (
            f"The file contains {len(warnings)} warning-level "
            f"inconsistenc{'y' if len(warnings) == 1 else 'ies'} "
            f"({top_titles}) that a reviewer should examine before "
            f"approval. Pending that review, {support.lower()} is the "
            f"appropriate provisional package."
        )
    elif action == PolicyActionType.HIGH_RISK_REJECT:
        justification = (
            f"The file contains {len(criticals)} critical "
            f"contradiction{'s' if len(criticals) != 1 else ''} "
            f"({top_titles}) that cannot be reconciled as submitted. "
            f"Support is withheld pending corrected documentation and "
            f"physical verification."
        )
    else: # FIELD_AUDIT_REQUIRED
        if criticals:
            justification = (
                f"The declared data contains a critical contradiction "
                f"({top_titles}) — the figures cannot all be accurate as "
                f"submitted. No support should be disbursed until physical "
                f"verification resolves the discrepancy."
            )
        else:
            justification = (
                f"Multiple inconsistencies ({top_titles}) make the declared "
                f"circumstances difficult to reconcile without on-the-ground "
                f"verification. Support should be conditional on a "
                f"successful field audit."
            )

    return PolicyRecommendation(
        action_type=action,
        recommended_support=support,
        summary_justification=justification,
    )


# ── Public API ───────────────────────────────────────────────────────────────


def detect_anomalies(
    applicant,
    utility_records: list,
    academic_records: list,
    income_signals: list,
    feature_set: FeatureSet,
    *,
    score: float | None = None,
    confidence: ConfidenceLevel | None = None,
) -> AnomalyReport:
    """
    Run every fraud-shield rule over an applicant's file.

    ``score`` and ``confidence`` are optional context from the scoring run:
    the recommendation's support package is tiered by the Sahaara Score and
    never auto-approves a thin file. Both default to unknown, in which case
    the recommendation leans conservative.

    Returns an :class:`AnomalyReport` with flags, a 0-100 risk score, an
    overall risk level, the audit requirement, and the policy recommendation.
    """
    utility_records = utility_records or []
    academic_records = academic_records or []
    income_signals = income_signals or []

    flags: list[AnomalyFlag] = []
    for rule in (
        lambda: _rule_income_bill_mismatch(utility_records, income_signals),
        lambda: _rule_luxury_tariff(utility_records, income_signals),
        lambda: _rule_chronic_default(utility_records),
        lambda: _rule_income_evidence_gap(income_signals),
        lambda: _rule_academic_discordance(academic_records),
        lambda: _rule_dependency_inflation(applicant, income_signals),
    ):
        try:
            flags.extend(rule())
        except Exception as exc: # noqa: BLE001 — one bad rule never blocks scoring
            logger.warning(
                "Anomaly rule failed (%s: %s) — continuing with remaining "
                "rules.", type(exc).__name__, exc,
            )

    # Most severe first so ``flags[:n]`` is the reviewer-facing summary.
    flags.sort(
        key=lambda f: _SEVERITY_RANK[f.severity], reverse=True,
    )

    risk_score = _risk_score(flags)
    risk_level = _risk_level(flags, risk_score)
    audit_required = risk_level in (RiskLevel.HIGH_SUSPICION,
                                    RiskLevel.CRITICAL_MISMATCH)
    recommendation = _build_recommendation(
        flags, risk_level, risk_score, score, confidence,
    )

    return AnomalyReport(
        flags=flags,
        risk_score=risk_score,
        risk_level=risk_level,
        audit_required=audit_required,
        recommendation=recommendation,
    )
