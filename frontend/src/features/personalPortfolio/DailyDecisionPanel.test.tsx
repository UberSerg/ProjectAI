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
  engine_version: "PERSONAL_DAILY_DECISION_V2",
  decision_fingerprint: "fp-base-aaaa",
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
  risks: [{ code: "CONCENTRATION", message: "Высокая концентрация в одном эмитенте" }],
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

const scenarios100k: DailyPersonalDecision["scenario_comparison"] = [
  {
    id: "DO_NOTHING",
    title: "Ничего не делать",
    status: "available",
    deployed_rub: "0",
    residual_cash_rub: "0",
    external_unallocated_rub: "100000",
    facts: ["baseline"],
  },
  {
    id: "HOLD_CASH",
    title: "Держать кэш",
    status: "available",
    deployed_rub: "0",
    residual_cash_rub: "100000",
  },
  {
    id: "TARGET_UNDERWEIGHTS",
    title: "Докупить недовесы",
    status: "available",
    deployed_rub: "40000",
    executable_notional_rub: "40000",
    residual_cash_rub: "60000",
    purchases: [{ symbol: "SBER", target_rub: "40000", lots: 2, limitations: [] }],
  },
  {
    id: "KRAKEN_ALLOCATION",
    title: "План Kraken",
    status: "unavailable",
    reason: "CANDIDATE_OR_VALUATION_UNAVAILABLE",
  },
  {
    id: "FIXED_INCOME_ALTERNATIVE",
    title: "Альтернатива: fixed-income",
    status: "advisory",
    target_allocation_rub: "100000",
    executable_notional_rub: "0",
    advisory_only_rub: "100000",
    residual_cash_rub: "0",
    purchases: [
      {
        sleeve: "fixed_income",
        target_rub: "100000",
        limitations: ["ADVISORY_ONLY_BOND_TRADE"],
        execution_status: "ADVISORY_ONLY",
      },
    ],
  },
];

describe("DailyDecisionPanel", () => {
  beforeEach(() => {
    vi.mocked(api.getDailyPersonalDecision).mockReset();
  });

  it("renders NO_ACTION summary with NAV and cash", () => {
    render(<DailyDecisionPanel decision={base} />);
    expect(screen.getByTestId("daily-decision-panel")).toBeInTheDocument();
    expect(screen.getByTestId("daily-decision-summary")).toBeInTheDocument();
    expect(screen.getByTestId("daily-decision-headline")).toHaveTextContent("Срочных действий нет");
    expect(screen.getByTestId("daily-action-HOLD")).toBeInTheDocument();
    expect(screen.getAllByText(/100[\s\u00a0]?000/).length).toBeGreaterThan(0);
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

  it("calculates 100000 scenarios with Russian explanations and clears on portfolio switch", async () => {
    const onDecisionChange = vi.fn();
    vi.mocked(api.getDailyPersonalDecision).mockResolvedValue({
      ...base,
      decision_fingerprint: "fp-100k-bbbb",
      new_cash_rub: "100000",
      new_cash_plan: {
        requested_new_cash_rub: "100000",
        current_nav_rub: "100000",
        current_cash_rub: "20000",
        hypothetical_total_capital_rub: "200000",
      },
      scenario_comparison: scenarios100k,
      data_confidence: { status: "PARTIAL", reasons: ["candidate_unavailable"] },
      limitations: ["READ_ONLY_HYPOTHETICAL"],
    });

    const { rerender } = render(
      <DailyDecisionPanel decision={base} portfolioId={1} onDecisionChange={onDecisionChange} />,
    );
    fireEvent.click(screen.getByTestId("daily-decision-preset-100k"));
    await waitFor(() => expect(screen.getByTestId("daily-decision-scenarios")).toBeInTheDocument());

    expect(api.getDailyPersonalDecision).toHaveBeenCalledWith(1, {
      newCashRub: 100000,
    });
    expect(screen.getByTestId("decision-scenario-DO_NOTHING")).toBeInTheDocument();
    expect(screen.getByTestId("decision-scenario-HOLD_CASH")).toBeInTheDocument();
    expect(screen.getByTestId("decision-scenario-TARGET_UNDERWEIGHTS")).toBeInTheDocument();
    expect(screen.getByTestId("decision-scenario-KRAKEN_ALLOCATION")).toBeInTheDocument();
    expect(screen.getByTestId("decision-scenario-FIXED_INCOME_ALTERNATIVE")).toBeInTheDocument();
    expect(screen.getByTestId("decision-scenario-explain-DO_NOTHING")).toHaveTextContent(/вне учёта/i);
    expect(screen.getByTestId("decision-scenario-blocked-KRAKEN_ALLOCATION")).toHaveTextContent(
      /Нет надёжного сравнения/,
    );
    expect(screen.getAllByText(/только ориентир/i).length).toBeGreaterThan(0);
    expect(screen.getByTestId("daily-decision-risks")).toBeInTheDocument();
    expect(onDecisionChange).toHaveBeenCalledWith(
      expect.objectContaining({ decision_fingerprint: "fp-100k-bbbb", new_cash_rub: "100000" }),
    );

    rerender(
      <DailyDecisionPanel decision={base} portfolioId={2} onDecisionChange={onDecisionChange} />,
    );
    expect(screen.getByTestId("daily-decision-new-cash-input")).toHaveValue("");
  });

  it("invalidates fingerprint when capital input changes after calculation", async () => {
    const onDecisionChange = vi.fn();
    vi.mocked(api.getDailyPersonalDecision).mockResolvedValue({
      ...base,
      decision_fingerprint: "fp-calc",
      new_cash_rub: "100000",
      new_cash_plan: {
        requested_new_cash_rub: "100000",
        current_nav_rub: "100000",
        current_cash_rub: "20000",
        hypothetical_total_capital_rub: "200000",
      },
      scenario_comparison: scenarios100k,
    });

    render(<DailyDecisionPanel decision={base} portfolioId={1} onDecisionChange={onDecisionChange} />);
    fireEvent.click(screen.getByTestId("daily-decision-preset-100k"));
    await waitFor(() =>
      expect(onDecisionChange).toHaveBeenCalledWith(
        expect.objectContaining({ decision_fingerprint: "fp-calc" }),
      ),
    );

    fireEvent.change(screen.getByTestId("daily-decision-new-cash-input"), {
      target: { value: "50000" },
    });
    expect(onDecisionChange).toHaveBeenCalledWith(
      expect.objectContaining({ decision_fingerprint: undefined }),
    );
  });

  it("keeps technical details collapsed until requested", () => {
    render(<DailyDecisionPanel decision={base} />);
    expect(screen.queryByTestId("daily-decision-details-body")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("daily-decision-toggle-details"));
    expect(screen.getByTestId("daily-decision-details-body")).toHaveTextContent(/fingerprint/i);
  });

  it("shows loading error from failed calculate", async () => {
    vi.mocked(api.getDailyPersonalDecision).mockRejectedValue(new Error("backend down"));
    render(<DailyDecisionPanel decision={base} portfolioId={1} />);
    fireEvent.change(screen.getByTestId("daily-decision-new-cash-input"), {
      target: { value: "100000" },
    });
    fireEvent.click(screen.getByTestId("daily-decision-calculate"));
    expect(await screen.findByTestId("daily-decision-local-error")).toHaveTextContent("backend down");
  });
});
