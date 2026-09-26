import type { InvestmentDecisionResponse } from "../../api/investment";
import type {
  ManualCompareCandidate,
  ManualPortfolioAnalysis,
  ManualRebalancePlan,
  ManualRebalancePlanRow,
} from "../../api/manualPortfolios";
import { suggestedActionLabel } from "../manualPortfolio/labels";

export type ActionTone = "buy" | "reduce" | "hold" | "cash" | "fi";

export interface KrakenActionCard {
  id: string;
  tone: ActionTone;
  /** Human action badge text */
  actionLabel: string;
  ticker?: string;
  title: string;
  rationale: string;
  /** Short facts from available fields only */
  bullets: string[];
  effect: string;
  currentWeight?: number | null;
  targetWeight?: number | null;
  href: string;
  cta: string;
}

function toneFromAction(action: string): ActionTone {
  const a = action.toUpperCase();
  if (a.includes("BUY") || a.includes("INCREASE")) return "buy";
  if (a.includes("SELL") || a.includes("REDUCE") || a.includes("EXIT")) return "reduce";
  if (a.includes("CASH")) return "cash";
  if (a.includes("OFZ") || a.includes("BOND") || a.includes("FIXED")) return "fi";
  return "hold";
}

function actionLabelFromTone(tone: ActionTone, action?: string): string {
  if (tone === "buy") return "Докупить";
  if (tone === "reduce") return "Сократить";
  if (tone === "cash") return "Кэш";
  if (tone === "fi") return "Облигации";
  if (action) {
    const s = suggestedActionLabel(action);
    if (s !== "—") return s;
  }
  return "Держать";
}

function humanizeReason(reason: string | undefined | null): string {
  if (!reason) return "Совет по ребалансу относительно целевого кандидата.";
  const code = reason.trim().toUpperCase();
  const map: Record<string, string> = {
    REBALANCE_SELL: "Сократить позицию до целевого веса кандидата",
    REBALANCE_BUY: "Докупить до целевого веса кандидата",
    REDUCE: "Уменьшить вес позиции",
    INCREASE: "Увеличить вес позиции",
  };
  if (map[code]) return map[code];
  if (/^[A-Z0-9_]+$/.test(code) && code.length < 40) {
    return suggestedActionLabel(code) !== "—" ? suggestedActionLabel(code) : reason;
  }
  return reason;
}

function pct(w: number | null | undefined): string | null {
  if (w == null || Number.isNaN(w)) return null;
  return `${(w * 100).toFixed(1)}%`;
}

function rebalanceBullets(row: ManualRebalancePlanRow, plan: ManualRebalancePlan): string[] {
  const out: string[] = [];
  const cur = pct(row.current_weight);
  const tgt = pct(row.target_weight);
  if (cur && tgt) out.push(`Вес сейчас ${cur} → цель ${tgt}`);
  else if (tgt) out.push(`Целевой вес ≈ ${tgt}`);
  else if (cur) out.push(`Текущий вес ≈ ${cur}`);

  if (row.lots_delta != null && row.lots_delta !== 0) {
    const sign = row.lots_delta > 0 ? "+" : "";
    out.push(`Лоты: ${sign}${row.lots_delta}`);
  }
  if (row.units_delta != null && row.units_delta !== 0) {
    const sign = row.units_delta > 0 ? "+" : "";
    out.push(`Штуки: ${sign}${row.units_delta}`);
  }
  if (row.estimated_notional != null && row.estimated_notional !== 0) {
    const sign = row.estimated_notional > 0 ? "+" : "";
    out.push(
      `Ориентир суммы: ${sign}${Math.round(row.estimated_notional).toLocaleString("ru-RU")} ₽`,
    );
  }
  if (plan.projected_cash != null && plan.cash != null) {
    out.push(
      `Кэш после плана ≈ ${Math.round(plan.projected_cash).toLocaleString("ru-RU")} ₽ (сейчас ${Math.round(plan.cash).toLocaleString("ru-RU")} ₽)`,
    );
  }
  if (plan.cash_safe === false) {
    out.push("После плана запас кэша может быть недостаточным");
  } else if (plan.cash_safe === true) {
    out.push("Запас ликвидности после плана: достаточный");
  }
  return out.slice(0, 4);
}

