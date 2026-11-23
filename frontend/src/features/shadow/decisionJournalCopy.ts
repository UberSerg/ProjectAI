/**
 * Decision Journal V4 — display copy and reason mapping from structured API facts only.
 * Does not invent P&L, fills, or post-hoc explanations.
 */

import type {
  ShadowJournalCandidateTrace,
  ShadowJournalDay,
  ShadowJournalFill,
  ShadowJournalNav,
  ShadowJournalOrder,
} from "../../api/shadow";

/** Product copy when historical why/trace was not persisted. */
export const JOURNAL_MISSING_REASON_RU =
  "Подробная причина этого исторического решения не сохранялась";

export const JOURNAL_ACTION_LABELS: Record<string, string> = {
  BUY: "Покупка",
  SELL: "Продажа",
  ENTER: "Вход",
  EXIT: "Выход",
  HOLD: "Удержание",
  SKIP: "Пропуск",
  REVIEW_HOLD: "Проверка решения: удержать",
  REVIEW: "Проверка решения",
  ROTATE: "Ротация",
  DATA_HOLD: "Удержание (данные)",
  ENTER_TOP20: "Вход",
};

export const JOURNAL_ORDER_STATUS_LABELS: Record<string, string> = {
  FILLED: "Исполнено",
  PENDING: "Ожидает исполнения",
  OPEN: "Ожидает исполнения",
  NEW: "Ожидает исполнения",
  SUBMITTED: "Ожидает исполнения",
  WORKING: "Ожидает исполнения",
  CANCELLED: "Отменено",
  CANCELED: "Отменено",
  REJECTED: "Отклонено",
  PARTIAL: "Частично исполнено",
  PARTIALLY_FILLED: "Частично исполнено",
  EXPIRED: "Истёк срок заявки",
};

export const JOURNAL_REASON_LABELS: Record<string, string> = {
  TOP_ENTRY_BAND: "В зоне входа по рейтингу",
  WITHIN_EXIT_BAND: "В зоне удержания / выхода",
  EXIT_BAND_INSUFFICIENT_EDGE: "Ревизия: нет достаточного чистого edge для ротации",
  WITHIN_POLICY_SELECTION: "Остаётся в политике отбора",
  REVIEW_TRIGGER: "Сработал триггер ревизии",
  NET_EDGE_POSITIVE: "Чистый edge после издержек положительный",
  INSUFFICIENT_NET_EDGE: "Чистый edge после издержек недостаточен",
  RISK_FORCED_EXIT: "Принудительный выход по риску",
  RISK_FORCED_REDUCE: "Принудительное сокращение по риску",
  EXPLICIT_EXIT_TO_CASH: "Явный выход в кэш",
  STALE_SIGNAL: "Устаревший сигнал",
  NON_COMPARABLE_PREDICTION: "Прогноз несопоставим с заменой",
  MISSING_PRICE_OR_QTY: "Нет цены или количества",
  NO_COMPARABLE_REPLACEMENT: "Нет сопоставимой замены",
  REPLACEMENT_DATA_INCOMPLETE: "Данные по замене неполные",
  FEE_MODEL_MISSING: "Нет модели комиссий для оценки",
  POLICY_ENTER_FREE_CAPACITY: "Вход при свободной ёмкости",
  ENTER_TOP20: "Вход в топ по рейтингу стратегии",
  REBALANCE_BUY: "Ребалансировка: покупка",
  REBALANCE_SELL: "Ребалансировка: продажа",
};

export function journalDecisionActionLabel(action?: string | null): string {
  const key = (action ?? "").trim().toUpperCase();
  if (!key) return "—";
  if (JOURNAL_ACTION_LABELS[key]) return JOURNAL_ACTION_LABELS[key];
  if (key.startsWith("REVIEW")) return "Проверка решения";
  if (key.startsWith("ROTATE_TO_")) {
    return `Ротация → ${key.slice("ROTATE_TO_".length)}`;
  }
  if (key.startsWith("ENTER")) return "Вход";
  if (key.startsWith("EXIT")) return "Выход";
  return key;
}

