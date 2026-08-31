import type { ConfidenceLevel } from "../api/types";

const confStyles: Record<ConfidenceLevel, string> = {
  high: "bg-green-50 text-green-800 border-green-200",
  medium: "bg-amber-50 text-amber-800 border-amber-200",
  low: "bg-red-50 text-red-800 border-red-200",
};

const confDot: Record<ConfidenceLevel, string> = {
  high: "bg-green-600",
  medium: "bg-amber-600",
  low: "bg-red-600",
};

const confLabel: Record<ConfidenceLevel, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

interface Props {
  level: ConfidenceLevel;
  signalCount?: number;
  featureCount?: number;
}

export default function ConfidenceBadge({ level, signalCount, featureCount }: Props) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium ${confStyles[level]}`}
      title={
        signalCount !== undefined && featureCount !== undefined
          ? `${signalCount} signal categories, ${featureCount}/8 features non-null`
          : undefined
      }
    >
      <span className={`h-1.5 w-1.5 rounded-full ${confDot[level]}`} />
      {confLabel[level]}
    </span>
  );
}
