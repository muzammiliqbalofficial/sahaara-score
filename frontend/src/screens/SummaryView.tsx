import { useSummary } from "../api/hooks";

/* ── Small bar chart component ────────────────────────────────────────── */

function BarRow({
  label,
  value,
  max,
  color = "bg-gray-700",
}: {
  label: string;
  value: number;
  max: number;
  color?: string;
}) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-20 shrink-0 text-right text-xs text-gray-600">{label}</span>
      <div className="relative h-5 flex-1 rounded bg-gray-100">
        <div className={`h-5 rounded ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-10 shrink-0 text-right font-mono text-xs tabular-nums">{value}</span>
    </div>
  );
}

/* ── Confidence colours ───────────────────────────────────────────────── */

const confColor: Record<string, string> = {
  high: "bg-green-600",
  medium: "bg-amber-600",
  low: "bg-red-600",
};

const bandColor: Record<string, string> = {
  strong: "bg-green-600",
  moderate: "bg-amber-600",
  low: "bg-red-600",
};

/* ── Main screen ──────────────────────────────────────────────────────── */

export default function SummaryView() {
  const { data, isLoading, error } = useSummary();

  if (isLoading) return <p className="py-8 text-center text-gray-400">Loading…</p>;
  if (error)
    return (
      <div className="card border-red-200 bg-red-50 text-red-700">
        Failed to load: {String(error)}
      </div>
    );
  if (!data) return null;

  const maxBin = Math.max(...data.score_distribution.map((b) => b.count), 1);
  const maxBand = Math.max(...data.band_breakdown.map((b) => b.count), 1);
  const maxConf = Math.max(...data.confidence_breakdown.map((b) => b.count), 1);
  const maxComp = Math.max(...data.completeness_breakdown.map((b) => b.count), 1);

  const totalDecisions = data.decision_counts.reduce((s, d) => s + d.count, 0);

  return (
    <div className="space-y-6">
      <h1>Summary</h1>

      {/* Key numbers */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Total applicants" value={data.total_applicants} />
        <Stat label="Scored" value={data.scored_applicants} />
        <Stat
          label="Mean score"
          value={data.mean_score !== null ? data.mean_score.toFixed(1) : "—"}
        />
        <Stat
          label="Median score"
          value={data.median_score !== null ? data.median_score.toFixed(1) : "—"}
        />
      </div>

      {/* Score distribution */}
      <div className="card">
        <h2 className="mb-3">Score Distribution</h2>
        <div className="space-y-1.5">
          {data.score_distribution.map((b) => (
            <BarRow key={b.bin} label={b.bin} value={b.count} max={maxBin} />
          ))}
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Band breakdown */}
        <div className="card">
          <h2 className="mb-3">Band Breakdown</h2>
          <div className="space-y-1.5">
            {data.band_breakdown.map((b) => (
              <BarRow
                key={b.band}
                label={b.band}
                value={b.count}
                max={maxBand}
                color={bandColor[b.band] ?? "bg-gray-700"}
              />
            ))}
          </div>
        </div>

        {/* Confidence breakdown */}
        <div className="card">
          <h2 className="mb-3">Confidence Breakdown</h2>
          <div className="space-y-1.5">
            {data.confidence_breakdown.map((c) => (
              <BarRow
                key={c.confidence}
                label={c.confidence}
                value={c.count}
                max={maxConf}
                color={confColor[c.confidence] ?? "bg-gray-700"}
              />
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Data completeness */}
        <div className="card">
          <h2 className="mb-3">Data Completeness</h2>
          <p className="mb-3 text-xs text-gray-500">
            Number of signal categories present per applicant (utility, academic, income).
          </p>
          <div className="space-y-1.5">
            {data.completeness_breakdown.map((c) => (
              <BarRow
                key={c.categories}
                label={`${c.categories} cat.`}
                value={c.count}
                max={maxComp}
              />
            ))}
          </div>
        </div>

        {/* Decisions */}
        <div className="card">
          <h2 className="mb-3">Decisions</h2>
          {totalDecisions === 0 ? (
            <p className="text-sm text-gray-400">No decisions recorded yet.</p>
          ) : (
            <>
              <div className="space-y-1.5">
                {data.decision_counts.map((d) => (
                  <BarRow
                    key={d.outcome}
                    label={d.outcome}
                    value={d.count}
                    max={Math.max(totalDecisions, 1)}
                    color={d.outcome === "approved" ? "bg-green-600" : "bg-red-600"}
                  />
                ))}
              </div>
              <p className="mt-3 text-xs text-gray-500">
                {data.undecided_count} applicant{data.undecided_count !== 1 ? "s" : ""} still
                awaiting a decision.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Stat card ────────────────────────────────────────────────────────── */

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card flex flex-col">
      <span className="text-xs font-medium text-gray-500">{label}</span>
      <span className="mt-1 font-mono text-2xl font-semibold tabular-nums">{value}</span>
    </div>
  );
}
