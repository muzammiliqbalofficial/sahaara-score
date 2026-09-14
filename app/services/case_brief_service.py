"""
Case brief service — bilingual synthesis of any applicant's assessment.

Generates two parallel narratives from the same data:

  * ``english_brief`` — executive briefing for NGO / donor reviewers with
    key strengths, vulnerability profile, contradiction analysis, and a
    clear directive.
  * ``urdu_brief`` — empathetic, plain-language Urdu explanation
    (وضاحتی خلاصہ) for the applicant so they understand *why* a decision
    was reached, in their own language.

Both briefs are accompanied by a ``recommended_award_package`` mapping the
anomaly engine's recommendation to a concrete disbursement schedule with
conditions.

Qwen integration
────────────────
When ``DASHSCOPE_API_KEY`` is configured the service sends a structured
context block to Alibaba Cloud DashScope (OpenAI-compatible chat endpoint)
and lets Qwen-Max synthesise natural prose. Without a key — or when the
API call fails — the service falls back to deterministic template
generation seeded by the same assessment data. Every result reports its
``mode`` ('qwen' or 'template') so the caller can show provenance.

The deterministic fallback is intentionally detailed: it reads feature
contributions, anomaly flags, score, and band directly, so even offline
briefs are specific and audit-ready — never generic boilerplate.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()

# DashScope OpenAI-compatible chat endpoint (text generation).
_DASHSCOPE_CHAT_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
)

# Model for text synthesis (Qwen-VL is multimodal; Qwen-Max is text).
_TEXT_MODEL = "qwen-max"
_REQUEST_TIMEOUT = 45.0


# ── Public API ────────────────────────────────────────────────────────────────


def generate_case_brief(
    assessment_data: dict[str, Any],
    applicant_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Produce a bilingual case brief for one scored applicant.

    ``assessment_data`` is the JSONB-shaped dict returned by
    :func:`score_applicant` (or loaded from the ``anomaly_report`` column
    plus the flat score / band / confidence fields).

    ``applicant_data`` is optional extra context (city, applicant type,
    identity reference) for richer narrative.

    Returns a dict matching :class:`CaseBriefResponse`::

        {
            "english_brief": {
                "key_strengths": "...",
                "vulnerability_profile": "...",
                "contradiction_analysis": "...",
                "directive": "...",
            },
            "urdu_brief": "...",
            "recommended_award_package": {
                "tier": "...",
                "conditions": ["...", ...],
                "disbursement_schedule": "...",
            },
            "mode": "template" | "qwen",
        }
    """
    ctx = _build_context(assessment_data, applicant_data)

    api_key = _settings.dashscope_api_key
    if api_key:
        try:
            result = _call_qwen(ctx, api_key)
            result["mode"] = "qwen"
            return result
        except Exception as exc: # noqa: BLE001
            logger.warning(
                "Qwen case-brief generation failed (%s: %s) — falling back "
                "to deterministic template.",
                type(exc).__name__,
                exc,
            )

    return _build_template_brief(ctx)


# ── Context assembly ─────────────────────────────────────────────────────────


def _build_context(
    assessment: dict[str, Any],
    applicant: dict[str, Any] | None,
) -> dict[str, Any]:
    """Flatten assessment + applicant into a narrative-ready context dict."""
    anomaly = assessment.get("anomaly_report") or {}
    rec = anomaly.get("recommendation") or {}
    flags = anomaly.get("flags", [])
    contributions = assessment.get("feature_contributions") or []

    # Top positive and negative features.
    pos = [c for c in contributions if c.get("direction") == "positive"]
    neg = [c for c in contributions if c.get("direction") == "negative"]
    pos.sort(key=lambda c: abs(c.get("contribution", 0)), reverse=True)
    neg.sort(key=lambda c: abs(c.get("contribution", 0)), reverse=True)

    return {
        "score": assessment.get("score", 0),
        "band": _val(assessment.get("band")),
        "confidence": _val(assessment.get("confidence_level")),
        "is_rule_based": assessment.get("is_rule_based", True),
        "signal_categories": assessment.get("signal_categories_count", 0),
        "non_null_features": assessment.get("non_null_feature_count", 0),
        # Anomaly shield.
        "risk_score": anomaly.get("risk_score", 0),
        "risk_level": anomaly.get("risk_level", "clean"),
        "audit_required": anomaly.get("audit_required", False),
        "flags": flags,
        "action_type": rec.get("action_type", "standard_review"),
        "recommended_support": rec.get("recommended_support", ""),
        "justification": rec.get("summary_justification", ""),
        # Feature contributions.
        "top_strengths": pos[:3],
        "top_weaknesses": neg[:3],
        # Applicant demographics.
        "city": (applicant or {}).get("city"),
        "applicant_type": (applicant or {}).get("applicant_type"),
    }


