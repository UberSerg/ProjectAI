/** Period helpers for simulator equity charts (inspired by quotes/range). */

import { addMonthsUtc, addYearsUtc, clampRange, parseIsoDate, type DateBounds } from "../quotes/range";

export type SimRangePreset = "3M" | "6M" | "1Y" | "MAX";

export const SIM_RANGE_PRESETS: SimRangePreset[] = ["3M", "6M", "1Y", "MAX"];

function toIsoDate(value: Date): string {
  const y = value.getUTCFullYear();
  const m = String(value.getUTCMonth() + 1).padStart(2, "0");
  const d = String(value.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function simPresetRange(preset: SimRangePreset, available: DateBounds): DateBounds {
  const availTo = parseIsoDate(available.to);
  const availFrom = parseIsoDate(available.from);
  if (!availTo || !availFrom) return available;
  if (preset === "MAX") return { from: available.from, to: available.to };

  let from: Date;
  if (preset === "3M") from = addMonthsUtc(availTo, -3);
  else if (preset === "6M") from = addMonthsUtc(availTo, -6);
  else from = addYearsUtc(availTo, -1);

  return clampRange({ from: toIsoDate(from), to: available.to }, available);
}

export function segmentLabel(segment?: string | null): string {
  if (!segment) return "—";
  if (segment === "FINAL_HOLDOUT") return "HOLDOUT";
  if (segment === "DEVELOPMENT_OOS") return "DEV OOS";
  return segment;
}

export function segmentTone(segment?: string | null): "holdout" | "dev" | "neutral" {
  if (segment === "FINAL_HOLDOUT") return "holdout";
  if (segment === "DEVELOPMENT_OOS") return "dev";
  return "neutral";
}

export function isResearchContextSegment(segment?: string | null): boolean {
  return segment === "DEVELOPMENT_OOS" || segment === "FINAL_HOLDOUT";
}

export function costLabel(bps?: number | null): string {
  if (bps == null || Number.isNaN(bps)) return "—";
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(bps)} bps`;
}

export function policyShort(name?: string | null): string {
  if (!name) return "—";
  if (name === "RANK_LONG_ONLY_V0") return "Rank Long-Only V0";
  return name;
}

/** Pick 0 bps DEV + HOLDOUT siblings for the same candidate (educational comparison). */
export function pickCanonicalPair<T extends {
  id: number;
  segment: string;
  candidate_config_hash?: string | null;
  spec?: { commission_bps?: number | null; slippage_bps?: number | null } | null;
}>(
  runs: T[],
  current: {
    id: number;
    candidate_config_hash?: string | null;
  },
): { dev: T | null; holdout: T | null } {
  const hash = current.candidate_config_hash;
  const zeroCost = (r: T) =>
    (r.spec?.commission_bps ?? 0) === 0 && (r.spec?.slippage_bps ?? 0) === 0;
  const sameCandidate = (r: T) =>
    !hash || !r.candidate_config_hash || r.candidate_config_hash === hash;

  const pool = runs.filter((r) => zeroCost(r) && sameCandidate(r));
  const dev = pool.find((r) => r.segment === "DEVELOPMENT_OOS") ?? null;
  const holdout = pool.find((r) => r.segment === "FINAL_HOLDOUT") ?? null;
  return { dev, holdout };
}
