/**
 * Versioned decision explanation registry.
 * Policy semantics live here — not scattered in React components.
 */

import {
  computeCutoff,
  formatPp,
  formatQuantilePercent,
  formatRank,
  formatRuDate,
  formatSignedPercent,
  formatWeightPercent,
  instrumentLabel,
  instrumentShort,
} from "./format";
import { humanPolicyOrCode } from "./labels";
import type { DecisionExplanationContext } from "./types";

export interface ReasonDefinition {
  code: string;
  shortTitle: string;
  summary: (ctx: DecisionExplanationContext) => string;
  detailed: (ctx: DecisionExplanationContext) => string;
}

function joinSentences(parts: Array<string | null | undefined>): string {
  return parts
    .map((p) => (p ?? "").trim())
    .filter(Boolean)
    .join(" ");
}

function predictionClause(ctx: DecisionExplanationContext): string | null {
  const semantic = (ctx.predictionSemantic ?? "").toUpperCase();
  if (semantic === "RANKING_SCORE") {
    const when = formatRuDate(ctx.predictionDate);
    const score =
      ctx.predictionScore != null && Number.isFinite(ctx.predictionScore)
        ? new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 }).format(ctx.predictionScore)
        : null;
    const rankPart = rankClause(ctx, instrumentShort(ctx.ticker, ctx.displayName));
    if (rankPart && when) {
      return `На ${when} ${rankPart.toLowerCase()} по рейтинговому баллу модели`;
    }
    if (rankPart) return rankPart;
    if (score) {
      return when
        ? `На ${when} рейтинговый балл модели: ${score}`
        : `Рейтинговый балл модели: ${score}`;
    }
    return null;
  }
  const pred = formatSignedPercent(ctx.predictedReturn20d);
  const when = formatRuDate(ctx.predictionDate);
  if (!pred) return null;
  if (when) {
    return `На ${when} модель ожидала изменение цены ${pred} за 20 торговых дней`;
  }
  return `Прогноз модели: ${pred} за 20 торговых дней`;
}

function rankClause(ctx: DecisionExplanationContext, ticker: string): string | null {
  if (ctx.rank == null) return null;
  if (ctx.eligibleCount != null) {
    return `${ticker} занимал ${formatRank(ctx.rank, ctx.eligibleCount)} среди доступных инструментов`;
  }
  return `${ticker} занимал ${formatRank(ctx.rank)} в рейтинге`;
}

function targetClause(ctx: DecisionExplanationContext): string | null {
  const w = formatWeightPercent(ctx.targetWeight);
  return w ? `Целевая доля позиции — ${w}.` : null;
}

function entryZoneLabel(ctx: DecisionExplanationContext): string {
  const q = formatQuantilePercent(ctx.entryQuantile ?? 0.2);
  return q ? `верхние ${q}` : "верхние 20%";
}

function exitZoneLabel(ctx: DecisionExplanationContext): string {
  const q = formatQuantilePercent(ctx.exitQuantile ?? 0.35);
  return q ? `Top ${q}` : "Top 35%";
}

function executionDetailed(ctx: DecisionExplanationContext): string | null {
  const status = (ctx.orderStatus ?? "").toUpperCase();
  if (status === "PENDING") {
    const minExec = formatRuDate(ctx.minExecutionDate);
    return joinSentences([
      "Ордер ожидает первого допустимого будущего открытия рынка.",
      minExec ? `Исполнение возможно не раньше ${minExec}.` : null,
    ]);
  }
  if (!ctx.executionDate) return null;
  const decision = formatRuDate(ctx.decisionDate ?? ctx.predictionDate);
  const exec = formatRuDate(ctx.executionDate);
  if (!exec) return null;
  if ((ctx.executionRule ?? "NEXT_OPEN").toUpperCase().includes("NEXT") || !ctx.executionRule) {
    return joinSentences([
      decision ? `Решение было сформировано ${decision}.` : null,
      `Согласно правилу Next Open сделка была исполнена на следующем доступном открытии рынка — ${exec}.`,
    ]);
  }
  return `Сделка исполнена ${exec}.`;
}

