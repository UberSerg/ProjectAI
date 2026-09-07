/** Human labels and stage mapping for Shadow Live Research dashboard. */

import type {
  ShadowDailyOperations,
  ShadowLiveResponse,
  ShadowOrder,
  ShadowPendingOrderReason,
  ShadowPortfolioSummary,
} from "../../api/shadow";

export const EXPERIMENT_GROUP_V1 = "SHADOW_FORWARD_V0";
export const EXPERIMENT_GROUP_V2 = "SHADOW_PORTFOLIO_REALISM_V2";

export const PORTFOLIO_A_V1 = "SHADOW_HYSTERESIS_V1";
export const PORTFOLIO_B_V1 = "SHADOW_HYSTERESIS_DD_V1";
export const PORTFOLIO_A_V2 = "SHADOW_HYSTERESIS_V2";
export const PORTFOLIO_B_V2 = "SHADOW_HYSTERESIS_DD_V2";

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
  SHADOW_HYSTERESIS_V1: "Рейтинговый портфель (V1)",
  SHADOW_HYSTERESIS_DD_V1: "Рейтинговый + защита от просадки (V1)",
  SHADOW_HYSTERESIS_V2: "Рейтинговый портфель",
  SHADOW_HYSTERESIS_DD_V2: "Рейтинговый портфель + защита от просадки",
};

export const PORTFOLIO_HUMAN_SUBTITLES: Record<string, string> = {
  SHADOW_HYSTERESIS_V1: "Legacy · дробные единицы",
  SHADOW_HYSTERESIS_DD_V1: "Legacy · дробные единицы + Drawdown Guard",
  SHADOW_HYSTERESIS_V2: "Realism V2 · целые лоты MOEX",
  SHADOW_HYSTERESIS_DD_V2: "Realism V2 · целые лоты + защита от просадки",
};

export function portfolioHumanName(name?: string | null): string {
  if (!name) return "Shadow-портфель";
  return PORTFOLIO_HUMAN_NAMES[name] ?? name;
}

export function portfolioHumanSubtitle(name?: string | null): string {
  if (!name) return "";
  return PORTFOLIO_HUMAN_SUBTITLES[name] ?? "";
}

export function isRealismV2Portfolio(p?: ShadowPortfolioSummary | null): boolean {
  if (!p) return false;
  if (p.experiment_group === EXPERIMENT_GROUP_V2) return true;
  if (p.lot_aware) return true;
  return p.name === PORTFOLIO_A_V2 || p.name === PORTFOLIO_B_V2;
}

