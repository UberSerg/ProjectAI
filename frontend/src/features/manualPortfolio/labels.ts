/** Shared labels for Instrument Master + Manual Portfolio V1. */

const SUPPORT_LEVEL: Record<string, string> = {
  FULL: "Полная поддержка",
  PARTIAL: "Частичная",
  CATALOG_ONLY: "Только каталог",
  INACTIVE: "Неактивен",
};

const SUGGESTED_ACTION: Record<string, string> = {
  KEEP: "Держать",
  INCREASE: "Увеличить",
  REDUCE: "Уменьшить",
  EXIT: "Выйти",
  REVIEW: "Проверить",
  NO_VIEW: "Нет оценки",
};

const COMPARE_STATUS: Record<string, string> = {
  BOTH: "В обоих",
  NOT_IN_MANUAL: "Нет в моём",
  NOT_IN_CANDIDATE: "Нет у Kraken",
};

const COVERAGE_LABELS: Record<string, string> = {
  live_quote: "Живая котировка",
  portfolio_value: "Оценка в портфеле",
  predict: "Прогноз модели",
  fundamental: "Фундаментал",
  fixed_income: "Анализ облигаций",
  rebalance: "Ребаланс (лоты)",
  cashflow: "Денежные потоки",
};

const SUBTYPE_LABELS: Record<string, string> = {
  equity_common: "Обыкновенная акция",
  equity_preferred: "Привилегированная",
  ofz_gov: "ОФЗ",
  corporate_bond: "Корпоративная облигация",
  municipal_bond: "Муниципальная облигация",
  fund: "Фонд / ETF",
  other: "Прочее",
  index: "Индекс",
};

export function supportLevelLabel(value?: string | null): string {
  if (!value) return "—";
  return SUPPORT_LEVEL[value.toUpperCase()] ?? value;
}

export function suggestedActionLabel(value?: string | null): string {
  if (!value) return "—";
  return SUGGESTED_ACTION[value.toUpperCase()] ?? value;
}

export function compareStatusLabel(value?: string | null): string {
  if (!value) return "—";
  return COMPARE_STATUS[value.toUpperCase()] ?? value;
}

export function coverageLabel(key: string): string {
  return COVERAGE_LABELS[key] ?? key;
}

export function subtypeLabel(value?: string | null): string {
  if (!value) return "—";
  return SUBTYPE_LABELS[value.toLowerCase()] ?? value;
}

export function isOfz(subtype?: string | null, symbol?: string | null): boolean {
  if ((subtype || "").toLowerCase() === "ofz_gov") return true;
  const s = (symbol || "").toUpperCase();
  return s.startsWith("SU") || s.startsWith("OFZ");
}

export function isBondLike(
  assetClass?: string | null,
  subtype?: string | null,
  detail?: Record<string, unknown> | null,
): boolean {
  const asset = (assetClass || "").toLowerCase();
  if (asset === "bond") return true;
  const st = (subtype || "").toLowerCase();
  if (st.includes("bond") || st === "ofz_gov") return true;
  if (detail && ("clean_percent" in detail || "accrued_interest_per_bond" in detail || "dirty_total" in detail)) {
    return true;
  }
  return false;
}

export function moneyRub(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toLocaleString("ru-RU", { maximumFractionDigits: digits })} ₽`;
}

export function pctWeight(weight: number | null | undefined): string {
  if (weight == null || Number.isNaN(weight)) return "—";
  return `${(weight * 100).toFixed(1)}%`;
}

export function qualityLabel(quality?: string | null): string {
  const q = (quality || "").toUpperCase();
  if (q === "LIVE") return "Актуальные котировки";
  if (q === "PARTIAL") return "Частичное качество";
  if (q === "STALE") return "Устаревшие цены";
  if (q === "UNSUPPORTED") return "Нет оценки";
  return quality || "—";
}
