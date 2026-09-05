/** Client-side cash hurdle post-processing (does not mutate simulation). */

const DAY_COUNT = 365.25;

export function calendarDaysBetween(from: string, to: string): number | null {
  const a = Date.parse(from.slice(0, 10));
  const b = Date.parse(to.slice(0, 10));
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return null;
  return Math.round((b - a) / 86_400_000);
}

/** (1+r)^(days/365.25) − 1 */
export function cashHurdleReturn(
  periodFrom: string | null | undefined,
  periodTo: string | null | undefined,
  annualRate: number,
): number | null {
  if (!periodFrom || !periodTo) return null;
  const days = calendarDaysBetween(periodFrom, periodTo);
  if (days == null || days < 0) return null;
  return (1 + annualRate) ** (days / DAY_COUNT) - 1;
}

export function excessVsCashHurdle(
  totalReturn: number | null | undefined,
  periodFrom: string | null | undefined,
  periodTo: string | null | undefined,
  annualRate: number,
): { hurdleReturn: number | null; excess: number | null } {
  const hurdleReturn = cashHurdleReturn(periodFrom, periodTo, annualRate);
  if (totalReturn == null || hurdleReturn == null) {
    return { hurdleReturn, excess: null };
  }
  return { hurdleReturn, excess: totalReturn - hurdleReturn };
}

/** Approximate annualised excess when CAGR is available: CAGR − annualRate. */
export function excessCagrVsCash(
  cagr: number | null | undefined,
  annualRate: number,
): number | null {
  if (cagr == null || Number.isNaN(cagr)) return null;
  return cagr - annualRate;
}

export function economicConclusion(excess: number | null): string {
  if (excess == null) {
    return "Недостаточно данных, чтобы сравнить результат с выбранной денежной альтернативой.";
  }
  if (excess > 0.005) {
    return "В этом историческом эксперименте стратегия превысила выбранную денежную альтернативу.";
  }
  if (excess < -0.005) {
    return "В этом историческом эксперименте стратегия не превысила выбранную денежную альтернативу.";
  }
  return "В этом историческом эксперименте результат близок к выбранной денежной альтернативе.";
}

export const HURDLE_PRESETS = [
  { rate: 0.1, label: "10 % годовых" },
  { rate: 0.05, label: "5 % годовых" },
  { rate: 0.15, label: "15 % годовых" },
] as const;

export function clampHurdleRate(value: number): number {
  if (!Number.isFinite(value)) return 0.1;
  return Math.min(0.3, Math.max(0, value));
}

export function parseHurdleParam(raw: string | null): number {
  if (raw == null || raw === "") return 0.1;
  const n = Number(raw);
  return clampHurdleRate(Number.isFinite(n) ? n : 0.1);
}
