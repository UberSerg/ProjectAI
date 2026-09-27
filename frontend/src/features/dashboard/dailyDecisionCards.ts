import type { DailyDecisionAction, DailyPersonalDecision } from "../../api/dailyPersonalDecision";
import type { ActionTone, KrakenActionCard } from "./recommendations";

/** Presentation adapter: backend Daily Decision → existing ActionCards UI. */
export function dailyDecisionToActionCards(decision: DailyPersonalDecision | null): KrakenActionCard[] {
  if (!decision?.actions?.length) return [];
  return decision.actions.slice(0, 5).map((a) => toCard(a));
}

function toneFromAction(action: string): ActionTone {
  const a = action.toUpperCase();
  if (a.includes("INCREASE") || a === "SETUP") return "buy";
  if (a.includes("REDUCE")) return "reduce";
  if (a.includes("CASH") || a === "KEEP_CASH") return "cash";
  if (a.includes("DATA") || a === "ACTIVATE_JOURNAL" || a === "REVIEW") return "hold";
  return "hold";
}

function badge(action: string): string {
  switch (action) {
    case "SETUP":
      return "Начать учёт";
    case "ACTIVATE_JOURNAL":
      return "Начать учёт";
    case "DATA_QUALITY":
      return "Нужны данные";
    case "REVIEW":
      return "Обратить внимание";
    case "CONSIDER_INCREASE":
      return "Рассмотреть увеличение";
    case "CONSIDER_REDUCE":
      return "Рассмотреть сокращение";
    case "KEEP_CASH":
      return "Сохранить кэш";
    case "HOLD":
      return "Держать";
    default:
      return "Обратить внимание";
  }
}

function toCard(a: DailyDecisionAction): KrakenActionCard {
  const tone = toneFromAction(a.action);
  return {
    id: a.id,
    tone,
    actionLabel: badge(a.action),
    ticker: a.symbol ?? undefined,
    title: a.title,
    rationale: a.rationale,
    bullets: a.facts.slice(0, 3),
    effect: a.priority === "HIGH" ? "Важно сейчас" : a.priority === "MEDIUM" ? "Стоит рассмотреть" : "Для сведения",
    currentWeight: a.current_weight,
    targetWeight: a.target_weight,
    href: a.href || "/portfolio/mine?tab=decision",
    cta: "Подробнее",
  };
}
