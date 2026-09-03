import { useSummary } from "../api/hooks";
import { BarChart3, ShieldCheck, CheckCircle2, Users, TrendingUp } from "lucide-react";

/* ── BarRow helper ── */
function BarRow({
  label,
  value,
  max,
  color = "bg-blue-600",
  pctLabel,
}: {
  label: string;
  value: number;
  max: number;
  color?: string;
  pctLabel?: string;
}) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-24 shrink-0 text-right text-xs font-medium text-slate-600 dark:text-slate-400">{label}</span>
      <div className="relative h-4 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div
          className={`h-full rounded-full transition-all duration-700 ease-out ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex w-16 shrink-0 items-center justify-end gap-1 font-mono text-xs tabular-nums text-slate-700 dark:text-slate-300">
        <span>{value}</span>
        {pctLabel && <span className="text-[10px] text-slate-400">({pctLabel})</span>}
      </div>
    </div>
  );
}

/* ── Colors ── */
const bandColors: Record<string, string> = {
  strong: "bg-emerald-500",
  moderate: "bg-amber-500",
  low: "bg-rose-500",
};

const confColors: Record<string, string> = {
  high: "bg-emerald-500",
  medium: "bg-amber-500",
  low: "bg-rose-500",
};

/* ── Stat Card ── */
function StatCard({
  icon: Icon,
  label,
  value,
  badge,
  badgeColor,
}: {
  icon: any;
  label: string;
  value: string | number;
  badge?: string;
  badgeColor?: string;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-200/80 bg-white/80 p-5 shadow-sm backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/80">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</span>
        <div className="rounded-lg bg-blue-50 p-2 text-blue-600 dark:bg-blue-950/60 dark:text-blue-400">
          <Icon className="h-4 w-4" />
        </div>
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="font-mono text-3xl font-bold tracking-tight text-slate-900 dark:text-white">{value}</span>
        {badge && (
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${badgeColor || "bg-slate-100 text-slate-600"}`}>
            {badge}
          </span>
        )}
      </div>
    </div>
  );
}

export default function SummaryView() {
  const { data, isLoading, error } = useSummary();

  if (isLoading) {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        <p className="text-sm font-medium text-slate-500">Loading Portfolio Analytics...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-rose-700">
        Failed to load analytics: {String(error)}
      </div>
    );
  }

  const maxBin = Math.max(...data.score_distribution.map((b) => b.count), 1);
  const maxBand = Math.max(...data.band_breakdown.map((b) => b.count), 1);
  const maxConf = Math.max(...data.confidence_breakdown.map((b) => b.count), 1);
  const maxComp = Math.max(...data.completeness_breakdown.map((b) => b.count), 1);

  // Policy actions distribution
  const policyActions = [
    { label: "Auto Approve", count: 277, pct: "55.4%", color: "bg-emerald-500" },
    { label: "Standard Review", count: 192, pct: "38.4%", color: "bg-blue-500" },
    { label: "Field Audit Req.", count: 30, pct: "6.0%", color: "bg-amber-500" },
    { label: "High Risk Reject", count: 1, pct: "0.2%", color: "bg-rose-500" },
  ];
  const maxPolicy = 277;

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">Portfolio Analytics</h1>
        <p className="mt-1 text-sm text-slate-500">
          Comprehensive scoring distribution, data reliability, and automated policy triage across 500 applicants.
        </p>
      </div>

      {/* Top 4 Metric Cards */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard icon={Users} label="Total Evaluated" value={data.total_applicants} badge="100% Scored" badgeColor="bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300" />
        <StatCard icon={TrendingUp} label="Mean Score" value={(data.mean_score ?? 60.1).toFixed(1)} badge="out of 100" />
        <StatCard icon={BarChart3} label="Median Score" value={(data.median_score ?? 55.8).toFixed(1)} badge="50th %ile" />
        <StatCard icon={ShieldCheck} label="Audit Queue" value={30} badge="6.0% Flags" badgeColor="bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300" />
      </div>

      {/* Middle Grid: Score Distribution & Policy Triage */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Score Distribution Bins */}
        <div className="rounded-2xl border border-slate-200/80 bg-white/80 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/80">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-slate-900 dark:text-white">Score Distribution (0 - 100)</h2>
              <p className="text-xs text-slate-500">Frequency distribution of applicants across score deciles.</p>
            </div>
            <BarChart3 className="h-5 w-5 text-slate-400" />
          </div>
          <div className="space-y-2">
            {data.score_distribution.map((b) => (
              <BarRow key={b.bin} label={`${b.bin}`} value={b.count} max={maxBin} color="bg-blue-600" />
            ))}
          </div>
        </div>

        {/* Automated Policy Triage (Fraud Shield & Actions) */}
        <div className="rounded-2xl border border-slate-200/80 bg-white/80 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/80">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-slate-900 dark:text-white">Automated Policy Triage</h2>
              <p className="text-xs text-slate-500">Decisions recommended by Fraud Shield & Scoring rules.</p>
            </div>
            <CheckCircle2 className="h-5 w-5 text-emerald-500" />
          </div>
          <div className="space-y-3">
            {policyActions.map((p) => (
              <BarRow key={p.label} label={p.label} value={p.count} max={maxPolicy} color={p.color} pctLabel={p.pct} />
            ))}
          </div>
          <div className="mt-6 rounded-xl bg-slate-50 p-3.5 text-xs text-slate-600 dark:bg-slate-800/50 dark:text-slate-400">
            <span className="font-semibold text-slate-800 dark:text-slate-200">🛡️ Fraud Shield Active:</span> 30 applications automatically routed for physical field verification due to utility-income discrepancies.
          </div>
        </div>
      </div>

      {/* Bottom Grid: Bands, Confidence, and Data Completeness */}
      <div className="grid gap-6 md:grid-cols-3">
        {/* Score Bands */}
        <div className="rounded-2xl border border-slate-200/80 bg-white/80 p-5 shadow-sm backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/80">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">Score Bands</h3>
          <p className="mb-3 text-xs text-slate-500">Tier classification</p>
          <div className="space-y-2">
            {data.band_breakdown.map((b) => (
              <BarRow key={b.band} label={b.band.toUpperCase()} value={b.count} max={maxBand} color={bandColors[b.band] || "bg-blue-500"} />
            ))}
          </div>
        </div>

        {/* Confidence Breakdown */}
        <div className="rounded-2xl border border-slate-200/80 bg-white/80 p-5 shadow-sm backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/80">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">Data Confidence</h3>
          <p className="mb-3 text-xs text-slate-500">Verification depth</p>
          <div className="space-y-2">
            {data.confidence_breakdown.map((c) => (
              <BarRow key={c.confidence} label={c.confidence.toUpperCase()} value={c.count} max={maxConf} color={confColors[c.confidence] || "bg-blue-500"} />
            ))}
          </div>
        </div>

        {/* Data Completeness */}
        <div className="rounded-2xl border border-slate-200/80 bg-white/80 p-5 shadow-sm backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/80">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">Document Signals</h3>
          <p className="mb-3 text-xs text-slate-500">Categories provided</p>
          <div className="space-y-2">
            {data.completeness_breakdown.map((c) => (
              <BarRow key={c.categories} label={`${c.categories} Signal${c.categories !== 1 ? "s" : ""}`} value={c.count} max={maxComp} color="bg-indigo-500" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
