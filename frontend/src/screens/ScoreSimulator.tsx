import { useState, useMemo } from "react";
import {
  Sliders, AlertTriangle, ShieldCheck, GraduationCap,
  Zap, Users, Banknote, TrendingUp, RotateCcw,
} from "lucide-react";

/* ── Constants (match backend scoring_service.py) ────────────────────────── */

const RULE_WEIGHTS: Record<string, number> = {
  payment_on_time_ratio: 0.30,
  longest_on_time_streak: 0.10,
  mean_days_late: 0.10,
  payment_consistency: 0.10,
  academic_signal: 0.15,
  household_burden: 0.10,
  income_confidence: 0.08,
  total_income_normalised: 0.07,
};

const AVG_TARIFF_PER_KWH = 29.0;
const LOW_INCOME_THRESHOLD = 25_000;
const LUXURY_UNITS = 400;
const DEPENDANTS_THRESHOLD = 8;

/* ── Feature calculation ─────────────────────────────────────────────────── */

interface SimInputs {
  income: number;
  electricityUnits: number;
  dependants: number;
  academicPct: number;
  arrearsPkr: number;
}

function computeFeatures(inp: SimInputs) {
  const elecBill = inp.electricityUnits * AVG_TARIFF_PER_KWH;

  // Payment reliability: derived from arrears relative to bill.
  const arrearsMultiple = elecBill > 0 ? inp.arrearsPkr / elecBill : 0;
  const paymentRatio = arrearsMultiple <= 0 ? 1.0 : Math.max(0, 1 - arrearsMultiple * 0.25);
  const streak = arrearsMultiple <= 0 ? 0.8 : Math.max(0, 0.6 - arrearsMultiple * 0.15);
  const meanLate = arrearsMultiple <= 0 ? 0.9 : Math.max(0.1, 0.8 - arrearsMultiple * 0.2);
  const consistency = arrearsMultiple <= 0 ? 0.85 : Math.max(0.15, 0.75 - arrearsMultiple * 0.15);

  const academic = Math.min(inp.academicPct / 100, 1.0);
  const burden = Math.max(0, 1 - inp.dependants / 12);
  const incomeConf = 0.5; // Simulator assumes moderate confidence.
  const incomeNorm = Math.min(inp.income / 100_000, 1.0);

  return {
    payment_on_time_ratio: paymentRatio,
    longest_on_time_streak: streak,
    mean_days_late: meanLate,
    payment_consistency: consistency,
    academic_signal: academic,
    household_burden: burden,
    income_confidence: incomeConf,
    total_income_normalised: incomeNorm,
    elecBill,
    arrearsMultiple,
  };
}

function computeScore(features: { [key: string]: number }) {
  let weighted = 0;
  let totalWeight = 0;
  for (const [name, weight] of Object.entries(RULE_WEIGHTS)) {
    const v = features[name];
    if (v !== undefined) {
      weighted += v * weight;
      totalWeight += weight;
    }
  }
  return totalWeight > 0 ? Math.round((weighted / totalWeight) * 100) : 25;
}

/* ── Anomaly detection ───────────────────────────────────────────────────── */

interface AnomalyFlag {
  code: string;
  severity: "info" | "warning" | "critical";
  message: string;
}

function detectAnomalies(inp: SimInputs, elecBill: number): AnomalyFlag[] {
  const flags: AnomalyFlag[] = [];
  const ratio = inp.income > 0 ? elecBill / inp.income : 0;

  if (ratio > 1.0) {
    flags.push({
      code: "INCOME_BILL_MISMATCH",
      severity: "critical",
      message: `Bill (${(ratio * 100).toFixed(0)}% of income) exceeds declared income entirely.`,
    });
  } else if (ratio > 0.6) {
    flags.push({
      code: "INCOME_BILL_MISMATCH",
      severity: "warning",
      message: `Bill consumes ${(ratio * 100).toFixed(0)}% of declared income.`,
    });
  }

  if (inp.income < LOW_INCOME_THRESHOLD && inp.electricityUnits > LUXURY_UNITS) {
    flags.push({
      code: "LUXURY_TARIFF_INDICATOR",
      severity: "warning",
      message: `${inp.electricityUnits} kWh consumption while claiming extreme-need income (PKR ${inp.income.toLocaleString()}).`,
    });
  }

  if (inp.arrearsPkr > 0 && elecBill > 0) {
    const mult = inp.arrearsPkr / elecBill;
    if (mult > 2.0) {
      flags.push({
        code: "CHRONIC_DEFAULT_BURDEN",
        severity: "warning",
        message: `Arrears are ${mult.toFixed(1)}x the monthly bill — chronic default.`,
      });
    }
  }

  if (inp.dependants > DEPENDANTS_THRESHOLD) {
    flags.push({
      code: "DEPENDENCY_INFLATION",
      severity: "warning",
      message: `${inp.dependants} dependants declared — unusually large household.`,
    });
  }

  return flags;
}

