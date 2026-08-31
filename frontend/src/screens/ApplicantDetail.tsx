import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useApplicantDetail, useSubmitDecision } from "../api/hooks";
import type { DecisionCreate, DecisionOutcome, FeatureContribution } from "../api/types";
import ConfidenceBadge from "../components/ConfidenceBadge";
import { maskCnic } from "../lib/format";

/* ── helpers ──────────────────────────────────────────────────────────── */

const bandColor: Record<string, string> = {
  strong: "text-green-800 bg-green-50 border-green-200",
  moderate: "text-amber-800 bg-amber-50 border-amber-200",
  low: "text-red-800 bg-red-50 border-red-200",
};

function fmtDate(d: string | null | undefined) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString();
}

/* ── Score header ─────────────────────────────────────────────────────── */

function ScoreHeader({ detail }: { detail: ReturnType<typeof useApplicantDetail>["data"] }) {
  if (!detail) return null;
  const a = detail.latest_assessment;
  const app = detail.applicant;

  return (
    <div className="card">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="mb-1">
            {maskCnic(app.identity_reference) || app.id.slice(0, 8)}
          </h1>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-500">
            {app.applicant_type && <span className="capitalize">{app.applicant_type}</span>}
            {app.city && <span>{app.city}</span>}
            {app.district && <span>{app.district}</span>}
          </div>
        </div>

        {a ? (
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="font-mono text-3xl font-bold tabular-nums leading-none">
                {a.score.toFixed(1)}
              </div>
              <div className="mt-1 flex items-center justify-end gap-2">
                <span className={`inline-block rounded border px-2 py-0.5 text-xs font-semibold capitalize ${bandColor[a.band] ?? ""}`}>
                  {a.band}
                </span>
                <ConfidenceBadge
                  level={a.confidence_level}
                  signalCount={a.signal_categories_count}
                  featureCount={a.non_null_feature_count}
                />
              </div>
            </div>
          </div>
        ) : (
          <span className="text-gray-400">Not yet scored</span>
        )}
      </div>

      {a && (
        <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 border-t border-gray-100 pt-3 text-xs text-gray-500">
          <span>
            Scoring path:{" "}
            <span className="font-medium text-gray-700">
              {a.is_rule_based ? "Rule-based" : "Model-based"}
            </span>
          </span>
          <span>
            Signal categories:{" "}
            <span className="font-medium text-gray-700">{a.signal_categories_count}</span>
          </span>
          <span>
            Non-null features:{" "}
            <span className="font-medium text-gray-700">{a.non_null_feature_count}/8</span>
          </span>
          <span>
            Version: <span className="font-medium text-gray-700">{a.model_version}</span>
          </span>
          <span>
            Scored: <span className="font-medium text-gray-700">{fmtDate(a.created_at)}</span>
          </span>
          {a.categories_present && a.categories_present.length > 0 && (
            <span>
              Present:{" "}
              <span className="font-medium text-gray-700 capitalize">
                {a.categories_present.join(", ")}
              </span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/* ── SHAP / factor bar chart ──────────────────────────────────────────── */

function FactorChart({
  contributions,
}: {
  contributions: FeatureContribution[];
}) {
  if (!contributions || contributions.length === 0)
    return <p className="text-sm text-gray-400">No contributing factors recorded.</p>;

  // Separate factors with data from those without.
  const withData = contributions.filter((c) => !c.no_data);
  const noData = contributions.filter((c) => c.no_data);

  const sorted = [...withData].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  const maxAbs = Math.max(...sorted.map((c) => Math.abs(c.contribution)), 0.01);

  return (
    <div className="card">
      <h2 className="mb-3">Contributing Factors</h2>
      <p className="mb-4 text-xs text-gray-500">
        Each bar shows how much a factor pushed the score up or down.
      </p>
      <div className="space-y-3">
        {sorted.map((c) => {
          const pct = (Math.abs(c.contribution) / maxAbs) * 100;
          const isPos = c.direction === "positive";
          const isNeutral = c.direction === "neutral";
          const barColor = isNeutral
            ? "bg-gray-300"
            : isPos
              ? "bg-green-600"
              : "bg-red-600";
          const sign = isPos ? "+" : isNeutral ? "" : "";

          return (
            <div key={c.feature}>
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-gray-700 capitalize">
                  {c.feature.replace(/_/g, " ")}
                </span>
                <span className={`font-mono tabular-nums ${isPos ? "text-green-700" : isNeutral ? "text-gray-500" : "text-red-700"}`}>
                  {sign}{c.contribution.toFixed(1)}
                </span>
              </div>
              <div className="mt-0.5 h-2 w-full rounded-full bg-gray-100">
                <div
                  className={`h-2 rounded-full ${barColor}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              {c.explanation && (
                <p className="mt-0.5 text-xs text-gray-500">{c.explanation}</p>
              )}
            </div>
          );
        })}
      </div>

      {noData.length > 0 && (
        <div className="mt-5 border-t border-gray-100 pt-4">
          <h3 className="mb-2 text-xs font-medium text-gray-500 uppercase tracking-wide">
            No data available
          </h3>
          <p className="mb-2 text-xs text-gray-400">
            These factors had no underlying data and did not affect the score.
          </p>
          <ul className="space-y-1">
            {noData.map((c) => (
              <li key={c.feature} className="text-xs text-gray-500">
                <span className="font-medium text-gray-600 capitalize">
                  {c.feature.replace(/_/g, " ")}
                </span>
                {c.explanation && <span className="ml-1">— {c.explanation}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/* ── Records tables ───────────────────────────────────────────────────── */

function UtilityTable({ records }: { records: ReturnType<typeof useApplicantDetail>["data"] extends infer D ? D extends { utility_records: infer R } ? R : never : never }) {
  if (!records || records.length === 0) return null;
  return (
    <div>
      <h3 className="mb-2">Utility Records ({records.length})</h3>
      <div className="overflow-x-auto rounded border border-gray-200">
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
      <h3 className="mb-2">Academic Records ({records.length})</h3>
      <div className="overflow-x-auto rounded border border-gray-200">
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
      <h3 className="mb-2">Income Signals ({records.length})</h3>
      <div className="overflow-x-auto rounded border border-gray-200">
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

/* ── Decision panel ───────────────────────────────────────────────────── */

function DecisionPanel({
  assessmentId,
  decisions,
}: {
  assessmentId: string;
  decisions: { id: string; reviewer: string | null; outcome: DecisionOutcome; rationale: string | null; created_at: string }[];
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
      <h2 className="mb-3">Reviewer Decision</h2>

      {decisions.length > 0 && (
        <div className="mb-4 border-b border-gray-100 pb-4">
          <h3 className="mb-2 text-xs font-medium text-gray-500 uppercase">Previous decisions</h3>
          {decisions.map((d) => (
            <div key={d.id} className="mb-2 flex items-start gap-3 text-sm">
              <span
                className={`mt-0.5 inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
                  d.outcome === "approved"
                    ? "bg-green-50 text-green-800"
                    : "bg-red-50 text-red-800"
                }`}
              >
                {d.outcome}
              </span>
              <div className="min-w-0 flex-1">
                {d.rationale && <p className="text-gray-700">{d.rationale}</p>}
                <p className="text-xs text-gray-400">
                  {d.reviewer ?? "Anonymous"} — {fmtDate(d.created_at)}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex gap-3">
          <label className="flex items-center gap-1.5 text-sm">
            <input
              type="radio"
              name="outcome"
              checked={outcome === "approved"}
              onChange={() => setOutcome("approved")}
            />
            Approve
          </label>
          <label className="flex items-center gap-1.5 text-sm">
            <input
              type="radio"
              name="outcome"
              checked={outcome === "denied"}
              onChange={() => setOutcome("denied")}
            />
            Deny
          </label>
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
          <button
            type="submit"
            disabled={mutation.isPending}
            className={outcome === "approved" ? "btn-approve" : "btn-deny"}
          >
            {mutation.isPending
              ? "Submitting…"
              : outcome === "approved"
                ? "Record Approval"
                : "Record Denial"}
          </button>
          {mutation.isError && (
            <span className="text-xs text-red-600">
              Failed: {String(mutation.error)}
            </span>
          )}
          {mutation.isSuccess && (
            <span className="text-xs text-green-700">Decision recorded.</span>
          )}
        </div>
      </form>
    </div>
  );
}

/* ── Main screen ──────────────────────────────────────────────────────── */

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

  return (
    <div className="space-y-6">
      <div>
        <Link to="/" className="text-sm text-blue-700 hover:underline">
          ← Back to list
        </Link>
      </div>

      <ScoreHeader detail={data} />

      {a?.feature_contributions && (
        <FactorChart contributions={a.feature_contributions} />
      )}

      {(data.utility_records.length > 0 ||
        data.academic_records.length > 0 ||
        data.income_signals.length > 0) && (
        <div className="card space-y-5">
          <h2 className="mb-1">Underlying Evidence</h2>
          <p className="mb-3 text-xs text-gray-500">
            Raw records that fed into the scoring calculation.
          </p>
          <UtilityTable records={data.utility_records} />
          <AcademicTable records={data.academic_records} />
          <IncomeTable records={data.income_signals} />
        </div>
      )}

      {data.utility_records.length === 0 &&
        data.academic_records.length === 0 &&
        data.income_signals.length === 0 && (
          <div className="card">
            <h2 className="mb-1">Underlying Evidence</h2>
            <p className="text-sm text-gray-400">
              No utility, academic, or income records found for this applicant.
            </p>
          </div>
        )}

      {a && (
        <DecisionPanel
          assessmentId={a.id}
          decisions={data.decisions}
        />
      )}
    </div>
  );
}