function pendingSummarySuffix(ctx: DecisionExplanationContext): string | null {
  const status = (ctx.orderStatus ?? "").toUpperCase();
  if (status !== "PENDING") return null;
  return "Ордер пока не исполнен: система ожидает первое допустимое будущее открытие рынка.";
}

function sideAwareOpenVerb(ctx: DecisionExplanationContext): string {
  const side = (ctx.side ?? "").toUpperCase();
  const kind = ctx.actionKind ?? (side === "SELL" ? "SELL" : side === "BUY" ? "BUY" : "UNKNOWN");
  if (kind === "SELL") return "выбран для продажи";
  if ((ctx.orderStatus ?? "").toUpperCase() === "PENDING") return "выбран для покупки";
  if (kind === "BUY" && (ctx.currentWeight == null || ctx.currentWeight <= 1e-12)) {
    return "вошёл в портфель";
  }
  if (kind === "BUY") return "доля позиции увеличена";
  return "обработан политикой";
}

const ENTER_TOP20: ReasonDefinition = {
  code: "ENTER_TOP20",
  shortTitle: "Вход в зону покупок",
  summary: (ctx) => {
    const name = instrumentShort(ctx.ticker, ctx.displayName);
    const ticker = ctx.ticker ?? name;
    const pred = formatSignedPercent(ctx.predictedReturn20d);
    const rank = formatRank(ctx.rank, ctx.eligibleCount);
    const weight = formatWeightPercent(ctx.targetWeight);
    const pending = (ctx.orderStatus ?? "").toUpperCase() === "PENDING";
    const head = pending
      ? `${ticker} выбран для покупки`
      : `${name} вошёл в ${entryZoneLabel(ctx)} рейтинга модели`;
    const mid = joinSentences([
      rank && pred ? `${rank}, прогноз ${pred} на 20 торговых дней.` : null,
      rank && !pred ? `${rank} в рейтинге модели.` : null,
      !rank && pred ? `прогноз ${pred} на 20 торговых дней.` : null,
      weight ? `Стратегия назначила позиции вес ${weight}.` : null,
      pendingSummarySuffix(ctx),
    ]);
    return joinSentences([`${head}.`, mid]);
  },
  detailed: (ctx) => {
    const label = instrumentLabel(ctx.ticker, ctx.displayName);
    const ticker = ctx.ticker ?? label;
    const when = formatRuDate(ctx.predictionDate);
    const entryQ = formatQuantilePercent(ctx.entryQuantile ?? 0.2);
    const entryCut =
      ctx.entryCutoff ?? computeCutoff(ctx.eligibleCount, ctx.entryQuantile ?? 0.2);
    return joinSentences([
      when
        ? `На дату решения ${when} ${rankClause(ctx, ticker) ?? `${ticker} был в рейтинге модели`}.`
        : `${rankClause(ctx, ticker) ?? `${ticker} был в рейтинге модели`}.`,
      `Политика ${humanPolicyOrCode(ctx.policyName)} открывает новые позиции, когда инструмент входит в верхние ${entryQ ?? "20%"} рейтинга.`,
      entryCut != null
        ? `Граница входа: примерно ${entryCut}-е место и выше.`
        : null,
      `${label} находился внутри зоны входа, поэтому для него была сформирована позиция${formatWeightPercent(ctx.targetWeight) ? ` с целевым весом ${formatWeightPercent(ctx.targetWeight)}` : ""}.`,
      (ctx.predictionSemantic ?? "").toUpperCase() === "RANKING_SCORE"
        ? "Рейтинговый балл используется для порядка, а не как процент доходности. Решение о позиции принимает политика, а не модель."
        : "Прогноз модели — оценка ожидаемого изменения цены, а не гарантия результата. Решение о позиции принимает политика, а не модель.",
      executionDetailed(ctx),
    ]);
  },
};