export function isLegacyV1Portfolio(p?: ShadowPortfolioSummary | null): boolean {
  if (!p) return false;
  if (p.experiment_group === EXPERIMENT_GROUP_V1) return true;
  return p.name === PORTFOLIO_A_V1 || p.name === PORTFOLIO_B_V1;
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

/** True when age is too short for strategy claims (UX warning only). */
export function hasFewObservations(days: number | null): boolean {
  return days != null && days < 20;
}

/** Display-only lots × lot_size = units (no accounting). */
export function formatLotsUnits(input: {
  lots?: number | null;
  lot_size?: number | null;
  quantity?: number | null;
}): string {
  const lots = input.lots;
  const lotSize = input.lot_size;
  const qty = input.quantity;
  if (lots != null && lotSize != null && lotSize > 0) {
    const units = qty != null ? qty : lots * lotSize;
    return `${lots}×${lotSize}=${units}`;
  }
  if (qty != null) return String(qty);
  return "—";
}

export function orderLotsFromMeta(order: ShadowOrder): {
  lots?: number | null;
  lot_size?: number | null;
  units?: number | null;
} {
  const meta = order.metadata ?? {};
  const lots = typeof meta.lots === "number" ? meta.lots : null;
  const lot_size = typeof meta.lot_size === "number" ? meta.lot_size : null;
  const units = typeof meta.units === "number" ? meta.units : order.quantity;
  return { lots, lot_size, units };
}

export function pickPortfolioA(portfolios: ShadowPortfolioSummary[]): ShadowPortfolioSummary | undefined {
  return (
    portfolios.find((p) => p.name === PORTFOLIO_A_V2) ??
    portfolios.find((p) => p.name === PORTFOLIO_A_V1) ??
    portfolios.find((p) => isRealismV2Portfolio(p) && !String(p.name).includes("DD")) ??
    portfolios[0]
  );
}

export function pickPortfolioB(portfolios: ShadowPortfolioSummary[]): ShadowPortfolioSummary | undefined {
  return (
    portfolios.find((p) => p.name === PORTFOLIO_B_V2) ??
    portfolios.find((p) => p.name === PORTFOLIO_B_V1) ??
    portfolios.find((p) => isRealismV2Portfolio(p) && String(p.name).includes("DD")) ??
    portfolios[1]
  );
}

/** Prefer V2 arms for primary UI; keep V1 as legacy list. */
export function partitionShadowPortfolios(portfolios: ShadowPortfolioSummary[]): {
  primary: ShadowPortfolioSummary[];
  legacy: ShadowPortfolioSummary[];
  hasV2: boolean;
} {
  const v2 = portfolios.filter(isRealismV2Portfolio);
  const v1 = portfolios.filter(isLegacyV1Portfolio);
  const other = portfolios.filter((p) => !isRealismV2Portfolio(p) && !isLegacyV1Portfolio(p));
  if (v2.length > 0) {
    return { primary: [...v2, ...other], legacy: v1, hasV2: true };
  }
  return { primary: [...v1, ...other], legacy: [], hasV2: false };
}

export type LifecycleStepKey =
  | "close"
  | "forecast"
  | "plan"
  | "orders"
  | "open"
  | "positions"
  | "mark";

export type LifecycleStepState = "done" | "current" | "pending";

export function buildDailyLifecycleSteps(input: {
  ops?: ShadowDailyOperations | null;
  primary?: ShadowPortfolioSummary | null;
}): Array<{ key: LifecycleStepKey; label: string; state: LifecycleStepState }> {
  const ops = input.ops;
  const primary = input.primary;
  const eodReady = Boolean(ops?.eod_readiness?.ready ?? ops?.latest_complete_eod_date);
  const hasForward = Boolean(ops?.latest_forward_as_of);
  const planPresent =
    (ops?.order_plan_status ?? "").toUpperCase() === "PRESENT" ||
    Boolean(primary?.order_plan) ||
    (primary?.skipped?.length ?? 0) > 0;
  const hasOrders = (ops?.pending_orders ?? primary?.pending_orders ?? 0) > 0 || (primary?.fills ?? 0) > 0;
  const awaitingOpen =
    (ops?.status_code ?? "").toUpperCase() === "PENDING_ORDERS_AWAITING_OPEN" ||
    (primary?.status ?? "").toUpperCase() === "WAITING_FOR_FUTURE_MARKET_OPEN";
  const hasPositions =
    (primary?.live?.positions?.length ?? 0) > 0 || (primary?.position_count ?? 0) > 0;
  const hasMarks =
    (primary?.live?.quote_coverage ?? 0) > 0 ||
    (primary?.live?.positions ?? []).some((p) => p.mark_price != null);

  const flags = [eodReady, hasForward, planPresent, hasOrders, awaitingOpen || hasPositions, hasPositions, hasMarks];
  let currentIdx = flags.findIndex((f) => !f);
  if (currentIdx < 0) currentIdx = flags.length - 1;
  // If ready_for_next and pending open, highlight «Открытие»
  if (ops?.ready_for_next_session && awaitingOpen) currentIdx = 4;

  const labels: Array<{ key: LifecycleStepKey; label: string }> = [
    { key: "close", label: "Закрытие" },
    { key: "forecast", label: "Прогноз" },
    { key: "plan", label: "План" },
    { key: "orders", label: "Ордера" },
    { key: "open", label: "Открытие" },
    { key: "positions", label: "Позиции" },
    { key: "mark", label: "Оценка" },
  ];

  return labels.map((item, i) => ({
    ...item,
    state: (i < currentIdx ? "done" : i === currentIdx ? "current" : "pending") as LifecycleStepState,
  }));
}

export function readinessHeadline(ops?: ShadowDailyOperations | null): {
  ready: boolean;
  code: string | null;
  short: string;
} {
  if (!ops) {
    return { ready: false, code: null, short: "Статус готовности ещё не загружен" };
  }
  const ready = Boolean(ops.ready_for_next_session);
  const code =
    ops.next_session_preparation_status ??
    ops.pipeline?.next_session_preparation_status ??
    ops.status_code ??
    ops.blocker_code ??
    null;
  return {
    ready,
    code,
    short: ready ? "READY" : "NOT READY",
  };
}

export function shortHash(value?: string | null, n = 8): string {
  if (!value) return "—";
  return value.length <= n ? value : value.slice(0, n);
}

/** Product stage buckets for next-session prep (mega task §37). */
export type NextSessionStage = "WAITING_EOD" | "PROCESSING" | "READY" | "BLOCKED";

export type StatusTone = "success" | "warning" | "error" | "running" | "info" | "neutral";

export function currentSessionCode(ops?: ShadowDailyOperations | null): string | null {
  return ops?.current_session_status ?? ops?.pipeline?.current_session_status ?? null;
}

export function nextSessionPrepCode(ops?: ShadowDailyOperations | null): string | null {
  return (
    ops?.next_session_preparation_status ??
    ops?.pipeline?.next_session_preparation_status ??
    ops?.status_code ??
    null
  );
}

export function isMidSessionActivation(ops?: ShadowDailyOperations | null): boolean {
  if (ops?.mid_session_activation ?? ops?.pipeline?.mid_session_activation) return true;
  const code = (currentSessionCode(ops) ?? "").toUpperCase();
  return (
    code === "MID_SESSION_ACTIVATION_WAIT_NEXT_OPEN" || code === "FILLS_BLOCKED_ORDER_AFTER_OPEN"
  );
}

export function automationWarningText(ops?: ShadowDailyOperations | null): string | null {
  const warning =
    ops?.automation?.warning ?? ops?.pipeline?.automation_warning ?? null;
  if (typeof warning === "string" && warning.trim()) return warning.trim();
  return null;
}

export function mapNextSessionStage(prepCode?: string | null): NextSessionStage {
  const code = (prepCode ?? "").toUpperCase();
  if (
    code === "READY_FOR_NEXT_SESSION" ||
    code === "READY_NO_REBALANCE" ||
    code === "PENDING_ORDERS_AWAITING_OPEN"
  ) {
    return "READY";
  }
  if (code === "WAITING_FOR_MARKET_COMPLETE") return "WAITING_EOD";
  if (
    code === "WAITING_FOR_ANALYTICS" ||
    code === "WAITING_FOR_TECHNICAL" ||
    code === "WAITING_FOR_RELATIONS" ||
    code === "WAITING_FOR_FORWARD" ||
    code === "WAITING_FOR_SHADOW_PLAN" ||
    code === "CYCLE_RUNNING" ||
    code === "ORDER_PLAN_PENDING"
  ) {
    return "PROCESSING";
  }
  return "BLOCKED";
}

export function nextSessionStageTone(stage: NextSessionStage): StatusTone {
  switch (stage) {
    case "READY":
      return "success";
    case "WAITING_EOD":
    case "PROCESSING":
      return "running";
    case "BLOCKED":
      return "error";
    default:
      return "warning";
  }
}

export function todaySessionHeadline(ops?: ShadowDailyOperations | null): {
  code: string | null;
  title: string;
  messageRu: string | null;
  midSession: boolean;
} {
  const code = currentSessionCode(ops);
  const midSession = isMidSessionActivation(ops);
  const summary = ops?.today_summary ?? ops?.pipeline?.today_summary;
  const messageRu = summary?.message_ru ?? null;
  if (midSession) {
    return {
      code: code ?? "MID_SESSION_ACTIVATION_WAIT_NEXT_OPEN",
      title: "Первая сделка — на следующем открытии",
      messageRu:
        messageRu ??
        "Эксперимент запущен сегодня после открытия рынка. Kraken не использует уже известную цену открытия задним числом.",
      midSession: true,
    };
  }
  const upper = (code ?? "").toUpperCase();
  let title = "Сегодня";
  if (upper === "NO_ACTIVITY") title = "Сегодня сделок не требовалось";
  else if (upper === "PENDING_ORDERS_AWAITING_OPEN") title = "Ждём открытия рынка";
  else if (upper === "SESSION_ACTIVE") title = "Сессия активна";
  else if (upper === "FILLS_BLOCKED_ORDER_AFTER_OPEN") {
    title = "Первая сделка — на следующем открытии";
  } else if (summary?.message_ru) title = summary.message_ru;
  else if (code) title = code;
  return { code, title, messageRu, midSession };
}

export function pipelineWatermarks(ops?: ShadowDailyOperations | null): Array<{
  key: string;
  label: string;
  value: string | null;
}> {
  const wm = ops?.pipeline?.watermarks;
  const flat = ops?.watermarks;
  const pick = (short: string, long: string): string | null => {
    const fromPipe = wm?.[short];
    if (fromPipe != null && fromPipe !== "") return String(fromPipe);
    const fromFlat = flat?.[long] ?? flat?.[short];
    if (fromFlat != null && fromFlat !== "") return String(fromFlat);
    return null;
  };
  return [
    { key: "market", label: "Рынок", value: pick("market", "raw_market_latest_date") },
    { key: "analytics", label: "Analytics", value: pick("analytics", "analytics_v2_latest_date") },
    { key: "forward", label: "Forward", value: pick("forward", "forward_latest_as_of") },
    { key: "plan", label: "План", value: pick("shadow_plan", "shadow_plan_latest_as_of") },
  ];
}

/** MOEX equities open ~07:00 UTC (10:00 MSK) — display helper only. */
export function sessionOpenIsoForDate(isoDate?: string | null): string | null {
  if (!isoDate) return null;
  const day = isoDate.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  return `${day}T07:00:00+00:00`;
}

export function earliestActivationIso(ops?: ShadowDailyOperations | null): string | null {
  const times = (ops?.portfolios ?? [])
    .map((p) => p.activated_at)
    .filter((v): v is string => Boolean(v));
  if (!times.length) return null;
  return times.slice().sort()[0] ?? null;
}
