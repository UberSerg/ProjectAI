/** Human labels for Daily Research Cycle V0 statuses and steps. */

import type { OutcomeMaturity, ResearchCycleSchedule } from "../../api/researchCycle";
import { shadowStatusLabel } from "../shadow/helpers";

const HEALTH_LABELS: Record<string, string> = {
  IN_SYNC: "Контур синхронизирован",
  WAITING_FOR_MARKET: "Ожидаем новые рыночные данные",
  LAGGING: "Есть отставание downstream",
  BLOCKED: "Контур заблокирован",
  RUNNING: "Идёт ежедневный цикл",
};

const STATUS_LABELS: Record<string, string> = {
  SUCCESS: "успешно",
  SUCCEEDED: "успешно",
  COMPLETED: "завершено",
  WARNING: "предупреждение",
  ERROR: "ошибка",
  FAILED: "ошибка",
  RUNNING: "выполняется",
  PENDING: "ожидает",
  NO_CHANGES: "без изменений",
  SKIPPED_NOT_DUE: "не требовалось",
  WAITING_FOR_MARKET: "ожидаем рынок",
  BLOCKED: "заблокирован",
  IN_SYNC: "синхронизирован",
  LAGGING: "отставание",
  PENDING_OUTCOME: "ожидаем outcome",
  PARTIALLY_MATURED: "частично созрело",
  EVALUATED: "оценено",
  INVALID: "некорректно",
};

const STEP_LABELS: Record<string, string> = {
  SOURCE_DISCOVERY: "Обнаружение источников",
  MARKET_UPDATE: "Обновление рынка",
  CBR_UPDATE: "Обновление ЦБ РФ",
  CORPORATE_ACTION_UPDATE: "Корпоративные действия",
  ANALYTICS_V2: "Analytics V2",
  TECHNICAL_V2: "Technical V2",
  RELATIONS_V2: "Relations V2",
  FORWARD_SIGNAL: "Forward Signal",
  SHADOW_ADVANCE: "Shadow advance",
  FORWARD_OUTCOME_EVALUATION: "Оценка Forward outcomes",
  FINALIZE: "Фиксация результата",
};

export function researchCycleHealthLabel(
  code?: string | null,
  humanFallback?: string | null,
): string {
  if (humanFallback) return humanFallback;
  if (!code) return "—";
  const key = code.toUpperCase();
  return HEALTH_LABELS[key] ?? code;
}

export function researchCycleStatusLabel(code?: string | null): string {
  if (!code) return "—";
  const key = code.toUpperCase();
  return STATUS_LABELS[key] ?? code;
}

/** Capitalized status for badges / key-value rows. */
export function researchCycleStatusDisplay(code?: string | null): string {
  const raw = researchCycleStatusLabel(code);
  if (raw === "—" || raw === code) return raw;
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

export function researchCycleStepLabel(name?: string | null): string {
  if (!name) return "—";
  return STEP_LABELS[name] ?? STEP_LABELS[name.toUpperCase()] ?? name;
}

export function researchCycleStatusTone(
  code?: string | null,
): "success" | "warning" | "error" | "running" | "info" | "neutral" {
  switch ((code ?? "").toUpperCase()) {
    case "SUCCESS":
    case "SUCCEEDED":
    case "COMPLETED":
    case "IN_SYNC":
    case "EVALUATED":
    case "NO_CHANGES":
      return "success";
    case "WARNING":
    case "LAGGING":
    case "BLOCKED":
    case "PARTIALLY_MATURED":
    case "SKIPPED_NOT_DUE":
      return "warning";
    case "ERROR":
    case "FAILED":
    case "INVALID":
      return "error";
    case "RUNNING":
    case "PENDING":
    case "WAITING_FOR_MARKET":
    case "PENDING_OUTCOME":
      return "running";
    default:
      return "neutral";
  }
}

export function formatOutcomeMaturity(maturity?: OutcomeMaturity | null): string {
  if (!maturity) return "—";
  const n = maturity.future_trading_observations;
  const req = maturity.required ?? 20;
  if (maturity.matured) return `${maturity.status} (${n}/${req})`;
  return `Ожидаем ${n}/${req}`;
}

export function formatAutomaticSchedule(
  automatic?: string | null,
  schedule?: ResearchCycleSchedule | null,
): string {
  const enabled =
    automatic === "enabled" || schedule?.enabled === true;
  if (enabled) {
    const hh = String(schedule?.hour ?? 18).padStart(2, "0");
    const mm = String(schedule?.minute ?? 30).padStart(2, "0");
    const tz = schedule?.timezone ?? "UTC";
    return `включено (${hh}:${mm} ${tz})`;
  }
  return "выключено";
}

export function shadowSummaryFromWatermarks(
  portfolios?: Array<{
    status?: string | null;
    last_processed_market_date?: string | null;
  }> | null,
): string {
  if (!portfolios?.length) return "—";
  const dates = portfolios
    .map((p) => p.last_processed_market_date)
    .filter(Boolean) as string[];
  const latest = dates.sort().at(-1);
  const statuses = [
    ...new Set(
      portfolios
        .map((p) => shadowStatusLabel(p.status))
        .filter((s) => s && s !== "Неизвестно"),
    ),
  ];
  const statusPart = statuses.length ? statuses.join(", ") : "n/a";
  return latest ? `${statusPart} · до ${latest}` : statusPart;
}