const RANK_LONG_ONLY_V0: ReasonDefinition = {
  code: "RANK_LONG_ONLY_V0",
  shortTitle: "Вход по рейтингу V0",
  summary: (ctx) => {
    const name = instrumentShort(ctx.ticker, ctx.displayName);
    const pred = formatSignedPercent(ctx.predictedReturn20d);
    const when = formatRuDate(ctx.predictionDate);
    const rank = formatRank(ctx.rank, ctx.eligibleCount);
    const weight = formatWeightPercent(ctx.targetWeight);
    return joinSentences([
      `${name} вошёл в верхний квантиль рейтинга модели.`,
      when && pred
        ? `На ${when} модель ожидала изменение цены ${pred} за 20 торговых дней${rank ? `; ${ctx.ticker ?? name} занимал ${rank}` : ""}.`
        : null,
      weight ? `Целевая доля позиции — ${weight}.` : null,
    ]);
  },
  detailed: (ctx) => {
    const label = instrumentLabel(ctx.ticker, ctx.displayName);
    return joinSentences([
      `Политика ${humanPolicyOrCode("RANK_LONG_ONLY_V0")} формирует равновзвешенный long-only портфель из верхнего квантиля прогнозов.`,
      rankClause(ctx, ctx.ticker ?? label),
      predictionClause(ctx) ? `${predictionClause(ctx)}.` : null,
      targetClause(ctx),
      "Модель даёт прогноз и ранг; политика задаёт целевые веса. Это не рекомендация и не обещание доходности.",
      executionDetailed(ctx),
    ]);
  },
};

const HOLD_WITHIN_EXIT_BAND: ReasonDefinition = {
  code: "HOLD_WITHIN_EXIT_BAND",
  shortTitle: "Удержание в зоне hysteresis",
  summary: (ctx) => {
    const ticker = ctx.ticker ?? instrumentShort(ctx.ticker, ctx.displayName);
    const rank = formatRank(ctx.rank, ctx.eligibleCount);
    return joinSentences([
      "Позиция сохранена.",
      `${ticker} уже вне зоны новых покупок, но ещё внутри зоны удержания${rank ? ` (${rank})` : ""}.`,
      "Hysteresis поэтому не продаёт, чтобы снизить лишнюю ротацию.",
    ]);
  },
  detailed: (ctx) => {
    const ticker = ctx.ticker ?? "Инструмент";
    const entryQ = formatQuantilePercent(ctx.entryQuantile ?? 0.2);
    const entryCut =
      ctx.entryCutoff ?? computeCutoff(ctx.eligibleCount, ctx.entryQuantile ?? 0.2);
    const exitCut = ctx.exitCutoff ?? computeCutoff(ctx.eligibleCount, ctx.exitQuantile ?? 0.35);
    return joinSentences([
      "Позиция сохранена.",
      `Инструмент уже вышел из зоны новых покупок ${entryQ ? `Top ${entryQ}` : "Top 20%"}, но всё ещё находится внутри зоны удержания ${exitZoneLabel(ctx)}.`,
      ctx.rank != null
        ? `Текущий ранг: ${formatRank(ctx.rank, ctx.eligibleCount)}.`
        : null,
      entryCut != null && exitCut != null
        ? `Граница входа ≈ ${entryCut}, граница удержания ≈ ${exitCut}.`
        : null,
      `${humanPolicyOrCode(ctx.policyName)} поэтому не продаёт ${ticker}, чтобы избежать лишней ротации портфеля.`,
      "Это правило политики (hysteresis), а не отдельный прогноз модели о «качестве» компании.",
    ]);
  },
};

const EXIT_BELOW_TOP35: ReasonDefinition = {
  code: "EXIT_BELOW_TOP35",
  shortTitle: "Выход ниже зоны удержания",
  summary: (ctx) => {
    const ticker = ctx.ticker ?? instrumentShort(ctx.ticker, ctx.displayName);
    const rank = formatRank(ctx.rank, ctx.eligibleCount);
    return joinSentences([
      `Позиция по ${ticker} закрыта: инструмент опустился ниже зоны удержания стратегии.`,
      rank ? `Ранг: ${rank}.` : null,
    ]);
  },
  detailed: (ctx) => {
    const exitCut = ctx.exitCutoff ?? computeCutoff(ctx.eligibleCount, ctx.exitQuantile ?? 0.35);
    return joinSentences([
      "Позиция закрыта, потому что инструмент опустился ниже зоны удержания стратегии.",
      ctx.rank != null ? `Текущий ранг: ${formatRank(ctx.rank, ctx.eligibleCount)}.` : null,
      exitCut != null
        ? `Граница удержания: примерно ${exitCut}-е место (${exitZoneLabel(ctx)}).`
        : `Граница удержания: ${exitZoneLabel(ctx)}.`,
      "Это относительный рейтинг на дату решения, а не оценка «плохая компания».",
      executionDetailed(ctx),
    ]);
  },
};

