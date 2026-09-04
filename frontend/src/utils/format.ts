/** Единые форматтеры дат и чисел для UI. */

const dateFmt = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const dateTimeFmt = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const numberFmt = new Intl.NumberFormat("ru-RU");

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return dateFmt.format(date);
}

export function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return dateTimeFmt.format(date);
}

export function formatDateRange(from?: string | null, to?: string | null): string {
  if (!from && !to) return "—";
  return `${formatDate(from)} — ${formatDate(to)}`;
}

export function formatNumber(value?: number | null): string {
  return value == null ? "—" : numberFmt.format(value);
}

export function formatDuration(seconds?: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  if (seconds < 60) return `${seconds} сек`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s ? `${m} мин ${s} сек` : `${m} мин`;
}

export function formatPrice(value?: number | null): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 4 }).format(value);
}

/** Decimal fraction → percent string, e.g. 0.0352 → "3,52 %" */
export function formatPercent(value?: number | null, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${new Intl.NumberFormat("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value * 100)} %`;
}

/**
 * Fraction difference → percentage points, e.g. 0.11 → "+11,0 п.п.".
 * Use for excess vs benchmark — not absolute portfolio return.
 */
export function formatPercentPoints(value?: number | null, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value * 100)} п.п.`;
}

export function formatMoney(value?: number | null, currency = "RUB"): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatZScore(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)}σ`;
}

export function shortHash(value?: string | null, length = 8): string {
  if (!value) return "—";
  return value.length <= length ? value : value.slice(0, length);
}
