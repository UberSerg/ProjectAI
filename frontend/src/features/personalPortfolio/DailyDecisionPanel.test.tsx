import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DailyPersonalDecision } from "../../api/dailyPersonalDecision";
import { DailyDecisionPanel } from "./DailyDecisionPanel";

const base: DailyPersonalDecision = {
  as_of: "2026-09-27",
  status: "NO_ACTION",
  headline: "Срочных действий нет",
  summary: "Портфель близок к кандидату.",
  portfolio: {
    id: 1,
    journal_state: "ACTIVE",
    cash_rub: "20000",
    securities_value_rub: "80000",
    nav_rub: "100000",
    contributed_rub: "100000",
    withdrawn_rub: "0",
    investment_pnl_rub: "0",
    symbols: ["SBER"],
  },
  actions: [
    {
      id: "HOLD:portfolio:ALIGNED",
      priority: "LOW",
      action: "HOLD",
      title: "Срочных действий нет",
      rationale: "Портфель близок к кандидату.",
      reason_codes: ["ALIGNED_WITH_CANDIDATE"],
      facts: ["NAV ≈ 100000 ₽"],
      href: "/portfolio/mine?tab=decision",
      limitations: [],
    },
  ],
  risks: [],
  data_quality: {
    valuation_complete: true,
    valuation_partial: false,
    valuation_as_of: "2026-09-25",
    valuation_from: "2026-09-25",
    valuation_to: "2026-09-25",
    valuation_label: "Оценка по ценам на 25.09.2026",
    missing_price_count: 0,
    degradations: [],
  },
  context: { candidate_source: "preview", what_can_change_decision: ["новая котировка"] },
  disclaimer: "Модельная рекомендация",
};

describe("DailyDecisionPanel", () => {
  it("renders NO_ACTION state", () => {
    render(<DailyDecisionPanel decision={base} />);
    expect(screen.getByTestId("daily-decision-panel")).toBeInTheDocument();
    expect(screen.getByTestId("daily-decision-headline")).toHaveTextContent("Срочных действий нет");
    expect(screen.getByTestId("daily-action-HOLD")).toBeInTheDocument();
  });

  it("renders PARTIAL warning", () => {
    render(
      <DailyDecisionPanel
        decision={{
          ...base,
          status: "PARTIAL",
          headline: "Сначала проверьте данные",
          data_quality: { ...base.data_quality, valuation_partial: true, valuation_complete: false },
          actions: [
            {
              id: "DATA_QUALITY:portfolio:VALUATION_PARTIAL",
              priority: "HIGH",
              action: "DATA_QUALITY",
              title: "Нужны данные",
              rationale: "Частичная оценка",
              reason_codes: ["VALUATION_PARTIAL"],
              facts: ["Без цены: X"],
              limitations: [],
            },
          ],
        }}
      />,
    );
    expect(screen.getByTestId("daily-decision-partial")).toBeInTheDocument();
    expect(screen.getByTestId("daily-action-DATA_QUALITY")).toBeInTheDocument();
  });

  it("OWNER sees reason codes", () => {
    render(<DailyDecisionPanel decision={base} owner />);
    expect(screen.getByTestId("daily-action-codes")).toHaveTextContent("ALIGNED_WITH_CANDIDATE");
  });
});