const REBALANCE_WEIGHT_DELTA: ReasonDefinition = {
  code: "REBALANCE_WEIGHT_DELTA",
  shortTitle: "Коррекция веса",
  summary: (ctx) => {
    const delta =
      ctx.currentWeight != null && ctx.targetWeight != null
        ? formatPp(ctx.targetWeight - ctx.currentWeight)
        : null;
    return joinSentences([
      "Доля позиции скорректирована при ребалансировке.",
      delta ? `Изменение целевого веса: ${delta}.` : null,
    ]);
  },
  detailed: (ctx) => {
    const cur = formatWeightPercent(ctx.currentWeight);
    const tgt = formatWeightPercent(ctx.targetWeight);
    const delta =
      ctx.currentWeight != null && ctx.targetWeight != null
        ? formatPp(ctx.targetWeight - ctx.currentWeight)
        : null;
    const thr = formatPp(ctx.minTradeWeightDelta ?? 0.02);
    return joinSentences([
      "Доля позиции скорректирована при ребалансировке.",
      "Текущий вес отличался от целевого достаточно сильно, чтобы превысить минимальный порог сделки.",
      cur ? `Текущий вес: ${cur}.` : null,
      tgt ? `Целевой: ${tgt}.` : null,
      delta ? `Изменение: ${delta}.` : null,
      thr ? `Порог: ${thr}.` : null,
      executionDetailed(ctx),
    ]);
  },
};

const BELOW_MIN_WEIGHT_DELTA: ReasonDefinition = {
  code: "BELOW_MIN_WEIGHT_DELTA",
  shortTitle: "Сделка не потребовалась",
  summary: () =>
    "Сделка не выполнялась: разница весов была меньше минимального порога ребалансировки.",
  detailed: (ctx) => {
    const thr = formatPp(ctx.minTradeWeightDelta ?? 0.02);
    const cur = formatWeightPercent(ctx.currentWeight);
    const tgt = formatWeightPercent(ctx.targetWeight);
    return joinSentences([
      "Сделка не выполнялась.",
      `Разница между текущей и целевой долей была меньше минимального порога${thr ? ` ${thr}` : ""}, поэтому стратегия сохранила позицию без лишней ребалансировки.`,
      cur ? `Текущий вес: ${cur}.` : null,
      tgt ? `Целевой вес: ${tgt}.` : null,
    ]);
  },
};

const DD_GUARD_REDUCE: ReasonDefinition = {
  code: "DD_GUARD_REDUCE",
  shortTitle: "Снижение риска",
  summary: (ctx) => {
    const dd = formatSignedPercent(ctx.drawdown, 1);
    return joinSentences([
      "Риск портфеля был снижен.",
      dd ? `Просадка достигла ${dd}.` : null,
    ]);
  },
  detailed: (ctx) => {
    const dd = formatSignedPercent(ctx.drawdown, 1);
    const prev = formatWeightPercent(ctx.previousExposureCap, 0);
    const next = formatWeightPercent(ctx.newExposureCap, 0);
    return joinSentences([
      "Риск портфеля был снижен.",
      dd
        ? `Просадка от предыдущего максимума достигла ${dd}, что превысило порог Risk Guard −20%.`
        : "Просадка превысила порог Risk Guard −20%.",
      prev && next
        ? `Допустимая рыночная экспозиция была снижена с ${prev} до ${next}.`
        : next
          ? `Допустимая рыночная экспозиция снижена до ${next}.`
          : null,
      "Это правило риска по собственной NAV-истории портфеля, а не новый прогноз модели.",
    ]);
  },
};

