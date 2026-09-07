/** Human labels and stage mapping for Shadow Live Research dashboard. */

import type {
  ShadowLiveResponse,
  ShadowPendingOrderReason,
  ShadowPortfolioSummary,
} from "../../api/shadow";

/** Hero-level live experiment status (display mapping only). */
export type LiveExperimentUiStatus =
  | "positions_open"
  | "waiting_session"
  | "waiting_open_price"
  | "waiting_forward"
  | "updates_disabled"
  | "error";

export function liveExperimentStatusLabel(status: LiveExperimentUiStatus): string {
  switch (status) {
    case "positions_open":
      return "Позиции открыты";
    case "waiting_session":
      return "Ожидаем торговую сессию";
    case "waiting_open_price":
      return "Ожидаем цену открытия";
    case "waiting_forward":
      return "Ожидаем Forward-сигнал";
    case "updates_disabled":
      return "Живые обновления выключены";
    case "error":
      return "Ошибка эксперимента";
    default:
      return "Неизвестно";
  }
}

export function liveExperimentStatusTone(
  status: LiveExperimentUiStatus,
): "success" | "warning" | "error" | "running" | "info" | "neutral" {
  switch (status) {
    case "positions_open":
      return "success";
    case "waiting_session":
    case "waiting_open_price":
    case "waiting_forward":
      return "running";
    case "updates_disabled":
      return "neutral";
    case "error":
      return "error";
    default:
      return "info";
  }
}

function pendingReasonsOf(portfolio?: ShadowPortfolioSummary | null): ShadowPendingOrderReason[] {
  return portfolio?.pending_order_reasons ?? [];
}

/**
 * Map API facts → hero status. No trading logic — only presentation priority.
 */
export function deriveLiveExperimentStatus(input: {
  live?: ShadowLiveResponse | null;
  primary?: ShadowPortfolioSummary | null;
  hasForward?: boolean;
  loadError?: boolean;
}): LiveExperimentUiStatus {
  if (input.loadError) return "error";
  const primary = input.primary;
  const st = (primary?.status ?? "").toUpperCase();
  if (st === "ERROR" || st === "BLOCKED") return "error";

  const intradayEnabled =
    input.live?.intraday_enabled ??
    primary?.intraday_enabled ??
    false;
  if (!intradayEnabled) return "updates_disabled";

  if (st === "WAITING_FOR_SIGNAL" || st === "INITIALIZED" || input.hasForward === false) {
    return "waiting_forward";
  }

  const reasons = pendingReasonsOf(primary).map((r) => (r.reason ?? "").toUpperCase());
  if (reasons.some((r) => r === "OPEN_PRICE_NOT_AVAILABLE")) return "waiting_open_price";

  const livePositions = primary?.live?.positions?.length ?? 0;
  const posCount = primary?.position_count ?? livePositions;
  if (posCount > 0 || livePositions > 0) return "positions_open";

  if (
    reasons.some((r) =>
      [
        "NEXT_SESSION_NOT_STARTED",
        "WAITING_NEXT_SESSION",
        "MARKET_CLOSED",
        "NON_TRADING_DAY",
        "MIN_EXECUTION_DATE_NOT_REACHED",
      ].includes(r),
    ) ||
    st === "WAITING_FOR_FUTURE_MARKET_OPEN"
  ) {
    return "waiting_session";
  }

  if ((primary?.pending_orders ?? 0) > 0) return "waiting_session";
  return "waiting_forward";
}

export function isCalmMarketClosedStatus(status: LiveExperimentUiStatus): boolean {
  return status === "waiting_session" || status === "updates_disabled";
}

export const PORTFOLIO_HUMAN_NAMES: Record<string, string> = {
  SHADOW_HYSTERESIS_V1: "Рейтинговый портфель",
  SHADOW_HYSTERESIS_DD_V1: "Рейтинговый портфель + защита от просадки",
};

export const PORTFOLIO_HUMAN_SUBTITLES: Record<string, string> = {
  SHADOW_HYSTERESIS_V1: "Рейтинговая стратегия с удержанием",
  SHADOW_HYSTERESIS_DD_V1: "Та же стратегия + защита от глубокой просадки",
};

export function portfolioHumanName(name?: string | null): string {
  if (!name) return "Shadow-портфель";
  return PORTFOLIO_HUMAN_NAMES[name] ?? name;
}

export function portfolioHumanSubtitle(name?: string | null): string {
  if (!name) return "";
  return PORTFOLIO_HUMAN_SUBTITLES[name] ?? "";
}

export function shadowStatusLabel(status?: string | null): string {
  switch ((status ?? "").toUpperCase()) {
    case "INITIALIZED":
      return "Инициализирован";
    case "WAITING_FOR_SIGNAL":
      return "Ожидаем сигнал";
    case "DECISION_READY":
      return "Решение готово";
    case "WAITING_FOR_FUTURE_MARKET_OPEN":
      return "Ожидаем открытие рынка";
    case "ACTIVE":
      return "Активен";
    case "BLOCKED":
      return "Заблокирован";
    case "ERROR":
      return "Ошибка";
    default:
      return status || "Неизвестно";
  }
}