function recommend(score: number, flags: AnomalyFlag[]) {
  const hasCritical = flags.some((f) => f.severity === "critical");
  const warnCount = flags.filter((f) => f.severity === "warning").length;

  if (hasCritical) return { action: "HIGH_RISK_REJECT", support: "Physical Verification Required", color: "text-red-700" };
  if (warnCount >= 2) return { action: "FIELD_AUDIT_REQUIRED", support: "Conditional on Audit", color: "text-orange-700" };
  if (warnCount === 1) return { action: "STANDARD_REVIEW", support: "Partial Fee Support (50%)", color: "text-amber-700" };
  if (score >= 60) return { action: "AUTO_APPROVE", support: "Full Merit-Need Scholarship (100%)", color: "text-green-700" };
  if (score >= 35) return { action: "AUTO_APPROVE", support: "Partial Fee Support (50%)", color: "text-green-700" };
  return { action: "AUTO_APPROVE", support: "Emergency Micro-Grant", color: "text-green-700" };
}

/* ── Presets ─────────────────────────────────────────────────────────────── */

interface Preset {
  label: string;
  emoji: string;
  inputs: SimInputs;
}

const PRESETS: Preset[] = [
  {
    label: "Destitute High-Achieving Student",
    emoji: "",
    inputs: { income: 15000, electricityUnits: 120, dependants: 4, academicPct: 92, arrearsPkr: 0 },
  },
  {
    label: "Electricity vs Income Fraud",
    emoji: "",
    inputs: { income: 18000, electricityUnits: 700, dependants: 3, academicPct: 65, arrearsPkr: 25000 },
  },
  {
    label: "Informal Freelancer / Daily Wager",
    emoji: "",
    inputs: { income: 30000, electricityUnits: 200, dependants: 5, academicPct: 55, arrearsPkr: 3000 },
  },
];

/* ── Component ───────────────────────────────────────────────────────────── */

