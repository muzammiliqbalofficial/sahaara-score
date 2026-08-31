import { useState } from "react";
import { Link } from "react-router-dom";
import { useApplicantList, type ApplicantListParams } from "../api/hooks";
import ConfidenceBadge from "../components/ConfidenceBadge";
import { maskCnic } from "../lib/format";
import type { ScoredApplicant } from "../api/types";

type SortKey = "score" | "band" | "confidence" | "created_at" | "city" | "applicant_type";

const bandColor: Record<string, string> = {
  strong: "text-green-800",
  moderate: "text-amber-800",
  low: "text-red-800",
};

function ScoreCell({ row }: { row: ScoredApplicant }) {
  const a = row.latest_assessment;
  if (!a) return <span className="text-gray-400">Unscored</span>;
  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-base font-semibold tabular-nums">{a.score.toFixed(1)}</span>
      <ConfidenceBadge
        level={a.confidence_level}
        signalCount={a.signal_categories_count}
        featureCount={a.non_null_feature_count}
      />
    </div>
  );
}

export default function ApplicantList() {
  const [params, setParams] = useState<ApplicantListParams>({
    offset: 0,
    limit: 50,
    sort_by: "score",
    sort_order: "desc",
  });

  const { data, isLoading, error } = useApplicantList(params);

  const setSort = (field: SortKey) => {
    setParams((p) => ({
      ...p,
      sort_by: field,
      sort_order: p.sort_by === field && p.sort_order === "desc" ? "asc" : "desc",
      offset: 0,
    }));
  };

  const setFilter = (key: keyof ApplicantListParams, value: string) => {
    setParams((p) => ({ ...p, [key]: value || undefined, offset: 0 }));
  };

  const sortIndicator = (field: SortKey) =>
    params.sort_by === field ? (params.sort_order === "desc" ? " ↓" : " ↑") : "";

  const thClass = "px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer select-none hover:text-gray-700";

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <h1>Applicants</h1>
        <div className="ml-auto flex flex-wrap gap-2">
          <input
            type="text"
            className="input w-48"
            placeholder="Search city, CNIC…"
            value={params.search ?? ""}
            onChange={(e) => setFilter("search", e.target.value)}
          />
          <select
            className="select"
            value={params.band ?? ""}
            onChange={(e) => setFilter("band", e.target.value)}
          >
            <option value="">All bands</option>
            <option value="strong">Strong</option>
            <option value="moderate">Moderate</option>
            <option value="low">Low</option>
          </select>
          <select
            className="select"
            value={params.confidence ?? ""}
            onChange={(e) => setFilter("confidence", e.target.value)}
          >
            <option value="">All confidence</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <select
            className="select"
            value={params.review_status ?? ""}
            onChange={(e) => setFilter("review_status", e.target.value)}
          >
            <option value="">All statuses</option>
            <option value="decided">Decided</option>
            <option value="undecided">Undecided</option>
          </select>
        </div>
      </div>

      {isLoading && <SkeletonTable />}
      {error && (
        <div className="card border-red-200 bg-red-50 text-red-700">
          Failed to load: {String(error)}
        </div>
      )}

      {data && (
        <>
          <div className="overflow-x-auto rounded border border-gray-200 bg-white">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className={thClass} onClick={() => setSort("score")}>
                    Score{sortIndicator("score")}
                  </th>
                  <th className={thClass} onClick={() => setSort("band")}>
                    Band{sortIndicator("band")}
                  </th>
                  <th className={thClass}>ID / Type</th>
                  <th className={thClass} onClick={() => setSort("city")}>
                    City{sortIndicator("city")}
                  </th>
                  <th className={thClass}>Status</th>
                  <th className={thClass} onClick={() => setSort("created_at")}>
                    Created{sortIndicator("created_at")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.map((row) => (
                  <tr key={row.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-3 py-2.5">
                      <ScoreCell row={row} />
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5">
                      {row.latest_assessment && (
                        <span className={`font-medium capitalize ${bandColor[row.latest_assessment.band] ?? ""}`}>
                          {row.latest_assessment.band}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <Link
                        to={`/applicant/${row.id}`}
                        className="font-mono text-xs text-blue-700 hover:underline"
                      >
                        {maskCnic(row.identity_reference) || row.id.slice(0, 8)}
                      </Link>
                      {row.applicant_type && (
                        <div className="text-xs text-gray-500 capitalize">{row.applicant_type}</div>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-sm">
                      {row.city ?? "—"}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5">
                      {row.has_decision ? (
                        <span
                          className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${
                            row.latest_decision_outcome === "approved"
                              ? "bg-green-50 text-green-800"
                              : "bg-red-50 text-red-800"
                          }`}
                        >
                          {row.latest_decision_outcome}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400">Pending</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-xs text-gray-500">
                      {new Date(row.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
                {data.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-gray-400">
                      No applicants match the current filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="mt-3 flex items-center justify-between text-xs text-gray-500">
            <span>
              Showing {(params.offset ?? 0) + 1}–{(params.offset ?? 0) + data.length} results
            </span>
            <div className="flex gap-2">
              <button
                className="btn-secondary"
                disabled={(params.offset ?? 0) === 0}
                onClick={() =>
                  setParams((p) => ({ ...p, offset: Math.max(0, (p.offset ?? 0) - (p.limit ?? 50)) }))
                }
              >
                Previous
              </button>
              <button
                className="btn-secondary"
                disabled={data.length < (params.limit ?? 50)}
                onClick={() =>
                  setParams((p) => ({ ...p, offset: (p.offset ?? 0) + (p.limit ?? 50) }))
                }
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/* ── Skeleton table shown while data loads ──────────────────────────────── */

function SkeletonRow() {
  return (
    <tr className="animate-pulse">
      <td className="px-3 py-3"><div className="h-4 w-28 rounded bg-gray-200" /></td>
      <td className="px-3 py-3"><div className="h-4 w-16 rounded bg-gray-200" /></td>
      <td className="px-3 py-3"><div className="h-4 w-32 rounded bg-gray-200" /></td>
      <td className="px-3 py-3"><div className="h-4 w-20 rounded bg-gray-200" /></td>
      <td className="px-3 py-3"><div className="h-4 w-14 rounded bg-gray-200" /></td>
      <td className="px-3 py-3"><div className="h-4 w-16 rounded bg-gray-200" /></td>
    </tr>
  );
}

function SkeletonTable() {
  return (
    <div className="overflow-x-auto rounded border border-gray-200 bg-white">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {["Score", "Band", "ID / Type", "City", "Status", "Created"].map((h) => (
              <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {Array.from({ length: 8 }).map((_, i) => (
            <SkeletonRow key={i} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