export function shadowStatusTone(
  status?: string | null,
): "success" | "warning" | "error" | "running" | "info" | "neutral" {
  switch ((status ?? "").toUpperCase()) {
    case "ACTIVE":
      return "success";
    case "WAITING_FOR_FUTURE_MARKET_OPEN":
    case "WAITING_FOR_SIGNAL":
    case "DECISION_READY":
      return "running";
    case "BLOCKED":
      return "warning";
    case "ERROR":
      return "error";
    default:
      return "neutral";
  }
}

export function riskModeLabel(mode?: string | null): string {
  switch ((mode ?? "").toLowerCase()) {
    case "normal":
      return "Нормальный режим";
    case "risk_off":
      return "Сниженная экспозиция";
    default:
      return mode || "—";
  }
}

export function orderActionLabel(side?: string | null, status?: string | null): string {
  const s = (side ?? "").toUpperCase();
  const st = (status ?? "").toUpperCase();
  if (st === "PENDING" && s === "BUY") return "Ожидает покупки";
  if (st === "PENDING" && s === "SELL") return "Ожидает продажи";
  if (st === "FILLED" && s === "BUY") return "Куплено";
  if (st === "FILLED" && s === "SELL") return "Продано";
  return s || "—";
}

export type StageKey =
  | "signal"
  | "decision"
  | "waiting_open"
  | "execution"
  | "observation";

export function operationalStages(status?: string | null): {
  current: StageKey;
  items: Array<{ key: StageKey; label: string; done: boolean; current: boolean }>;
} {
  const st = (status ?? "").toUpperCase();
  let current: StageKey = "signal";
  if (st === "WAITING_FOR_SIGNAL" || st === "INITIALIZED") current = "signal";
  else if (st === "DECISION_READY") current = "decision";
  else if (st === "WAITING_FOR_FUTURE_MARKET_OPEN") current = "waiting_open";
  else if (st === "ACTIVE") current = "observation";
  else if (st === "BLOCKED" || st === "ERROR") current = "waiting_open";

  const order: StageKey[] = ["signal", "decision", "waiting_open", "execution", "observation"];
  const labels: Record<StageKey, string> = {
    signal: "Прогноз сформирован",
    decision: "Решение принято",
    waiting_open: "Ожидаем открытие рынка",
    execution: "Исполнение",
    observation: "Наблюдение портфеля",
  };
  const idx = order.indexOf(current);
  return {
    current,
    items: order.map((key, i) => ({
      key,
      label: labels[key],
      done: i < idx,
      current: i === idx,
    })),
  };
}

/** Calendar days since activation (UTC date boundary). */
export function experimentAgeDays(activatedAt?: string | null, now = new Date()): number | null {
  if (!activatedAt) return null;
  const start = new Date(activatedAt);
  if (Number.isNaN(start.getTime())) return null;
  const ms = now.getTime() - start.getTime();
  return Math.max(0, Math.floor(ms / 86_400_000));
}

export function experimentAgeLabel(days: number | null): string {
  if (days == null) return "—";
  if (days === 0) return "менее суток";
  if (days === 1) return "1 день";
  if (days >= 2 && days <= 4) return `${days} дня`;
  return `${days} дней`;
}

/**
 * Deterministic maturity ladder by calendar days since activation.
 * Not a scientific score — only a UX gate against premature claims.
 */
export function experimentMaturity(days: number | null): { label: string; hint: string } {
  if (days == null) return { label: "—", hint: "" };
  if (days < 1) {
    return {
      label: "Старт",
      hint: "Эксперимент только запущен; статистических выводов пока нет.",
    };
  }
  if (days < 20) {
    return {
      label: "Накапливаем данные",
      hint: "Несколько дней forward-наблюдения недостаточны для оценки качества стратегии.",
    };
  }
  if (days < 60) {
    return {
      label: "Ранняя история",
      hint: "Первые 20d-исходы модели могут становиться наблюдаемыми; выводы всё ещё ранние.",
    };
  }
  return {
    label: "Достаточно данных для первичного анализа",
    hint: "Можно сравнивать портфели осторожно; это всё ещё research, не proof of edge.",
  };
}

export function pickPortfolioA(portfolios: ShadowPortfolioSummary[]): ShadowPortfolioSummary | undefined {
  return portfolios.find((p) => p.name === "SHADOW_HYSTERESIS_V1") ?? portfolios[0];
}

export function pickPortfolioB(portfolios: ShadowPortfolioSummary[]): ShadowPortfolioSummary | undefined {
  return portfolios.find((p) => p.name === "SHADOW_HYSTERESIS_DD_V1") ?? portfolios[1];
}

export function shortHash(value?: string | null, n = 8): string {
  if (!value) return "—";
  return value.length <= n ? value : value.slice(0, n);
}
