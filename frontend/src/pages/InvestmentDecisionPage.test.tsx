import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HelpProvider } from "../help";
import { InvestmentDecisionPage } from "./InvestmentDecisionPage";

vi.mock("../api/investment", () => ({
  getHurdle: vi.fn(async () => ({
    status: "OK",
    annual_rate: 0.18,
    hurdle_1y: 0.18,
    hurdle_20d: 0.01,
  })),
  decideInvestment: vi.fn(async () => ({
    as_of: "2026-09-05",
    capital: "100000",
    cbr_hurdle_annual: 0.18,
    profile_id: "BALANCED_ALLOCATION_V0",
    equity_opportunity: {
      expected_return: null,
      expected_excess_return: 0,
      confidence: null,
      model_source: "test",
      calibration_status: "INSUFFICIENT_SAMPLE",
    },
    fixed_income_opportunity: {
      expected_yield: 0.12,
      duration: 4,
      credit_quality: "UNKNOWN",
      liquidity: "UNKNOWN",
      data_quality: "READY",
      yield_source: "OBSERVED",
      support_status: "SUPPORTED",
    },
    cash_opportunity: {
      annual_rate: 0.18,
      horizon_return: 0.18,
      source: "CBR",
      quality: "DATE_ONLY",
    },
    calibration: {
      sample_size: 0,
      bias: null,
      mae: null,
      hit_rate: null,
      calibration_status: "INSUFFICIENT_SAMPLE",
      uncertainty_note: "Нет зрелых пар",
      buckets: [],
      limitations: [],
    },
    risk_budget: {},
    decision: {
      profile_id: "BALANCED_ALLOCATION_V0",
      equity_weight: 0.25,
      fixed_income_weight: 0.4,
      cash_weight: 0.35,
      weights_pct: { equity: 25, fixed_income: 40, cash: 35 },
      reason_codes: ["equity_confidence_unknown"],
      explanations: ["Тестовое объяснение"],
      warnings: ["Высокая доходность может отражать высокий риск."],
      status: "RESEARCH_ONLY",
      why_equity_ru: "Доля акций ограничена калибровкой.",
      why_fixed_income_ru: "Fixed Income research sleeve.",
      why_cash_ru: "Cash как буфер.",
      limitations: [],
    },
    lots: {
      sleeve_cash_used: { EQUITY_ALPHA: "0", FIXED_INCOME: "0", CASH: "100000" },
      target_weights: { equity: 0.25, fixed_income: 0.4, cash: 0.35 },
      lot_result: { cash_remainder: "100000", fees: "0", positions: [] },
    },
    economic_metrics: {
      return: null,
      excess_vs_cbr: null,
      max_drawdown: null,
      volatility: null,
      turnover: null,
      question_ru: "Оправдал ли результат риск?",
      answer_ru: "Research framing.",
    },
    bond_safety_reminder: "Высокая доходность может отражать высокий риск.",
    mode: "RISK_OPPORTUNITY_ENGINE_V0",
  })),
  compareInvestmentDecisions: vi.fn(async () => ({
    profiles: [],
    static_benchmarks: [],
    cbr_benchmark: { annual_rate: 0.18, note: "CBR" },
    note: "no winner",
  })),
}));

describe("InvestmentDecisionPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders Kraken investment decision header and cards", async () => {
    render(
      <MemoryRouter>
        <HelpProvider>
          <InvestmentDecisionPage />
        </HelpProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Инвестиционное решение Kraken")).toBeInTheDocument();
    expect(await screen.findByText(/исследовательское распределение/i)).toBeInTheDocument();
    expect(screen.getByText("Оправдал ли результат риск?")).toBeInTheDocument();
  });
});
