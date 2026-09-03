/** Canonical quote range helpers: from/to ISO dates (YYYY-MM-DD). */

export type RangePreset = "1M" | "3M" | "6M" | "YTD" | "1Y" | "3Y" | "5Y" | "MAX";

export const RANGE_PRESETS: RangePreset[] = ["1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "MAX"];

export interface DateBounds {
  from: string;
  to: string;
}

function toIsoDate(value: Date): string {
  const y = value.getUTCFullYear();
  const m = String(value.getUTCMonth() + 1).padStart(2, "0");
  const d = String(value.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function parseIsoDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const day = value.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const date = new Date(`${day}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function isoFromTimestamp(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return toIsoDate(date);
}

export function clampRange(range: DateBounds, available: DateBounds): DateBounds {
  const availFrom = parseIsoDate(available.from);
  const availTo = parseIsoDate(available.to);
  let from = parseIsoDate(range.from) ?? availFrom;
  let to = parseIsoDate(range.to) ?? availTo;
  if (!from || !to || !availFrom || !availTo) {
    return { from: available.from, to: available.to };
  }
  if (from < availFrom) from = availFrom;
  if (to > availTo) to = availTo;
  if (from > to) from = to;
  return { from: toIsoDate(from), to: toIsoDate(to) };
}

export function addMonthsUtc(base: Date, months: number): Date {
  const next = new Date(base.getTime());
  next.setUTCMonth(next.getUTCMonth() + months);
  return next;
}

export function addYearsUtc(base: Date, years: number): Date {
  const next = new Date(base.getTime());
  next.setUTCFullYear(next.getUTCFullYear() + years);
  return next;
}

export function presetRange(preset: RangePreset, available: DateBounds): DateBounds {
  const availTo = parseIsoDate(available.to);
  const availFrom = parseIsoDate(available.from);
  if (!availTo || !availFrom) return available;
  if (preset === "MAX") return { from: available.from, to: available.to };

  let from: Date;
  if (preset === "YTD") {
    from = new Date(Date.UTC(availTo.getUTCFullYear(), 0, 1));
  } else if (preset === "1M") {
    from = addMonthsUtc(availTo, -1);
  } else if (preset === "3M") {
    from = addMonthsUtc(availTo, -3);
  } else if (preset === "6M") {
    from = addMonthsUtc(availTo, -6);
  } else if (preset === "1Y") {
    from = addYearsUtc(availTo, -1);
  } else if (preset === "3Y") {
    from = addYearsUtc(availTo, -3);
  } else {
    from = addYearsUtc(availTo, -5);
  }
  return clampRange({ from: toIsoDate(from), to: available.to }, available);
}

export function formatPeriodLabel(from: string, to: string): string {
  return `${from} → ${to}`;
}

export function tradingDaysEstimate(from: string, to: string): number {
  const a = parseIsoDate(from);
  const b = parseIsoDate(to);
  if (!a || !b) return 0;
  const days = Math.max(0, Math.round((b.getTime() - a.getTime()) / 86_400_000));
  return Math.max(1, Math.ceil(days * 0.72) + 5);
}