def _val(v: Any) -> str:
    """Unwrap an enum or value to a plain string."""
    if v is None:
        return "unknown"
    return v.value if hasattr(v, "value") else str(v)


# ── Qwen API call ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a bilingual policy analyst for Sahaara Score, an alternative "
    "credit scoring platform for financially invisible Pakistanis. You "
    "write clear, evidence-based case briefs for institutional donors "
    "(English) and empathetic, plain-language explanations for applicants "
    "(Urdu). Use the data provided; never invent facts."
)

_USER_TEMPLATE = """\
Applicant profile:
- Sahaara Score: {score:.1f} ({band}, {confidence} confidence)
- Scoring path: {scoring_path}
- Signal categories: {signal_categories}, Non-null features: {non_null_features}/8
- Anomaly risk: {risk_level} (score {risk_score:.0f}/100), audit required: {audit}
- Recommended action: {action_type}
- Recommended support: {recommended_support}

Key strengths (feature contributions):
{strengths_text}

Key weaknesses (feature contributions):
{weaknesses_text}

Anomaly flags detected ({flag_count}):
{flags_text}

Policy justification: {justification}

{city_line}
Produce a JSON object with exactly these keys:
{{
  "english_brief": {{
    "key_strengths": "2-3 sentence summary of positive signals",
    "vulnerability_profile": "2-3 sentence summary of risk factors",
    "contradiction_analysis": "2-3 sentences on any flagged contradictions",
    "directive": "1-2 sentence clear recommendation"
  }},
  "urdu_brief": "4-6 sentences in Urdu (Nastaliq script) explaining the assessment to the applicant in an empathetic, respectful tone",
  "recommended_award_package": {{
    "tier": "exact support package name",
    "conditions": ["condition 1", "condition 2"],
    "disbursement_schedule": "one-line disbursement timeline"
  }}
}}
Return ONLY the JSON object — no markdown fences, no commentary."""


