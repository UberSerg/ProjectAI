/** Russian number/date helpers for decision explanations. */

const dateFmt = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const pctFmt = (digits: number) =>
  new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

export function formatRuDate(value?: string | null): string | null {
  if (!value) return null;
  const date = new Date(value.includes("T") ? value : `${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return dateFmt.format(date);
}

/** Decimal fraction → "+5,85%" (no space). */
export function formatSignedPercent(value?: number | null, digits = 2): string | null {
  if (value == null || Number.isNaN(value)) return null;
  const sign = value > 0 ? "+" : "";
  return `${sign}${pctFmt(digits).format(value * 100)}%`;
}

/** Decimal fraction → "12,50%". */
export function formatWeightPercent(value?: number | null, digits = 2): string | null {
  if (value == null || Number.isNaN(value)) return null;
  return `${pctFmt(digits).format(value * 100)}%`;
}

/** Fraction difference → "2,0 п.п." */
export function formatPp(value?: number | null, digits = 1): string | null {
  if (value == null || Number.isNaN(value)) return null;
  const sign = value > 0 ? "+" : "";
  return `${sign}${pctFmt(digits).format(value * 100)} п.п.`;
}

export function formatQuantilePercent(q?: number | null): string | null {
  if (q == null || Number.isNaN(q)) return null;
  const pct = q <= 1 ? q * 100 : q;
  const digits = Number.isInteger(pct) ? 0 : 1;
  return `${pctFmt(digits).format(pct)}%`;
}

export function formatRank(rank?: number | null, eligible?: number | null): string | null {
  if (rank == null) return null;
  if (eligible != null) return `${rank} из ${eligible}`;
  return `${rank}-е место`;
}

export function instrumentLabel(ticker?: string | null, displayName?: string | null): string {
  const t = (ticker ?? "").trim();
  const n = (displayName ?? "").trim();
  if (n && t && n.toUpperCase() !== t.toUpperCase()) return `${n} (${t})`;
  return t || n || "Инструмент";
}

export function instrumentShort(ticker?: string | null, displayName?: string | null): string {
  const t = (ticker ?? "").trim();
  const n = (displayName ?? "").trim();
  if (n) return n;
  return t || "Инструмент";
}

export function computeCutoff(eligible?: number | null, quantile?: number | null): number | null {
  if (eligible == null || quantile == null || eligible <= 0) return null;
  return Math.max(1, Math.ceil(eligible * quantile));
}
