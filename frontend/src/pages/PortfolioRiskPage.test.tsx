import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HelpProvider } from "../help";
import { PortfolioRiskPage } from "./PortfolioRiskPage";

vi.mock("../api/investment", () => ({
  assessPortfolioRisk: vi.fn(async () => ({
    capital: "100000",
    policy_id: "CBR_HURDLE_GATE_V0",
    profile_id: "BALANCED_ALLOCATION_V0",
    pipeline: "Opportunity → Risk Checks → Eligibility → Portfolio Candidate",
    allocation: {
      equity_weight: 0.25,
      fixed_income_weight: 0.65,
      cash_weight: 0.1,
      status: "RESEARCH_ONLY",
      explanation_ru: "test",
    },
    risk_assessment: {
      status: "RESEARCH_ONLY",
      capital: "100000",
      positions: [
        {
          symbol: "CORP",
          sleeve: "FIXED_INCOME",
          status: "RESEARCH_ONLY",
          reason_codes: ["credit_unknown"],
          explanations_ru: ["credit UNKNOWN → RESEARCH_ONLY"],
          warnings_ru: ["кредитное качество неизвестно"],
          allowed_in_portfolio: true,
          target_weight: 0.65,
        },
      ],
      approved: [],
      approved_with_warnings: [],
      research_only: ["CORP"],
      blocked: [],
      insufficient_data: [],
      reason_codes: ["credit_unknown"],
      explanations_ru: ["credit UNKNOWN → RESEARCH_ONLY"],
      warnings_ru: ["кредитное качество неизвестно"],
      limitations: [],
      summary_ru: "Портфель только research",
    },
    note: "Yield alone never approves.",
    mode: "PORTFOLIO_RISK_GATE_V0",
  })),
}));

describe("PortfolioRiskPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders portfolio risk gate page", async () => {
    render(
      <MemoryRouter>
        <HelpProvider>
          <PortfolioRiskPage />
        </HelpProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Проверка риска портфеля Kraken")).toBeInTheDocument();
    expect(await screen.findByText(/Портфель только research/)).toBeInTheDocument();
  });
});
