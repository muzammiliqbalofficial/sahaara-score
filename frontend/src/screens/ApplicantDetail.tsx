import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useApplicantDetail, useSubmitDecision, useCaseBrief } from "../api/hooks";
import type {
  DecisionCreate, DecisionOutcome, FeatureContribution,
  AnomalyFlagSchema, AnomalyReportSchema, CaseBriefResponse,
} from "../api/types";
import ConfidenceBadge from "../components/ConfidenceBadge";
import { maskCnic } from "../lib/format";
import {
  ArrowLeft, ShieldCheck, ShieldAlert,
  FileText, Printer, ChevronDown, ChevronUp,
  Zap, GraduationCap, Banknote, CheckCircle2, XCircle,
  Sparkles, Languages,
} from "lucide-react";

/* ── helpers ──────────────────────────────────────────────────────────── */

const bandColor: Record<string, string> = {
  strong: "text-green-800 bg-green-50 ring-green-200",
  moderate: "text-amber-800 bg-amber-50 ring-amber-200",
  low: "text-red-800 bg-red-50 ring-red-200",
};

const sevBadge: Record<string, string> = {
  critical: "sev-badge-critical",
  warning: "sev-badge-warning",
  info: "sev-badge-info",
};

function fmtDate(d: string | null | undefined) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString();
}

/* ── Score Gauge (SVG ring) ─────────────────────────────────────────── */

function ScoreGauge({ score, band, confidence, categories, features, isRuleBased }: {
  score: number; band: string; confidence: string;
  categories: number; features: number; isRuleBased: boolean;
}) {
  const radius = 60;
  const circ = 2 * Math.PI * radius;
  const offset = circ - (score / 100) * circ;
  const color = score >= 60 ? "#16a34a" : score >= 35 ? "#d97706" : "#dc2626";

  return (
    <div className="card flex flex-col items-center sm:flex-row sm:items-start sm:gap-8">
      <div className="score-ring h-40 w-40 shrink-0">
        <svg className="h-full w-full -rotate-90" viewBox="0 0 140 140">
          <circle cx="70" cy="70" r={radius} fill="none" stroke="#e5e7eb" strokeWidth="12" />
          <circle
            cx="70" cy="70" r={radius} fill="none"
            stroke={color} strokeWidth="12" strokeLinecap="round"
            strokeDasharray={circ} strokeDashoffset={offset}
            className="transition-all duration-700"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-mono text-4xl font-bold tabular-nums" style={{ color }}>{score.toFixed(0)}</span>
          <span className={`mt-0.5 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${bandColor[band] ?? ""}`}>
            {band}
          </span>
        </div>
      </div>

      <div className="mt-4 flex-1 sm:mt-0">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <ConfidenceBadge level={confidence as "high" | "medium" | "low"} signalCount={categories} featureCount={features} />
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
            {isRuleBased ? "Rule-based" : "ML model"}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-gray-500">
          <span>Signal categories: <b className="text-gray-700">{categories}</b></span>
          <span>Features used: <b className="text-gray-700">{features}/8</b></span>
        </div>
      </div>
    </div>
  );
}

/* ── Category Breakdown ─────────────────────────────────────────────── */