/** Human order/fill status. Unknown → neutral label; raw stays for technical disclosure. */
export function journalOrderStatusLabel(status?: string | null): string {
  const key = (status ?? "").trim().toUpperCase();
  if (!key) return "Статус не определён";
  if (JOURNAL_ORDER_STATUS_LABELS[key]) return JOURNAL_ORDER_STATUS_LABELS[key];
  return "Статус не определён";
}

export function formatJournalDayTitle(isoDate?: string | null): string {
  if (!isoDate) return "—";
  const d = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(d.getTime())) return isoDate;
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  }).format(d);
}

export function journalReasonCodeLabel(code?: string | null): string {
  if (!code) return "—";
  const key = code.trim().toUpperCase();
  if (JOURNAL_REASON_LABELS[key]) return JOURNAL_REASON_LABELS[key];
  if (key.startsWith("ROTATE_TO_")) {
    return `Ротация на ${key.slice("ROTATE_TO_".length)}`;
  }
  return code;
}

function formatEdge(netEdge?: number | null): string {
  if (netEdge == null || !Number.isFinite(netEdge)) return "";
  return ` Чистый edge: ${netEdge}.`;
}

function joinedReasons(codes: string[]): string {
  return codes.map(journalReasonCodeLabel).filter(Boolean).join("; ");
}

/**
 * Human sentence for BUY/SELL/HOLD/REVIEW/ROTATE from structured facts only.
 */
