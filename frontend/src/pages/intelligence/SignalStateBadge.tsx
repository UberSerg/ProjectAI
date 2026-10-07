/** Signal / advisory state badge — UNKNOWN must never look like NEUTRAL. */

const SIGNAL_LABELS: Record<string, string> = {
  POSITIVE: "POSITIVE",
  NEUTRAL: "NEUTRAL",
  NEGATIVE: "NEGATIVE",
  ABSTAIN: "ABSTAIN",
  UNKNOWN: "UNKNOWN",
  CONSIDER_INCREASE: "CONSIDER INCREASE",
  HOLD: "HOLD",
  CONSIDER_REDUCE: "CONSIDER REDUCE",
  LOW: "LOW",
  MODERATE: "MODERATE",
  ELEVATED: "ELEVATED",
  HIGH: "HIGH",
  READY: "READY",
  PARTIAL: "PARTIAL",
  NOT_READY: "NOT READY",
};

function toneClass(state?: string | null): string {
  const raw = (state ?? "UNKNOWN").toUpperCase();
  switch (raw) {
    case "POSITIVE":
    case "CONSIDER_INCREASE":
    case "READY":
    case "LOW":
      return "intel-state intel-state-positive";
    case "NEUTRAL":
    case "HOLD":
    case "MODERATE":
    case "PARTIAL":
      return "intel-state intel-state-neutral";
    case "NEGATIVE":
    case "CONSIDER_REDUCE":
    case "HIGH":
    case "ELEVATED":
    case "NOT_READY":
      return "intel-state intel-state-negative";
    case "ABSTAIN":
      return "intel-state intel-state-abstain";
    case "UNKNOWN":
    default:
      return "intel-state intel-state-unknown";
  }
}

export function SignalStateBadge({
  state,
  label,
  testId,
}: {
  state?: string | null;
  label?: string;
  testId?: string;
}) {
  const key = (state ?? "UNKNOWN").toUpperCase();
  const text = label ?? SIGNAL_LABELS[key] ?? key;
  return (
    <span className={toneClass(key)} data-testid={testId} data-state={key}>
      {text}
    </span>
  );
}
