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
  REVIEW_HOLD: "Ревизия: удержать",
  REVIEW: "Ревизия",
  ROTATE: "Ротация",
  DATA_HOLD: "Удержание (данные)",
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
};

export function journalDecisionActionLabel(action?: string | null): string {
  const key = (action ?? "").trim().toUpperCase();
  if (!key) return "—";
  if (JOURNAL_ACTION_LABELS[key]) return JOURNAL_ACTION_LABELS[key];
  if (key.startsWith("REVIEW")) return "Ревизия";
  if (key.startsWith("ROTATE_TO_")) {
    return `Ротация → ${key.slice("ROTATE_TO_".length)}`;
  }
  return key;
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

  if (action === "REVIEW_HOLD" || action.startsWith("REVIEW")) {
    const why = reasons || "структурные причины не сохранены";
    const alt = replacement ? ` Кандидат на замену: ${replacement}.` : "";
    return `Ревизия: позиция удержана — ${why}.${alt}${edge}`.trim();
  }
  if (action === "ROTATE" || action.startsWith("ROTATE")) {
    const target = replacement ? ` на ${replacement}` : "";
    const why = reasons || "чистый edge после издержек";
    return `Ротация${target}: ${why}.`;
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
  pending: boolean;
};

/**
 * Build Decision → Order → Fill links by real IDs. Pending orders have no fills.
 * Fills without a matching day order are listed with order=null but real order_id.
 */
export function buildDecisionOrderFillChains(day: ShadowJournalDay): DecisionChainLink[] {
  const fillsByOrder = new Map<number, ShadowJournalFill[]>();
  for (const f of day.fills) {
    const list = fillsByOrder.get(f.order_id) ?? [];
    list.push(f);
    fillsByOrder.set(f.order_id, list);
  }

  const links: DecisionChainLink[] = [];
  const seenOrders = new Set<number>();

  for (const order of day.orders) {
    seenOrders.add(order.id);
    const fills = fillsByOrder.get(order.id) ?? [];
    links.push({
      decisionId: order.decision_id ?? null,
      order,
      fills,
      pending: fills.length === 0,
    });
  }

  for (const [orderId, fills] of fillsByOrder) {
    if (seenOrders.has(orderId)) continue;
    links.push({
      decisionId: fills[0]?.decision_at ? null : null,
      order: null,
      fills,
      pending: false,
    });
  }

  return links;
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
  if (!day.detail_available) return false;
  if (day.candidates.some((c) => (c.reason_codes?.length ?? 0) > 0 || c.decision_action)) {
    return true;
  }
  const d = day.decision;
  return Boolean(d?.policy_name || d?.risk_name || d?.risk_mode);
}