function CategoryBreakdown({ contributions }: { contributions: FeatureContribution[] }) {
  if (!contributions?.length) return null;

  const groups: Record<string, FeatureContribution[]> = {};
  for (const c of contributions) {
    const cat = c.feature.includes("payment") || c.feature.includes("streak") || c.feature.includes("days_late") || c.feature.includes("consistency")
      ? "Payment Reliability"
      : c.feature.includes("academic")
        ? "Academic Signal"
        : c.feature.includes("household")
          ? "Household Burden"
          : c.feature.includes("income")
            ? "Income Confidence"
            : "Other";
    (groups[cat] ??= []).push(c);
  }

  const catColors: Record<string, string> = {
    "Payment Reliability": "bg-blue-500",
    "Academic Signal": "bg-purple-500",
    "Household Burden": "bg-amber-500",
    "Income Confidence": "bg-green-500",
    "Other": "bg-gray-400",
  };

  return (
    <div className="card">
      <h2 className="mb-3">Category Breakdown</h2>
      <div className="space-y-3">
        {Object.entries(groups).map(([cat, items]) => {
          const totalContrib = items.reduce((s, c) => s + c.contribution, 0);
          const pct = Math.min(Math.abs(totalContrib) * 3, 100);
          return (
            <div key={cat}>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="font-medium text-gray-700">{cat}</span>
                <span className="font-mono tabular-nums text-gray-500">
                  {totalContrib > 0 ? "+" : ""}{totalContrib.toFixed(1)}
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-gray-100">
                <div className={`h-2 rounded-full ${catColors[cat] ?? "bg-gray-400"}`} style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Factor Chart ───────────────────────────────────────────────────── */

function FactorChart({ contributions }: { contributions: FeatureContribution[] }) {
  if (!contributions?.length) return null;

  const withData = contributions.filter((c) => !c.no_data);
  const noData = contributions.filter((c) => c.no_data);
  const sorted = [...withData].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  const maxAbs = Math.max(...sorted.map((c) => Math.abs(c.contribution)), 0.01);

  return (
    <div className="card">
      <h2 className="mb-3">Contributing Factors</h2>
      <div className="space-y-3">
        {sorted.map((c) => {
          const pct = (Math.abs(c.contribution) / maxAbs) * 100;
          const isPos = c.direction === "positive";
          const isNeutral = c.direction === "neutral";
          const barColor = isNeutral ? "bg-gray-300" : isPos ? "bg-green-600" : "bg-red-600";

          return (
            <div key={c.feature}>
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-gray-700 capitalize">{c.feature.replace(/_/g, " ")}</span>
                <span className={`font-mono tabular-nums ${isPos ? "text-green-700" : isNeutral ? "text-gray-500" : "text-red-700"}`}>
                  {c.contribution.toFixed(1)}
                </span>
              </div>
              <div className="mt-0.5 h-2 w-full rounded-full bg-gray-100">
                <div className={`h-2 rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
              </div>
              {c.explanation && <p className="mt-0.5 text-xs text-gray-500">{c.explanation}</p>}
            </div>
          );
        })}
      </div>

      {noData.length > 0 && (
        <div className="mt-4 border-t border-gray-100 pt-3">
          <p className="mb-2 text-xs font-medium text-gray-500 uppercase">No data available</p>
          {noData.map((c) => (
            <p key={c.feature} className="text-xs text-gray-400">
              <span className="font-medium text-gray-500 capitalize">{c.feature.replace(/_/g, " ")}</span>
              {c.explanation && ` — ${c.explanation}`}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Anomaly & Fraud Shield Card ────────────────────────────────────── */

function AnomalyCard({ report }: { report: AnomalyReportSchema }) {
  const [expanded, setExpanded] = useState(true);
  const rec = report.recommendation;

  return (
    <div className="card">
      <button
        className="flex w-full items-center justify-between text-left"
        onClick={() => setExpanded((e) => !e)}
      >
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-blue-600" />
          <h2 className="text-base">Anomaly & Fraud Shield</h2>
          <span className={`risk-badge-${report.risk_level}`}>
            {report.risk_level.replace(/_/g, " ")}
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className="font-mono">{report.risk_score.toFixed(0)}/100</span>
          {report.audit_required && (
            <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700 ring-1 ring-red-200">
              Audit Required
            </span>
          )}
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>

      {expanded && (
        <div className="mt-4 space-y-3 animate-fade-in">
          {report.flags.length === 0 ? (
            <div className="flex items-center gap-2 rounded-lg bg-green-50 p-3 text-sm text-green-700 ring-1 ring-green-200">
              <ShieldCheck className="h-4 w-4" />
              No anomalies detected — file is clean.
            </div>
          ) : (
            <div className="space-y-2">
              {report.flags.map((f: AnomalyFlagSchema, i: number) => (
                <div key={i} className={`rounded-lg p-3 ring-1 ${
                  f.severity === "critical" ? "bg-red-50 ring-red-200"
                    : f.severity === "warning" ? "bg-amber-50 ring-amber-200"
                      : "bg-blue-50 ring-blue-200"
                }`}>
                  <div className="flex items-center gap-2">
                    <span className={sevBadge[f.severity] ?? ""}>{f.severity.toUpperCase()}</span>
                    <span className="text-sm font-medium text-gray-800">{f.title}</span>
                  </div>
                  <p className="mt-1 text-xs text-gray-600">{f.message}</p>
                  {f.evidence && Object.keys(f.evidence).length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-2 text-xs">
                      {Object.entries(f.evidence).slice(0, 4).map(([k, v]) => (
                        <span key={k} className="rounded bg-white/60 px-1.5 py-0.5 text-gray-600 ring-1 ring-gray-200">
                          {k.replace(/_/g, " ")}: <b>{typeof v === "number" ? v.toFixed(2) : String(v)}</b>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {rec && (
            <div className="rounded-lg bg-gray-50 p-3 ring-1 ring-gray-200">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-bold uppercase text-gray-500">Policy Recommendation</span>
                <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${
                  rec.action_type === "auto_approve" ? "bg-green-100 text-green-800"
                    : rec.action_type === "standard_review" ? "bg-amber-100 text-amber-800"
                      : "bg-red-100 text-red-800"
                }`}>
                  {rec.action_type.replace(/_/g, " ")}
                </span>
              </div>
              <p className="text-xs font-medium text-gray-700">{rec.recommended_support}</p>
              <p className="mt-1 text-xs text-gray-500">{rec.summary_justification}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Bilingual Case Brief Tab ───────────────────────────────────────── */

function CaseBriefTab({ assessmentId }: { assessmentId: string }) {
  const [lang, setLang] = useState<"en" | "ur">("en");
  const [brief, setBrief] = useState<CaseBriefResponse | null>(null);
  const mutation = useCaseBrief(assessmentId);

  const handleGenerate = () => {
    mutation.mutate(undefined, {
      onSuccess: (data) => setBrief(data),
    });
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-purple-600" />
          <h2>Bilingual AI Case Brief</h2>
          {brief && (
            <span className="rounded bg-purple-50 px-1.5 py-0.5 text-xs text-purple-600 ring-1 ring-purple-200">
              {brief.mode === "qwen" ? "Qwen AI" : "Template"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {!brief && (
            <button onClick={handleGenerate} disabled={mutation.isPending} className="btn-primary text-xs">
              {mutation.isPending ? "Generating…" : "Generate Brief"}
            </button>
          )}
          {brief && (
            <div className="flex rounded-lg bg-gray-100 p-0.5">
              <button
                onClick={() => setLang("en")}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${lang === "en" ? "bg-white shadow-sm" : "text-gray-500"}`}
              >
                English
              </button>
              <button
                onClick={() => setLang("ur")}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${lang === "ur" ? "bg-white shadow-sm" : "text-gray-500"}`}
              >
                <span className="inline-flex items-center gap-1"><Languages className="h-3 w-3" /> اردو</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {mutation.isError && (
        <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700 ring-1 ring-red-200">
          Failed to generate: {String(mutation.error)}
        </div>
      )}

      {brief && lang === "en" && (
        <div className="space-y-3 animate-fade-in">
          <BriefSection title="Key Strengths" text={brief.english_brief.key_strengths} />
          <BriefSection title="Vulnerability Profile" text={brief.english_brief.vulnerability_profile} />
          <BriefSection title="Contradiction Analysis" text={brief.english_brief.contradiction_analysis} />
          <BriefSection title="Directive" text={brief.english_brief.directive} />

          <div className="rounded-lg bg-blue-50 p-3 ring-1 ring-blue-200">
            <p className="text-xs font-bold text-blue-800 mb-1">Award Package: {brief.recommended_award_package.tier}</p>
            <ul className="text-xs text-blue-700 space-y-0.5">
              {brief.recommended_award_package.conditions.map((c, i) => (
                <li key={i}>• {c}</li>
              ))}
            </ul>
            <p className="mt-1 text-xs text-blue-600">{brief.recommended_award_package.disbursement_schedule}</p>
          </div>
        </div>
      )}

      {brief && lang === "ur" && (
        <div className="animate-fade-in">
          <div className="urdu-text rounded-lg bg-emerald-50 p-4 text-sm text-emerald-900 ring-1 ring-emerald-200 leading-loose">
            {brief.urdu_brief}
          </div>
          <div className="mt-3 rounded-lg bg-blue-50 p-3 ring-1 ring-blue-200">
            <p className="text-xs font-bold text-blue-800 mb-1">Award Package: {brief.recommended_award_package.tier}</p>
            <p className="text-xs text-blue-600">{brief.recommended_award_package.disbursement_schedule}</p>
          </div>
        </div>
      )}

      {!brief && !mutation.isPending && !mutation.isError && (
        <p className="text-xs text-gray-400">
          Click "Generate Brief" to create a bilingual synthesis of this assessment — an executive summary for donors and an empathetic Urdu explanation for the applicant.
        </p>
      )}
    </div>
  );
}

function BriefSection({ title, text }: { title: string; text: string }) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-500 uppercase mb-1">{title}</h3>
      <p className="text-sm text-gray-700 leading-relaxed">{text}</p>
    </div>
  );
}

/* ── Records Tables ─────────────────────────────────────────────────── */

function UtilityTable({ records }: { records: ReturnType<typeof useApplicantDetail>["data"] extends infer D ? D extends { utility_records: infer R } ? R : never : never }) {
  if (!records || records.length === 0) return null;
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-1.5"><Zap className="h-4 w-4 text-amber-600" />Utility Records ({records.length})</h3>
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200 text-xs">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-1.5 text-left font-medium text-gray-500">Type</th>
              <th className="px-3 py-1.5 text-left font-medium text-gray-500">Month</th>
              <th className="px-3 py-1.5 text-right font-medium text-gray-500">Billed</th>
              <th className="px-3 py-1.5 text-right font-medium text-gray-500">Paid</th>
              <th className="px-3 py-1.5 text-right font-medium text-gray-500">Days late</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {records.map((r) => (
              <tr key={r.id}>
                <td className="whitespace-nowrap px-3 py-1.5 capitalize">{r.utility_type ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-1.5">{fmtDate(r.billing_month)}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{r.amount_billed?.toFixed(0) ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{r.amount_paid?.toFixed(0) ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{r.days_late ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AcademicTable({ records }: { records: ReturnType<typeof useApplicantDetail>["data"] extends infer D ? D extends { academic_records: infer R } ? R : never : never }) {
  if (!records || records.length === 0) return null;
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-1.5"><GraduationCap className="h-4 w-4 text-purple-600" />Academic Records ({records.length})</h3>
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200 text-xs">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-1.5 text-left font-medium text-gray-500">Institution</th>
              <th className="px-3 py-1.5 text-left font-medium text-gray-500">Level</th>
              <th className="px-3 py-1.5 text-right font-medium text-gray-500">Result</th>
              <th className="px-3 py-1.5 text-left font-medium text-gray-500">Scale</th>
              <th className="px-3 py-1.5 text-right font-medium text-gray-500">Year</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {records.map((r) => (
              <tr key={r.id}>
                <td className="px-3 py-1.5">{r.institution ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-1.5 capitalize">{r.qualification_level ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{r.result_value?.toFixed(1) ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-1.5">{r.result_scale ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{r.year ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function IncomeTable({ records }: { records: ReturnType<typeof useApplicantDetail>["data"] extends infer D ? D extends { income_signals: infer R } ? R : never : never }) {
  if (!records || records.length === 0) return null;
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-1.5"><Banknote className="h-4 w-4 text-green-600" />Income Signals ({records.length})</h3>
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200 text-xs">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-1.5 text-left font-medium text-gray-500">Source</th>
              <th className="px-3 py-1.5 text-right font-medium text-gray-500">Monthly (PKR)</th>
              <th className="px-3 py-1.5 text-left font-medium text-gray-500">Evidence</th>
              <th className="px-3 py-1.5 text-center font-medium text-gray-500">Verified</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {records.map((r) => (
              <tr key={r.id}>
                <td className="px-3 py-1.5 capitalize">{r.source_type ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{r.declared_monthly_amount?.toLocaleString() ?? "—"}</td>
                <td className="px-3 py-1.5 capitalize">{r.evidence_type?.replace(/_/g, " ") ?? "—"}</td>
                <td className="px-3 py-1.5 text-center">{r.confidence_flag ? "Yes" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Decision Panel ─────────────────────────────────────────────────── */

function DecisionPanel({
  assessmentId,
  decisions,
  recommendedSupport,
}: {
  assessmentId: string;
  decisions: { id: string; reviewer: string | null; outcome: DecisionOutcome; rationale: string | null; created_at: string }[];
  recommendedSupport?: string;
}) {
  const [outcome, setOutcome] = useState<DecisionOutcome>("approved");
  const [rationale, setRationale] = useState("");
  const [reviewer, setReviewer] = useState("");
  const mutation = useSubmitDecision();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const payload: DecisionCreate = {
      outcome,
      rationale: rationale || null,
      reviewer: reviewer || null,
    };
    mutation.mutate(
      { assessmentId, payload },
      { onSuccess: () => setRationale("") },
    );
  };

  return (
    <div className="card">
      <h2 className="mb-3 flex items-center gap-2">
        <FileText className="h-5 w-5 text-gray-600" />
        Reviewer Decision
      </h2>

      {recommendedSupport && (
        <div className="mb-3 rounded-lg bg-blue-50 p-2 text-xs text-blue-700 ring-1 ring-blue-200">
          <b>Suggested:</b> {recommendedSupport}
        </div>
      )}

      {decisions.length > 0 && (
        <div className="mb-4 border-b border-gray-100 pb-4">
          <h3 className="mb-2 text-xs font-medium text-gray-500 uppercase">Previous decisions</h3>
          {decisions.map((d) => (
            <div key={d.id} className="mb-2 flex items-start gap-3 text-sm">
              <span className={`mt-0.5 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ${
                d.outcome === "approved" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"
              }`}>
                {d.outcome === "approved" ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                {d.outcome}
              </span>
              <div className="min-w-0 flex-1">
                {d.rationale && <p className="text-gray-700">{d.rationale}</p>}
                <p className="text-xs text-gray-400">{d.reviewer ?? "Anonymous"} — {fmtDate(d.created_at)}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => setOutcome("approved")}
            className={`btn flex-1 justify-center ${outcome === "approved" ? "bg-green-700 text-white ring-2 ring-green-300" : "bg-gray-100 text-gray-600"}`}
          >
            <CheckCircle2 className="h-4 w-4" /> Approve
          </button>
          <button
            type="button"
            onClick={() => setOutcome("denied")}
            className={`btn flex-1 justify-center ${outcome === "denied" ? "bg-red-700 text-white ring-2 ring-red-300" : "bg-gray-100 text-gray-600"}`}
          >
            <XCircle className="h-4 w-4" /> Deny
          </button>
        </div>
        <input
          className="input w-full"
          placeholder="Reviewer name (optional)"
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
        />
        <textarea
          className="input w-full"
          rows={3}
          placeholder="Rationale — why this decision? This becomes part of the audit trail."
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
        />
        <div className="flex items-center gap-3">
          <button type="submit" disabled={mutation.isPending} className={outcome === "approved" ? "btn-approve" : "btn-deny"}>
            {mutation.isPending ? "Submitting…" : outcome === "approved" ? "Record Approval" : "Record Denial"}
          </button>
          {mutation.isError && <span className="text-xs text-red-600">Failed: {String(mutation.error)}</span>}
          {mutation.isSuccess && <span className="text-xs text-green-700">Decision recorded.</span>}
        </div>
      </form>
    </div>
  );
}

/* ── Main screen ────────────────────────────────────────────────────── */

export default function ApplicantDetail() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error } = useApplicantDetail(id);

  if (isLoading) return <p className="py-8 text-center text-gray-400">Loading…</p>;
  if (error)
    return (
      <div className="card border-red-200 bg-red-50 text-red-700">
        Failed to load: {String(error)}
      </div>
    );
  if (!data) return null;

  const a = data.latest_assessment;
  const anomalyReport = a?.anomaly_report ?? null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Link to="/" className="inline-flex items-center gap-1 text-sm text-blue-700 hover:underline">
          <ArrowLeft className="h-4 w-4" /> Back to list
        </Link>
        <div className="flex items-center gap-2">
          <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
            Powered by Alibaba Cloud AI
          </span>
          <button
            onClick={() => window.print()}
            className="btn-secondary text-xs"
          >
            <Printer className="h-3.5 w-3.5" /> Print / Export
          </button>
        </div>
      </div>

      {/* Applicant header */}
      <div className="card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="mb-1">{maskCnic(data.applicant.identity_reference) || data.applicant.id.slice(0, 8)}</h1>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-500">
              {data.applicant.applicant_type && <span className="capitalize">{data.applicant.applicant_type}</span>}
              {data.applicant.city && <span>{data.applicant.city}</span>}
              {data.applicant.district && <span>{data.applicant.district}</span>}
            </div>
          </div>
        </div>
      </div>

      {/* Score gauge */}
      {a && (
        <ScoreGauge
          score={a.score}
          band={a.band}
          confidence={a.confidence_level}
          categories={a.signal_categories_count}
          features={a.non_null_feature_count}
          isRuleBased={a.is_rule_based}
        />
      )}

      {/* Category breakdown */}
      {a?.feature_contributions && (
        <CategoryBreakdown contributions={a.feature_contributions} />
      )}

      {/* Factor chart */}
      {a?.feature_contributions && (
        <FactorChart contributions={a.feature_contributions} />
      )}

      {/* Anomaly & Fraud Shield */}
      {anomalyReport && <AnomalyCard report={anomalyReport} />}

      {/* Underlying evidence */}
      {(data.utility_records.length > 0 || data.academic_records.length > 0 || data.income_signals.length > 0) && (
        <div className="card space-y-5">
          <h2 className="mb-1 flex items-center gap-2">
            <FileText className="h-5 w-5 text-gray-600" />
            Underlying Evidence
          </h2>
          <UtilityTable records={data.utility_records} />
          <AcademicTable records={data.academic_records} />
          <IncomeTable records={data.income_signals} />
        </div>
      )}

      {/* Bilingual Case Brief */}
      {a && <CaseBriefTab assessmentId={a.id} />}

      {/* Decision panel */}
      {a && (
        <DecisionPanel
          assessmentId={a.id}
          decisions={data.decisions}
          recommendedSupport={anomalyReport?.recommendation?.recommended_support}
        />
      )}
    </div>
  );
}