def _call_qwen(
    ctx: dict[str, Any], api_key: str,
) -> dict[str, Any]:
    """Send the context to Qwen-Max via DashScope chat completions."""
    strengths_text = "\n".join(
        f"- {c.get('feature', '?').replace('_', ' ').title()}: "
        f"+{c.get('contribution', 0):.1f} ({c.get('explanation', '')})"
        for c in ctx["top_strengths"]
    ) or "None identified."

    weaknesses_text = "\n".join(
        f"- {c.get('feature', '?').replace('_', ' ').title()}: "
        f"{c.get('contribution', 0):.1f} ({c.get('explanation', '')})"
        for c in ctx["top_weaknesses"]
    ) or "None identified."

    flags = ctx["flags"]
    flags_text = "\n".join(
        f"- [{f.get('severity', '?').upper()}] {f.get('title', f.get('code', '?'))}: "
        f"{f.get('message', '')}"
        for f in flags
    ) if flags else "No anomalies detected."

    city_line = (
        f"City: {ctx['city']}" if ctx.get("city") else ""
    )

    user_msg = _USER_TEMPLATE.format(
        score=ctx["score"],
        band=ctx["band"],
        confidence=ctx["confidence"],
        scoring_path="Rule-based" if ctx["is_rule_based"] else "ML model",
        signal_categories=ctx["signal_categories"],
        non_null_features=ctx["non_null_features"],
        risk_level=ctx["risk_level"],
        risk_score=ctx["risk_score"],
        audit="Yes" if ctx["audit_required"] else "No",
        action_type=ctx["action_type"],
        recommended_support=ctx["recommended_support"],
        strengths_text=strengths_text,
        weaknesses_text=weaknesses_text,
        flag_count=len(flags),
        flags_text=flags_text,
        justification=ctx["justification"] or "N/A",
        city_line=city_line,
    )

    resp = httpx.post(
        _DASHSCOPE_CHAT_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": _TEXT_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)

    return {
        "english_brief": parsed["english_brief"],
        "urdu_brief": parsed["urdu_brief"],
        "recommended_award_package": parsed["recommended_award_package"],
    }


# ── Deterministic template fallback ──────────────────────────────────────────


def _build_template_brief(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Build a complete bilingual brief from templates and the assessment data.

    Every sentence is constructed from actual numbers in the file — no
    generic filler. The result is deterministic for the same input.
    """
    score = ctx["score"]
    band = ctx["band"]
    risk_level = ctx["risk_level"]
    risk_score = ctx["risk_score"]
    action = ctx["action_type"]
    support = ctx["recommended_support"]
    flags = ctx["flags"]
    strengths = ctx["top_strengths"]
    weaknesses = ctx["top_weaknesses"]
    confidence = ctx["confidence"]
    city = ctx.get("city")

    # ── English brief ────────────────────────────────────────────────────

    # Key strengths.
    if strengths:
        strength_phrases = ", ".join(
            f"{c['feature'].replace('_', ' ')} "
            f"(+{c['contribution']:.1f})"
            for c in strengths
        )
        key_strengths = (
            f"The applicant demonstrates measurable strengths across "
            f"{len(strengths)} scoring factor{'s' if len(strengths) != 1 else ''}: "
            f"{strength_phrases}. "
        )
    else:
        key_strengths = (
            "The scoring engine did not identify strong positive signals, "
            "typically because insufficient data categories were submitted. "
        )

    if confidence == "high":
        key_strengths += (
            f"High data confidence across {ctx['signal_categories']} signal "
            f"categories reinforces the reliability of this assessment."
        )
    elif confidence == "medium":
        key_strengths += (
            "Data confidence is moderate — additional documentation would "
            "strengthen the profile further."
        )
    else:
        key_strengths += (
            "The file is thin (low data confidence), so this score should "
            "be treated as indicative rather than definitive."
        )

    # Vulnerability profile.
    if weakness_text := _vulnerability_text(weaknesses, score, band):
        vulnerability_profile = weakness_text
    else:
        vulnerability_profile = (
            f"With a Sahaara Score of {score:.1f} ({band} band) and no "
            f"negative signals, the applicant's vulnerability profile is "
            f"low. "
        )

    if city:
        vulnerability_profile += f" Applicant is based in {city}."

    # Contradiction analysis.
    if flags:
        flag_parts = []
        for f in flags[:3]:
            sev = f.get("severity", "info").upper()
            title = f.get("title", f.get("code", "Unknown"))
            flag_parts.append(f"[{sev}] {title}")
        contradiction_analysis = (
            f"The fraud shield detected {len(flags)} "
            f"anomal{'y' if len(flags) == 1 else 'ies'}: "
            f"{', '.join(flag_parts)}. "
        )
        if risk_score >= 50:
            contradiction_analysis += (
                f"At risk score {risk_score:.0f}/100, these contradictions "
                f"make the declared circumstances difficult to reconcile "
                f"without further verification."
            )
        else:
            contradiction_analysis += (
                "These observations are noted but do not fundamentally "
                "undermine the overall assessment."
            )
    else:
        contradiction_analysis = (
            "No data contradictions were detected — utility, academic, "
            "and income records are internally consistent."
        )

    # Directive.
    directive = _directive_text(action, support, score, band)

    english_brief = {
        "key_strengths": key_strengths,
        "vulnerability_profile": vulnerability_profile,
        "contradiction_analysis": contradiction_analysis,
        "directive": directive,
    }

    # ── Urdu brief ───────────────────────────────────────────────────────

    urdu_brief = _build_urdu_brief(score, band, risk_level, action, support, flags)

    # ── Recommended award package ────────────────────────────────────────

    award = _build_award_package(action, support, score, band, risk_level)

    return {
        "english_brief": english_brief,
        "urdu_brief": urdu_brief,
        "recommended_award_package": award,
        "mode": "template",
    }


# ── Section builders ─────────────────────────────────────────────────────────


def _vulnerability_text(
    weaknesses: list[dict], score: float, band: str,
) -> str | None:
    if not weaknesses:
        return None

    phrases = []
    for c in weaknesses[:3]:
        feat = c["feature"].replace("_", " ")
        phrases.append(
            f"{feat} ({c['contribution']:.1f}: {c.get('explanation', '')})"
        )
    text = (
        f"With a Sahaara Score of {score:.1f} ({band} band), the scoring "
        f"engine identified risk factors in: {'; '.join(phrases)}. "
    )
    if score < 35:
        text += (
            "This low score reflects significant financial stress signals "
            "that require attention."
        )
    elif score < 60:
        text += (
            "These moderate signals suggest the household is under pressure "
            "but retains some financial resilience."
        )
    return text


def _directive_text(
    action: str, support: str, score: float, band: str,
) -> str:
    if action == "auto_approve":
        return (
            f"The file is clear for streamlined approval. Recommend "
            f"disbursing {support} with standard monitoring."
        )
    if action == "standard_review":
        return (
            f"A desk review is recommended before disbursement. Pending "
            f"approval, the appropriate support tier is {support}."
        )
    if action == "field_audit_required":
        return (
            f"Field verification is required before any disbursement. "
            f"Proposed support package: {support}, contingent on audit "
            f"clearance."
        )
    # high_risk_reject
    return (
        "The file contains contradictions that cannot be reconciled as "
        "submitted. Support is withheld pending corrected documentation "
        "and physical verification."
    )


def _build_urdu_brief(
    score: float,
    band: str,
    risk_level: str,
    action: str,
    support: str,
    flags: list[dict],
) -> str:
    """
    Construct an empathetic Urdu explanation for the applicant.

    The text uses respectful, plain-language Urdu (Nastaliq-compatible)
    so the applicant understands why this assessment was reached.
    """
    # Score line.
    score_line = (
        f"آپ کا سہارا اسکور {score:.1f} ہے ({band} بینڈ)۔"
    )

    # Strength or weakness.
    if score >= 60:
        body = (
            "آپ کی ادائیگی کی تاریخ اور دستاویزات اچھی حالت میں ہیں۔ "
            "یہ اسکور ظاہر کرتا ہے کہ آپ مالی ذمہ داری کا مظاہرہ کر رہے ہیں۔"
        )
    elif score >= 35:
        body = (
            "آپ کے اسکور سے ظاہر ہوتا ہے کہ آپ کی مالی صورتحال میں کچھ "
            "بہتری کی گنجائش ہے۔ ہم آپ کی مدد کرنا چاہتے ہیں۔"
        )
    else:
        body = (
            "آپ کا اسکور کم ہے جس کا مطلب ہے کہ آپ کو مالی مشکلات کا "
            "سامنا ہے۔ ہم آپ کی صورتحال کو بہتر بنانے میں مدد فراہم "
            "کرنا چاہتے ہیں۔"
        )

    # Flags / contradictions.
    if flags:
        flag_note = (
            f"ہمارے نظام نے آپ کی فائل میں {len(flags)} "
            f"{'معلوماتی تضاد' if len(flags) == 1 else 'معلوماتی تضادات'} "
            f"کی نشاندہی کی ہے جن کی تصدیق ضروری ہے۔"
        )
    else:
        flag_note = "آپ کی دستاویزات میں کوئی تضاد نہیں پایا گیا۔"

    # Recommendation.
    if action == "auto_approve":
        rec_urdu = (
            f"آپ کی درخواست منظور ہونے کے لیے تیار ہے۔ "
            f"تجویز کردہ معاونت: {support}۔"
        )
    elif action == "standard_review":
        rec_urdu = (
            "آپ کی فائل کا جائزہ لیا جا رہا ہے۔ "
            f"منظوری کے بعد تجویز کردہ معاونت: {support}۔"
        )
    elif action == "field_audit_required":
        rec_urdu = (
            "آپ کی فائل کی تصدیق کے لیے فیلڈ وزٹ کی ضرورت ہے۔ "
            "تصدیق کے بعد معاونت فراہم کی جائے گی۔"
        )
    else:
        rec_urdu = (
            "آپ کی فائل میں اہم تضادات پائے گئے ہیں۔ "
            "براہ کرم درست دستاویزات دوبارہ جمع کروائیں۔"
        )

    return f"{score_line} {body} {flag_note} {rec_urdu}"


def _build_award_package(
    action: str,
    support: str,
    score: float,
    band: str,
    risk_level: str,
) -> dict[str, Any]:
    """Map the anomaly recommendation to a concrete disbursement package."""
    if action == "auto_approve":
        if score >= 60:
            tier = "Full Merit-Need Scholarship"
            conditions = [
                "Maintain ≥ 80% attendance each semester",
                "Submit semester progress reports",
            ]
            schedule = "Full tuition disbursed at start of each semester"
        elif score >= 35:
            tier = "Partial Fee Support (50%)"
            conditions = [
                "Maintain ≥ 75% attendance",
                "Submit quarterly progress updates",
            ]
            schedule = "50% tuition disbursed at start, 50% mid-semester"
        else:
            tier = "Emergency Micro-Grant"
            conditions = [
                "One-time disbursement with no recurring obligation",
                "Post-disbursement welfare check at 30 days",
            ]
            schedule = "Single lump-sum disbursement within 7 business days"
    elif action == "standard_review":
        tier = support or "Partial Fee Support (50%)"
        conditions = [
            "Desk review approval required before disbursement",
            "Applicant may be asked for additional documentation",
        ]
        schedule = "Disbursement within 14 days of review clearance"
    elif action == "field_audit_required":
        tier = "Conditional — Pending Field Audit"
        conditions = [
            "Physical verification of declared household and income",
            "Audit report must clear all flagged contradictions",
            "Support package determined post-audit",
        ]
        schedule = "Disbursement within 30 days of audit clearance"
    else: # high_risk_reject
        tier = "Suspended — Documentation Required"
        conditions = [
            "Applicant must resubmit corrected documentation",
            "All contradictions must be resolved before reconsideration",
            "No disbursement until file is re-assessed and cleared",
        ]
        schedule = "N/A — file is suspended pending resubmission"

    return {
        "tier": tier,
        "conditions": conditions,
        "disbursement_schedule": schedule,
    }