export function buildKrakenActions(input: {
  analysis: ManualPortfolioAnalysis | null;
  rebalance: ManualRebalancePlan | null;
  compare: ManualCompareCandidate | null;
  decision: InvestmentDecisionResponse | null;
}): KrakenActionCard[] {
  const cards: KrakenActionCard[] = [];
  const { analysis, rebalance, compare, decision } = input;

  if (rebalance?.plan_rows?.length) {
    for (const row of rebalance.plan_rows.slice(0, 3)) {
      const action = (row.action || "").toUpperCase();
      const tone = toneFromAction(action);
      const bullets = rebalanceBullets(row, rebalance);
      cards.push({
        id: `reb-${row.ticker}-${row.action}`,
        tone,
        actionLabel: actionLabelFromTone(tone, row.action),
        ticker: row.ticker,
        title:
          tone === "buy"
            ? `Докупить ${row.ticker}`
            : tone === "reduce"
              ? `Сократить ${row.ticker}`
              : `${actionLabelFromTone(tone, row.action)} · ${row.ticker}`,
        rationale: humanizeReason(row.reason),
        bullets,
        effect:
          row.target_weight != null
            ? `Целевой вес ≈ ${(row.target_weight * 100).toFixed(0)}%`
            : "Справочный ребаланс, не приказ брокеру",
        currentWeight: row.current_weight,
        targetWeight: row.target_weight,
        href: `/portfolio/mine?tab=rebalance&focus=${encodeURIComponent(row.ticker)}`,
        cta: "Подробнее",
      });
    }
  }

  if (!cards.length && compare?.comparisons?.length) {
    const interesting = compare.comparisons.filter((c) => {
      const s = (c.suggested_action || "").toUpperCase();
      return s && s !== "KEEP" && s !== "NO_VIEW";
    });
    for (const row of interesting.slice(0, 3)) {
      const tone = toneFromAction(row.suggested_action);
      const bullets: string[] = [];
      if (row.manual_weight != null) bullets.push(`Вес в моём портфеле: ${pct(row.manual_weight)}`);
      if (row.candidate_weight != null) bullets.push(`Вес у кандидата Kraken: ${pct(row.candidate_weight)}`);
      if (row.status) bullets.push(`Статус сравнения: ${row.status}`);
      if (row.note) bullets.push(row.note);
      cards.push({
        id: `cmp-${row.symbol}-${row.suggested_action}`,
        tone,
        actionLabel: actionLabelFromTone(tone, row.suggested_action),
        ticker: row.symbol,
        title: `${actionLabelFromTone(tone, row.suggested_action)} · ${row.symbol}`,
        rationale: row.note || "Расхождение между моим портфелем и кандидатом Kraken.",
        bullets: bullets.slice(0, 4),
        effect: "Сравнение с research-кандидатом",
        currentWeight: row.manual_weight,
        targetWeight: row.candidate_weight,
        href: `/portfolio/mine?tab=compare&focus=${encodeURIComponent(row.symbol)}`,
        cta: "Подробнее",
      });
    }
  }

  if (!cards.length && decision?.decision) {
    const d = decision.decision;
    const eq = d.equity_weight ?? 0;
    const fi = d.fixed_income_weight ?? 0;
    const cash = d.cash_weight ?? 0;
    const decisionBullets = [
      `Акции ${(eq * 100).toFixed(0)}%`,
      `Облигации ${(fi * 100).toFixed(0)}%`,
      `Кэш ${(cash * 100).toFixed(0)}%`,
      ...(d.explanations?.slice(1, 2) ?? []),
    ].slice(0, 4);
    cards.push({
      id: "dec-alloc",
      tone: fi >= eq && fi >= cash ? "fi" : eq >= cash ? "buy" : "cash",
      actionLabel: "Распределение",
      title: "Исследовательское распределение",
      rationale:
        d.explanations?.[0] ??
        "Kraken предлагает целевые доли акций / облигаций / кэша для research-кандидата.",
      bullets: decisionBullets,
      effect: `Акции ${(eq * 100).toFixed(0)}% · Облигации ${(fi * 100).toFixed(0)}% · Кэш ${(cash * 100).toFixed(0)}%`,
      href: "/investment-decision",
      cta: "Подробнее",
    });
    if (cash >= 0.2) {
      cards.push({
        id: "dec-cash",
        tone: "cash",
        actionLabel: "Кэш",
        title: "Держать повышенный кэш",
        rationale:
          "В текущем решении заметная доля денег — это сознательный буфер, не «забытые средства».",
        bullets: [
          `Доля кэша ${(cash * 100).toFixed(0)}%`,
          "Справочное решение, не приказ брокеру",
        ],
        effect: `Кэш ${(cash * 100).toFixed(0)}% в research-решении`,
        href: "/portfolio/candidate?capital=100000",
        cta: "Подробнее",
      });
    }
    if (fi >= 0.4) {
      cards.push({
        id: "dec-ofz",
        tone: "fi",
        actionLabel: "Облигации",
        title: "Рассмотреть облигационный рукав",
        rationale: "Решение опирается на фиксированный доход относительно hurdle ЦБ.",
        bullets: [`FI ${(fi * 100).toFixed(0)}% целевого веса`, "Открыть каталог облигаций"],
        effect: `FI ${(fi * 100).toFixed(0)}% целевого веса`,
        href: "/bonds",
        cta: "Подробнее",
      });
    }
  }

  if (!cards.length) {
    if (analysis && analysis.positions.length === 0 && analysis.cash_rub <= 0) {
      cards.push({
        id: "empty-start",
        tone: "hold",
        actionLabel: "Начать",
        title: "Заполнить мой портфель",
        rationale: "Пока нет позиций и кэша — начните с учёта текущего портфеля.",
        bullets: ["Нужны позиции или кэш для персональных советов"],
        effect: "Без данных Kraken не может дать персональный совет",
        href: "/portfolio/mine",
        cta: "Подробнее",
      });
    } else {
      cards.push({
        id: "hold-default",
        tone: "hold",
        actionLabel: "Держать",
        title: "Пока без срочных действий",
        rationale:
          "Нет готового ребаланса или расхождений с кандидатом. Можно проверить риск и решение вручную.",
        bullets: ["Рекомендации появятся после сравнения с кандидатом"],
        effect: "Нет срочных действий",
        href: "/investment-decision",
        cta: "Подробнее",
      });
      cards.push({
        id: "risk-check",
        tone: "hold",
        actionLabel: "Риск",
        title: "Проверить риски портфеля",
        rationale: "Концентрация и связи позиций важнее «красивой» доходности на коротком горизонте.",
        bullets: ["Сводка предупреждений и концентрации"],
        effect: "Сводка рисков",
        href: "/portfolio-risk",
        cta: "Подробнее",
      });
    }
  }

  return cards.slice(0, 4);
}
