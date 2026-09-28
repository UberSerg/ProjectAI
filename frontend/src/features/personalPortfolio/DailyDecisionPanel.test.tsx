import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DailyPersonalDecision } from "../../api/dailyPersonalDecision";
import * as api from "../../api/dailyPersonalDecision";
import { DailyDecisionPanel } from "./DailyDecisionPanel";

vi.mock("../../api/dailyPersonalDecision", async () => {
  const actual = await vi.importActual<typeof api>("../../api/dailyPersonalDecision");
  return {
    ...actual,
    getDailyPersonalDecision: vi.fn(),
  };
});

const base: DailyPersonalDecision = {
  engine_version: "2",
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
  scenario_comparison: [],
  limitations: [],
};

describe("DailyDecisionPanel", () => {
  beforeEach(() => {
    vi.mocked(api.getDailyPersonalDecision).mockReset();
  });

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
  });

  it("calculates 30k scenarios and clears on portfolio switch", async () => {
    vi.mocked(api.getDailyPersonalDecision).mockResolvedValue({
      ...base,
      new_cash_rub: "30000",
      new_cash_plan: {
        requested_new_cash_rub: "30000",
        current_nav_rub: "100000",
        current_cash_rub: "20000",
        hypothetical_total_capital_rub: "130000",
      },
      scenario_comparison: [
        {
          id: "DO_NOTHING",
          title: "Не распределять",
          status: "available",
          deployed_rub: "0",
          residual_cash_rub: "30000",
          facts: ["baseline"],
        },
        {
          id: "HOLD_CASH",
          title: "Оставить кэшем",
          status: "available",
          deployed_rub: "0",
          residual_cash_rub: "30000",
        },
        {
          id: "TARGET_UNDERWEIGHTS",
          title: "Направить в недовесы",
          status: "available",
          deployed_rub: "10000",
          residual_cash_rub: "20000",
          purchases: [{ symbol: "SBER", target_rub: "10000", lots: null, limitations: ["LOT_SIZE_UNKNOWN"] }],
        },
        {
          id: "KRAKEN_ALLOCATION",
          title: "Текущий план Kraken",
          status: "unavailable",
          reason: "нет данных",
        },
        {
          id: "FIXED_INCOME_ALTERNATIVE",
          title: "Альтернатива: fixed-income sleeve",
          status: "available",
          purchases: [{ sleeve: "fixed_income", limitations: ["ADVISORY_ONLY_BOND_TRADE"] }],
        },
      ],
      data_confidence: { status: "PARTIAL", reasons: ["candidate_unavailable"] },
      limitations: ["READ_ONLY_HYPOTHETICAL"],
    });

    const { rerender } = render(<DailyDecisionPanel decision={base} portfolioId={1} />);
    fireEvent.change(screen.getByTestId("daily-decision-new-cash-input"), { target: { value: "30000" } });
    fireEvent.click(screen.getByTestId("daily-decision-calculate"));
    await waitFor(() => expect(screen.getByTestId("daily-decision-scenarios")).toBeInTheDocument());
    expect(screen.getByTestId("decision-scenario-DO_NOTHING")).toBeInTheDocument();
    expect(screen.getByTestId("decision-scenario-TARGET_UNDERWEIGHTS")).toBeInTheDocument();
    expect(screen.getByText(/лот неизвестен/)).toBeInTheDocument();
    expect(screen.getByText(/advisory FI/)).toBeInTheDocument();

    rerender(<DailyDecisionPanel decision={base} portfolioId={2} />);
    expect(screen.getByTestId("daily-decision-new-cash-input")).toHaveValue("");
  });
});