const DD_GUARD_RECOVER: ReasonDefinition = {
  code: "DD_GUARD_RECOVER",
  shortTitle: "Восстановление экспозиции",
  summary: (ctx) => {
    const dd = formatSignedPercent(ctx.drawdown, 1);
    return joinSentences([
      "Risk Guard разрешил восстановить полную экспозицию.",
      dd ? `Просадка восстановилась до ${dd}.` : null,
    ]);
  },
  detailed: (ctx) => {
    const dd = formatSignedPercent(ctx.drawdown, 1);
    const prev = formatWeightPercent(ctx.previousExposureCap, 0);
    const next = formatWeightPercent(ctx.newExposureCap, 0);
    return joinSentences([
      "Risk Guard разрешил восстановить полную экспозицию.",
      dd
        ? `Просадка восстановилась до ${dd}, то есть выше порога восстановления −10%.`
        : "Просадка поднялась выше порога восстановления −10%.",
      prev && next
        ? `Лимит экспозиции был увеличен с ${prev} до ${next}.`
        : next
          ? `Лимит экспозиции увеличен до ${next}.`
          : null,
    ]);
  },
};

const EXIT_MISSING_MARK: ReasonDefinition = {
  code: "exit_missing_mark",
  shortTitle: "Выход без котировки",
  summary: (ctx) =>
    joinSentences([
      `Позиция по ${ctx.ticker ?? "инструменту"} закрыта из‑за отсутствия рыночной отметки на дату решения.`,
    ]),
  detailed: (ctx) =>
    joinSentences([
      "Политика потребовала выход, но на дату решения не было надёжной mark-цены.",
      "Ордер сформирован с кодом exit_missing_mark — это техническое ограничение данных, а не отдельный прогноз.",
      executionDetailed(ctx),
    ]),
};

export const DECISION_EXPLANATION_REGISTRY: Record<string, ReasonDefinition> = {
  ENTER_TOP20,
  HOLD_WITHIN_EXIT_BAND,
  EXIT_BELOW_TOP35,
  REBALANCE_WEIGHT_DELTA,
  BELOW_MIN_WEIGHT_DELTA,
  DD_GUARD_REDUCE,
  DD_GUARD_RECOVER,
  RANK_LONG_ONLY_V0,
  exit_missing_mark: EXIT_MISSING_MARK,
};

export const FALLBACK_REASON: ReasonDefinition = {
  code: "UNKNOWN",
  shortTitle: "Решение политики",
  summary: () =>
    "Действие сформировано портфельной политикой на основании сохранённого прогноза и текущего состояния портфеля.",
  detailed: (ctx) =>
    joinSentences([
      "Действие сформировано портфельной политикой на основании сохранённого прогноза и текущего состояния портфеля.",
      predictionClause(ctx) ? `${predictionClause(ctx)}.` : null,
      rankClause(ctx, ctx.ticker ?? "Инструмент"),
      targetClause(ctx),
      ctx.reasonCode ? `Технический код причины: ${ctx.reasonCode}.` : null,
      executionDetailed(ctx),
      sideAwareOpenVerb(ctx) ? null : null,
    ]),
};

/** Strip suffixes like `|cash_scaled` for registry lookup. */
export function normalizeReasonCode(raw?: string | null): string {
  if (!raw) return "UNKNOWN";
  const base = raw.split("|")[0]?.trim() || "UNKNOWN";
  return base;
}

export function getReasonDefinition(raw?: string | null): {
  definition: ReasonDefinition;
  usedFallback: boolean;
  normalized: string;
} {
  const normalized = normalizeReasonCode(raw);
  const definition = DECISION_EXPLANATION_REGISTRY[normalized];
  if (definition) return { definition, usedFallback: false, normalized };
  return { definition: FALLBACK_REASON, usedFallback: true, normalized };
}

export const SUPPORTED_REASON_CODES = Object.keys(DECISION_EXPLANATION_REGISTRY);