export function journalCandidateHumanReason(input: {
  action?: string | null;
  reason_codes?: string[] | null;
  replacement_ticker?: string | null;
  net_edge?: number | null;
}): string {
  const action = (input.action ?? "").trim().toUpperCase();
  const codes = (input.reason_codes ?? []).map((c) => String(c));
  const reasons = joinedReasons(codes);
  const replacement = input.replacement_ticker?.trim().toUpperCase() || null;
  const edge = formatEdge(input.net_edge);

  if (action === "REVIEW_HOLD") {
    // Explicit REVIEW_HOLD only — do not imply HOLD from bare REVIEW.
    const why = reasons || JOURNAL_MISSING_REASON_RU;
    const alt = replacement ? ` Кандидат на замену: ${replacement}.` : "";
    return `Ревизия: позиция удержана — ${why}.${alt}${edge}`.trim();
  }
  if (action === "REVIEW" || action.startsWith("REVIEW")) {
    const alt = replacement ? ` Кандидат на замену: ${replacement}.` : "";
    if (reasons) return `Ревизия: ${reasons}.${alt}${edge}`.trim();
    return `Ревизия.${alt}${edge}`.trim() || JOURNAL_MISSING_REASON_RU;
  }
  if (action === "ROTATE" || action.startsWith("ROTATE")) {
    const target = replacement ? ` на ${replacement}` : "";
    // Never invent "чистый edge" when reason codes are absent.
    if (reasons) return `Ротация${target}: ${reasons}.`;
    if (replacement) return `Ротация на ${replacement}.`;
    return "Ротация.";
  }
  if (action === "BUY" || action === "ENTER") {
    const base = action === "ENTER" ? "Вход в позицию" : "Покупка";
    if (reasons) return `${base}: ${reasons}.${edge}`.trim();
    return `${base}.${edge}`.trim();
  }
  if (action === "SELL" || action === "EXIT") {
    const base = action === "EXIT" ? "Выход из позиции" : "Продажа";
    if (reasons) return `${base}: ${reasons}.${edge}`.trim();
    return `${base}.${edge}`.trim();
  }
  if (action === "HOLD" || action === "DATA_HOLD") {
    const base = action === "DATA_HOLD" ? "Удержание (ограничение данных)" : "Удержание позиции";
    if (reasons) return `${base}: ${reasons}.${edge}`.trim();
    return `${base}.${edge}`.trim();
  }
  if (reasons) return `${journalDecisionActionLabel(action)}: ${reasons}.${edge}`.trim();
  if (!action) return JOURNAL_MISSING_REASON_RU;
  return journalDecisionActionLabel(action);
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

/** Optional day-level provenance / quality fields (present only when API sends them). */
export type JournalDayQualityView = ShadowJournalDay & {
  history_kind?: string | null;
  valuation_freshness?: string | null;
  valuation_status?: string | null;
  drawdown_quality?: string | null;
  nav_quality?: string | null;
  metadata?: Record<string, unknown> | null;
};

export type JournalNavQualityView = ShadowJournalNav & {
  drawdown_quality?: string | null;
  quality?: string | null;
  metadata?: Record<string, unknown> | null;
};

function readMetaString(meta: Record<string, unknown> | null | undefined, key: string): string | null {
  if (!meta) return null;
  const v = meta[key];
  if (typeof v === "string" && v.trim()) return v.trim();
  return null;
}

export function dayHistoryKind(day: JournalDayQualityView): string | null {
  const direct = (day.history_kind ?? "").trim();
  if (direct) return direct.toUpperCase();
  const fromMeta =
    readMetaString(day.metadata, "history_kind") ??
    readMetaString(day.metadata, "provenance_kind");
  return fromMeta ? fromMeta.toUpperCase() : null;
}

export function historyKindLabel(kind?: string | null): string | null {
  const k = (kind ?? "").toUpperCase();
  if (!k) return null;
  if (k === "LIVE" || k === "RECORDED_LIVE") return "Запись LIVE";
  if (k === "COUNTERFACTUAL_REPLAY" || k === "COUNTERFACTUAL" || k === "REPLAY") {
    return "Историческая реконструкция";
  }
  return kind ?? null;
}

export function dayValuationFreshness(day: JournalDayQualityView): string | null {
  const direct = (day.valuation_freshness ?? "").trim();
  if (direct) return direct.toUpperCase();
  return readMetaString(day.metadata, "valuation_freshness")?.toUpperCase() ?? null;
}

export function valuationFreshnessLabel(freshness?: string | null): string | null {
  const f = (freshness ?? "").toUpperCase();
  if (!f) return null;
  switch (f) {
    case "FRESH":
      return "Оценка свежая";
    case "STALE":
      return "Данные требуют обновления";
    case "MIXED":
      return "Оценка смешанная";
    case "UNAVAILABLE":
      return "Оценка недоступна";
    case "PARTIAL":
      return "Оценка частичная";
    default:
      return freshness ?? null;
  }
}

/**
 * Legacy / limited DD warning only from explicit quality metadata — never from magnitude.
 */
export function drawdownQualityWarning(
  day: JournalDayQualityView,
  nav?: JournalNavQualityView | null,
): string | null {
  const candidates = [
    day.drawdown_quality,
    day.nav_quality,
    nav?.drawdown_quality,
    nav?.quality,
    readMetaString(day.metadata, "drawdown_quality"),
    readMetaString(day.metadata, "nav_quality"),
    readMetaString(nav?.metadata ?? null, "drawdown_quality"),
    readMetaString(nav?.metadata ?? null, "quality"),
  ]
    .map((v) => (v ?? "").trim().toUpperCase())
    .filter(Boolean);

  for (const q of candidates) {
    if (q === "LIMITED" || q === "INVALID" || q === "LEGACY_ANOMALY" || q === "UNTRUSTWORTHY") {
      return "Просадка помечена как ограниченно достоверная / невалидная в метаданных. Не интерпретируйте величину как точный факт.";
    }
  }
  return null;
}

/** NAV is shown only when the day payload includes a nav object (API fact). */
export function hasTrustworthyNav(day: JournalDayQualityView): boolean {
  return day.nav != null && typeof day.nav.nav === "number" && Number.isFinite(day.nav.nav);
}

/** Unique tickers present for the day (candidates / orders / fills). */
export function dayTickers(day: ShadowJournalDay): string[] {
  const set = new Set<string>();
  for (const c of day.candidates) {
    const t = (c.ticker ?? "").trim().toUpperCase();
    if (t) set.add(t);
  }
  for (const o of day.orders) {
    const t = (o.ticker ?? "").trim().toUpperCase();
    if (t) set.add(t);
  }
  for (const f of day.fills) {
    const t = (f.ticker ?? "").trim().toUpperCase();
    if (t) set.add(t);
  }
  return Array.from(set).sort();
}

export type DecisionChainLink = {
  decisionId: number | null;
  order: ShadowJournalOrder | null;
  fills: ShadowJournalFill[];
  /** True only when order.status is an open/pending state — never inferred from missing fills alone. */
  pending: boolean;
};

const PENDING_ORDER_STATUSES = new Set([
  "PENDING",
  "NEW",
  "OPEN",
  "SUBMITTED",
  "WORKING",
  "PARTIAL",
  "PARTIALLY_FILLED",
]);
const TERMINAL_ORDER_STATUSES = new Set([
  "FILLED",
  "CANCELLED",
  "CANCELED",
  "REJECTED",
  "EXPIRED",
]);

/** Pending is a real order status — absence of same-day fills is not proof of pending. */
export function isJournalOrderPendingStatus(status?: string | null): boolean {
  const st = (status ?? "").trim().toUpperCase();
  if (!st) return false;
  return PENDING_ORDER_STATUSES.has(st);
}

export function isJournalOrderTerminalStatus(status?: string | null): boolean {
  const st = (status ?? "").trim().toUpperCase();
  return TERMINAL_ORDER_STATUSES.has(st);
}

/**
 * Build Decision → Order → Fill links by real IDs.
 * Pending uses order.status; FILLED/CANCELLED/REJECTED without same-day fills stay non-pending.
 */
export function orderLinkedFills(order: ShadowJournalOrder, day: ShadowJournalDay): ShadowJournalFill[] {
  if (Array.isArray(order.fills) && order.fills.length > 0) return order.fills;
  return day.fills.filter((f) => f.order_id === order.id);
}

export function buildDecisionOrderFillChains(day: ShadowJournalDay): DecisionChainLink[] {
  const fillsByOrder = new Map<number, ShadowJournalFill[]>();
  for (const f of day.fills) {
    const list = fillsByOrder.get(f.order_id) ?? [];
    list.push(f);
    fillsByOrder.set(f.order_id, list);
  }
  for (const order of day.orders) {
    if (Array.isArray(order.fills)) {
      for (const f of order.fills) {
        const list = fillsByOrder.get(order.id) ?? [];
        if (!list.some((x) => x.id === f.id)) list.push(f);
        fillsByOrder.set(order.id, list);
      }
    }
  }

  const links: DecisionChainLink[] = [];
  const seenOrders = new Set<number>();

  for (const order of day.orders) {
    seenOrders.add(order.id);
    const fills = orderLinkedFills(order, day);
    links.push({
      decisionId: order.decision_id ?? null,
      order,
      fills,
      pending: isJournalOrderPendingStatus(order.status),
    });
  }

  for (const [orderId, fills] of fillsByOrder) {
    if (seenOrders.has(orderId)) continue;
    links.push({
      decisionId: null,
      order: null,
      fills,
      pending: false,
    });
  }

  return links;
}

/** Closed-card headline from confirmed order counts only. */
export function dayClosedHeadline(day: ShadowJournalDay): string {
  const buy = day.counts.buy_orders ?? day.counts.buy ?? 0;
  const sell = day.counts.sell_orders ?? day.counts.sell ?? 0;
  const orders = day.counts.orders ?? day.orders.length;
  if (buy > 0 && sell === 0) {
    return `Kraken сформировал ${buy} ${pluralZayavki(buy)} на покупку`;
  }
  if (sell > 0 && buy === 0) {
    return `Kraken сформировал ${sell} ${pluralZayavki(sell)} на продажу`;
  }
  if (orders > 0) {
    return `Kraken сформировал ${orders} ${pluralZayavki(orders)}`;
  }
  if (day.decision) return "Kraken зафиксировал решение без заявок";
  return "За этот день отдельных заявок нет";
}

export function dayWhatHappenedSummary(day: ShadowJournalDay): string {
  const buy = day.counts.buy_orders ?? day.counts.buy ?? 0;
  const filled = day.counts.filled_orders ?? 0;
  const cancelled = day.counts.cancelled_orders ?? 0;
  const later = day.orders.some((o) => o.execution_timing === "later");
  const parts: string[] = [];
  if (buy > 0) {
    parts.push(`Система сформировала ${buy} ${pluralZayavki(buy)} на покупку`);
  } else if (day.counts.orders > 0) {
    parts.push(`Система сформировала ${day.counts.orders} ${pluralZayavki(day.counts.orders)}`);
  } else {
    parts.push("Отдельных заявок за день не было");
  }
  if (filled > 0 && later) {
    parts.push("Часть из них получила подтверждённое исполнение позднее");
  } else if (filled > 0) {
    parts.push(`Подтверждено исполнений по заявкам: ${filled}`);
  }
  if (cancelled > 0) {
    parts.push(`Отменено заявок: ${cancelled}`);
  }
  const level = (day.evidence_level ?? "").toUpperCase();
  if (level === "PARTIAL" || level === "LIMITED" || (!day.detail_available && day.decision)) {
    parts.push("Подробные причины отбора в этой исторической записи сохранились не полностью");
  }
  return `${parts.join(". ")}.`;
}

function pluralZayavki(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "заявку";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return "заявки";
  return "заявок";
}

export function instrumentResultLabel(order: ShadowJournalOrder): {
  label: string;
  tone: "ok" | "warn" | "muted" | "danger";
} {
  const fills = order.fills ?? [];
  const timing = order.execution_timing;
  if (fills.length > 0) {
    if (timing === "later") return { label: "Исполнено позднее", tone: "ok" };
    return { label: "Исполнено", tone: "ok" };
  }
  if (timing === "status_fill_mismatch") {
    return { label: "Статус без исполнения", tone: "warn" };
  }
  const st = (order.status ?? "").toUpperCase();
  if (st === "CANCELLED" || st === "CANCELED") return { label: "Отменено", tone: "muted" };
  if (st === "REJECTED") return { label: "Отклонено", tone: "danger" };
  if (isJournalOrderPendingStatus(st)) return { label: "Ожидает исполнения", tone: "warn" };
  return { label: journalOrderStatusLabel(order.status), tone: "muted" };
}

export function candidatePlanFields(c: ShadowJournalCandidateTrace): Array<{ label: string; value: string }> {
  const rows: Array<{ label: string; value: string }> = [];
  if (c.target_weight != null && Number.isFinite(c.target_weight)) {
    rows.push({ label: "Целевой вес", value: String(c.target_weight) });
  }
  if (c.current_weight != null && Number.isFinite(c.current_weight)) {
    rows.push({ label: "Текущий вес", value: String(c.current_weight) });
  }
  if (c.quantity_before != null && Number.isFinite(c.quantity_before)) {
    rows.push({ label: "Кол-во до", value: String(c.quantity_before) });
  }
  if (c.rank != null && Number.isFinite(c.rank)) {
    rows.push({ label: "Ранг", value: String(c.rank) });
  }
  if (c.net_edge != null && Number.isFinite(c.net_edge)) {
    rows.push({ label: "Net edge", value: String(c.net_edge) });
  }
  if (c.replacement_ticker) {
    rows.push({ label: "Замена", value: String(c.replacement_ticker).toUpperCase() });
  }
  return rows;
}

export function dayHasWhyEvidence(day: ShadowJournalDay): boolean {
  if (day.candidates.some((c) => (c.reason_codes?.length ?? 0) > 0 || c.decision_action)) {
    return true;
  }
  const facts = day.recorded_facts;
  if (facts?.targets?.length || facts?.order_plan_rows?.length || facts?.order_reasons?.length) {
    return true;
  }
  const d = day.decision;
  return Boolean(d?.policy_name || d?.risk_name || d?.risk_mode || (d?.targets?.length ?? 0) > 0);
}
