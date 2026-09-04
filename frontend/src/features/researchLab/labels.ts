/** Human labels for Simulator Research Lab V0 (historical research, not live trading). */

import type {
  ResearchOptions,
  ResearchRunSummary,
  StrategyOption,
} from "../../api/researchLab";

export const MAX_COMPARE_RUNS = 5;
export const MIN_COMPARE_RUNS = 2;

/** Fallback names when /options is not loaded yet — options API stays the source of truth. */
const POLICY_FALLBACK: Record<string, string> = {
  RANK_LONG_ONLY_V0: "Базовая рейтинговая",
  RANK_HYSTERESIS_LONG_ONLY_V1: "Рейтинговая с удержанием",
};

const RISK_FALLBACK: Record<string, string> = {
  RISK_GUARDRAILS_V0: "Базовые ограничения",
  DRAWDOWN_GUARD_V1: "Защита от глубокой просадки",
};

function fromOptions(options: StrategyOption[] | undefined, id?: string | null): string | null {
  if (!id || !options) return null;
  return options.find((o) => o.id === id || o.technical_id === id)?.human_name ?? null;
}

export function policyHumanName(id?: string | null, options?: ResearchOptions | null): string {
  if (!id) return "—";
  return fromOptions(options?.policies, id) ?? POLICY_FALLBACK[id] ?? id;
}

export function riskHumanName(id?: string | null, options?: ResearchOptions | null): string {
  if (!id) return "—";
  return fromOptions(options?.risk_policies, id) ?? RISK_FALLBACK[id] ?? id;
}

/** Engineering run status → Russian wording used across the Lab. */
export function runStatusLabel(status?: string | null): string {
  switch ((status ?? "").toUpperCase()) {
    case "PENDING":
      return "Ожидает выполнения";
    case "RUNNING":
      return "Выполняется";
    case "SUCCESS":
      return "Готов";
    case "REUSED":
      return "Использован существующий результат";
    case "FAILED":
    case "ERROR":
      return "Ошибка";
    case "PASS":
      return "Инженерная проверка пройдена";
    default:
      return status || "Неизвестно";
  }
}

export function runStatusTone(
  status?: string | null,
): "success" | "warning" | "error" | "running" | "info" | "neutral" {
  switch ((status ?? "").toUpperCase()) {
    case "SUCCESS":
    case "PASS":
      return "success";
    case "REUSED":
      return "info";
    case "RUNNING":
    case "PENDING":
      return "running";
    case "FAILED":
    case "ERROR":
      return "error";
    default:
      return "neutral";
  }
}

export function launchOutcomeMessage(outcome?: string | null): string {
  if (outcome === "REUSE_EXISTING") {
    return "Такой эксперимент уже существует — открыт сохранённый результат, повторный расчёт не запускался.";
  }
  if (outcome === "CREATED") return "Эксперимент выполнен и сохранён в реестре.";
  return "";
}

export interface RegistrySortOption {
  id: string;
  label: string;
}

export const REGISTRY_SORTS: RegistrySortOption[] = [
  { id: "newest", label: "Сначала новые" },
  { id: "return", label: "По доходности" },
  { id: "max_drawdown", label: "По просадке" },
  { id: "turnover", label: "По обороту" },
  { id: "sharpe", label: "По Sharpe" },
];

export function experimentName(run: ResearchRunSummary): string {
  return run.research?.display_name ?? `Эксперимент #${run.id}`;
}

/** bps is 0.01 percentage point — spell it out for non-quant users. */
export function bpsLabel(bps?: number | null): string {
  if (bps == null || Number.isNaN(bps)) return "—";
  const formatted = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(bps);
  return `${formatted} bps`;
}

export function bpsHint(bps?: number | null): string {
  if (bps == null || Number.isNaN(bps)) return "";
  const pct = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 }).format(bps / 100);
  return `${pct} % от суммы сделки`;
}

/** Frozen policy/risk parameter names → Russian read-only rows. */
const PARAMETER_LABELS: Record<string, string> = {
  top_quantile: "Верхний квантиль отбора",
  entry_quantile: "Квантиль входа",
  exit_quantile: "Квантиль выхода",
  min_trade_weight_delta: "Минимальное изменение веса для сделки",
  rebalance: "Ребаланс",
  weighting: "Взвешивание",
  long_only: "Только длинные позиции",
  max_gross_exposure: "Максимальная экспозиция",
  max_single_weight: "Максимальная доля одного инструмента",
  dd_trigger: "Порог включения защиты",
  dd_recovery: "Порог восстановления",
  dd_risk_off_gross: "Экспозиция в режиме защиты",
  dd_normal_gross: "Экспозиция в обычном режиме",
  base_guardrails: "Базовые ограничения",
};

const PARAMETER_VALUES: Record<string, string> = {
  weekly_first_trading_day: "еженедельно, первый торговый день",
  equal_weight: "равными долями",
  RISK_GUARDRAILS_V0: "Базовые ограничения",
};

export function parameterLabel(key: string): string {
  return PARAMETER_LABELS[key] ?? key;
}

export function parameterValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? "да" : "нет";
  if (typeof value === "number") return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 4 }).format(value);
  const raw = String(value);
  return PARAMETER_VALUES[raw] ?? raw;
}

export function executionAssumptionRows(
  assumptions?: Record<string, unknown> | null,
): Array<{ label: string; value: string }> {
  const a = assumptions ?? {};
  return [
    { label: "Исполнение", value: a.execution === "Next Open" ? "На следующем открытии рынка (Next Open)" : String(a.execution ?? "—") },
    { label: "Дробные лоты", value: a.fractional_shares === false ? "нет" : "да" },
    { label: "Дивиденды", value: a.dividends === "excluded" ? "не учитываются (price return)" : String(a.dividends ?? "—") },
    { label: "Бенчмарк", value: String(a.benchmark ?? "—") },
    { label: "Плечо", value: a.no_leverage === false ? "разрешено" : "не используется" },
  ];
}

/** Selection guard for the compare action (backend enforces 2..5 as well). */
export function compareSelectionHint(count: number): string | null {
  if (count === 0) return "Отметьте 2–5 экспериментов для сравнения.";
  if (count === 1) return "Нужен минимум ещё один эксперимент.";
  if (count > MAX_COMPARE_RUNS) return `Можно сравнить не более ${MAX_COMPARE_RUNS} экспериментов.`;
  return null;
}

export function canCompare(count: number): boolean {
  return count >= MIN_COMPARE_RUNS && count <= MAX_COMPARE_RUNS;
}