export default function ScoreSimulator() {
  const [inputs, setInputs] = useState<SimInputs>({
    income: 35000,
    electricityUnits: 200,
    dependants: 3,
    academicPct: 72,
    arrearsPkr: 0,
  });

  const set = (key: keyof SimInputs) => (val: number) =>
    setInputs((prev) => ({ ...prev, [key]: val }));

  const features = useMemo(() => computeFeatures(inputs), [inputs]);
  const score = useMemo(() => computeScore(features), [features]);
  const flags = useMemo(() => detectAnomalies(inputs, features.elecBill), [inputs, features]);
  const rec = useMemo(() => recommend(score, flags), [score, flags]);

  const band = score >= 60 ? "Strong" : score >= 35 ? "Moderate" : "Low";
  const bandColor = score >= 60 ? "text-green-700 bg-green-50 ring-green-200" : score >= 35 ? "text-amber-700 bg-amber-50 ring-amber-200" : "text-red-700 bg-red-50 ring-red-200";

  // Score ring SVG parameters.
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (score / 100) * circumference;
  const ringColor = score >= 60 ? "#16a34a" : score >= 35 ? "#d97706" : "#dc2626";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2">
            <Sliders className="h-5 w-5 text-blue-600" />
            Live Judge Simulator
          </h1>
          <p className="mt-1 text-xs text-gray-500">
            Adjust inputs to see the Sahaara Score, anomaly flags, and policy recommendation in real time.
          </p>
        </div>
        <button
          onClick={() => setInputs(PRESETS[0]!.inputs)}
          className="btn-secondary text-xs"
        >
          <RotateCcw className="h-3.5 w-3.5" /> Reset
        </button>
      </div>

      {/* Presets */}
      <div className="flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            onClick={() => setInputs(p.inputs)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-gray-700 ring-1 ring-gray-200 transition hover:ring-blue-300 hover:bg-blue-50"
          >
            <span>{p.emoji}</span>
            {p.label}
          </button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left: Sliders */}
        <div className="lg:col-span-2 space-y-4">
          <div className="card space-y-5">
            <h2 className="text-sm font-semibold text-gray-700">Input Parameters</h2>

            <SliderRow
              icon={<Banknote className="h-4 w-4 text-green-600" />}
              label="Declared Monthly Income"
              unit="PKR"
              min={10_000}
              max={200_000}
              step={1_000}
              value={inputs.income}
              onChange={set("income")}
              format={(v) => v.toLocaleString()}
            />
            <SliderRow
              icon={<Zap className="h-4 w-4 text-amber-600" />}
              label="Monthly Electricity Consumption"
              unit="kWh"
              min={50}
              max={1_000}
              step={10}
              value={inputs.electricityUnits}
              onChange={set("electricityUnits")}
              format={(v) => `${v}`}
              subtext={`≈ PKR ${(inputs.electricityUnits * AVG_TARIFF_PER_KWH).toLocaleString()} billed`}
            />
            <SliderRow
              icon={<Users className="h-4 w-4 text-blue-600" />}
              label="Family Dependents"
              min={1}
              max={12}
              step={1}
              value={inputs.dependants}
              onChange={set("dependants")}
            />
            <SliderRow
              icon={<GraduationCap className="h-4 w-4 text-purple-600" />}
              label="Academic Score"
              unit="%"
              min={40}
              max={100}
              step={1}
              value={inputs.academicPct}
              onChange={set("academicPct")}
            />
            <SliderRow
              icon={<TrendingUp className="h-4 w-4 text-red-600" />}
              label="Accumulated Arrears"
              unit="PKR"
              min={0}
              max={100_000}
              step={1_000}
              value={inputs.arrearsPkr}
              onChange={set("arrearsPkr")}
              format={(v) => v.toLocaleString()}
            />
          </div>

          {/* Feature breakdown */}
          <div className="card">
            <h2 className="mb-3 text-sm font-semibold text-gray-700">Feature Weights</h2>
            <div className="grid gap-2 sm:grid-cols-2">
              {Object.entries(RULE_WEIGHTS).map(([name, weight]) => {
                const val = (features as unknown as Record<string, number>)[name] ?? 0;
                const pct = Math.round(val * 100);
                return (
                  <div key={name} className="flex items-center gap-2 text-xs">
                    <span className="w-36 shrink-0 truncate text-gray-500 capitalize">
                      {name.replace(/_/g, " ")}
                    </span>
                    <div className="h-2 flex-1 rounded-full bg-gray-100">
                      <div
                        className="h-2 rounded-full bg-blue-500"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="w-10 text-right font-mono tabular-nums text-gray-600">
                      {pct}%
                    </span>
                    <span className="w-8 text-right text-gray-400">
                      ×{weight}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Right: Results */}
        <div className="space-y-4">
          {/* Score gauge */}
          <div className="card flex flex-col items-center">
            <div className="score-ring h-36 w-36">
              <svg className="h-full w-full -rotate-90" viewBox="0 0 120 120">
                <circle cx="60" cy="60" r={radius} fill="none" stroke="#e5e7eb" strokeWidth="10" />
                <circle
                  cx="60" cy="60" r={radius} fill="none"
                  stroke={ringColor} strokeWidth="10" strokeLinecap="round"
                  strokeDasharray={circumference}
                  strokeDashoffset={strokeDashoffset}
                  className="transition-all duration-500"
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="font-mono text-3xl font-bold tabular-nums" style={{ color: ringColor }}>
                  {score}
                </span>
                <span className={`mt-0.5 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${bandColor}`}>
                  {band}
                </span>
              </div>
            </div>
            <p className="mt-3 text-xs text-gray-500">Sahaara Score (rule-based)</p>
          </div>

          {/* Anomaly warnings */}
          <div className="card">
            <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-gray-700">
              <ShieldCheck className="h-4 w-4 text-blue-600" />
              Anomaly Shield
            </h2>
            {flags.length === 0 ? (
              <div className="flex items-center gap-2 rounded-lg bg-green-50 p-3 text-xs text-green-700 ring-1 ring-green-200">
                <ShieldCheck className="h-4 w-4" />
                No anomalies detected — file is clean.
              </div>
            ) : (
              <div className="space-y-2">
                {flags.map((f) => (
                  <div
                    key={f.code}
                    className={`rounded-lg p-2.5 text-xs ring-1 ${
                      f.severity === "critical"
                        ? "bg-red-50 text-red-800 ring-red-200"
                        : f.severity === "warning"
                          ? "bg-amber-50 text-amber-800 ring-amber-200"
                          : "bg-blue-50 text-blue-800 ring-blue-200"
                    }`}
                  >
                    <div className="flex items-center gap-1.5 font-semibold">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      {f.code.replace(/_/g, " ")}
                    </div>
                    <p className="mt-0.5 text-gray-600">{f.message}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Recommendation */}
          <div className="card">
            <h2 className="mb-2 text-sm font-semibold text-gray-700">Policy Recommendation</h2>
            <div className={`rounded-lg p-3 text-xs ring-1 ${
              rec.action === "AUTO_APPROVE"
                ? "bg-green-50 ring-green-200"
                : rec.action === "STANDARD_REVIEW"
                  ? "bg-amber-50 ring-amber-200"
                  : "bg-red-50 ring-red-200"
            }`}>
              <p className={`font-bold ${rec.color}`}>
                {rec.action.replace(/_/g, " ")}
              </p>
              <p className="mt-1 text-gray-600">{rec.support}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Slider row ─────────────────────────────────────────────────────────── */

function SliderRow({
  icon, label, unit, min, max, step, value, onChange, format, subtext,
}: {
  icon: React.ReactNode;
  label: string;
  unit?: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
  subtext?: string;
}) {
  const display = format ? format(value) : String(value);
  const pct = ((value - min) / (max - min)) * 100;

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs font-medium text-gray-600">
          {icon} {label}
        </span>
        <span className="font-mono text-sm font-semibold tabular-nums text-gray-900">
          {display}{unit ? ` ${unit}` : ""}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-2 w-full cursor-pointer appearance-none rounded-full bg-gray-200 accent-blue-600"
        style={{ background: `linear-gradient(to right, #2563eb ${pct}%, #e5e7eb ${pct}%)` }}
      />
      {subtext && <p className="mt-0.5 text-xs text-gray-400">{subtext}</p>}
    </div>
  );
}
