import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HelpProvider } from "../help";
import { getPageHelp } from "../help/registry";
import { PortfolioProvider } from "../portfolio/PortfolioContext";
import { MyPortfolioPage } from "./MyPortfolioPage";

const analysisEmpty = {
  portfolio: {
    id: 1,
    name: "Primary Manual Portfolio",
    source: "MANUAL",
    base_currency: "RUB",
    cash_rub: 0,
    version: 1,
    created_at: null,
    updated_at: null,
    positions: [],
  },
  cash_rub: 0,
  market_value_supported: 0,
  nav: 0,
  positions: [],
  allocation: [],
  concentration_by_issuer: [],
  risk_findings: [],
  coverage_pct: 100,
  quality: "LIVE",
  unsupported_count: 0,
  advisory: true,
  note: "Risk findings are advisory; not a BLOCKED gate",
};

const analysisFilled = {
  ...analysisEmpty,
  cash_rub: 10000,
  nav: 40000,
  market_value_supported: 30000,
  portfolio: {
    ...analysisEmpty.portfolio,
    cash_rub: 10000,
    positions: [
      {
        id: 11,
        instrument_id: 1,
        units: 10,
        average_price: 250,
        note: null,
        non_standard_lot: false,
      },
    ],
  },
  positions: [
    {
      position_id: 11,
      instrument_id: 1,
      symbol: "SBER",
      units: 10,
      market_value: 30000,
      unit_price: 300,
      quality: "LIVE",
      price_source: "INTRADAY_LAST",
      supported: true,
      detail: {},
      capabilities: {},
      suggested_action: "NO_VIEW",
      research_member: true,
      weight: 0.75,
    },
  ],
  allocation: [{ symbol: "SBER", weight: 0.75 }],
  concentration_by_issuer: [
    { issuer_key: "issuer:1", issuer_title: "Сбер", market_value: 30000, weight: 0.75 },
  ],
  risk_findings: [
    {
      code: "ISSUER_CONCENTRATION",
      severity: "WARN",
      issuer: "Сбер",
      weight: 0.75,
      message: "Issuer aggregate weight >= 25% (advisory)",
    },
  ],
  quality: "PARTIAL",
  credit_intelligence: {
    government_weight: 0.2,
    corporate_weight: 0.1,
    rated_corporate_weight: 0,
    unrated_corporate_weight: 0.1,
    credit_data_unavailable_weight: 0.1,
    bond_weight: 0.3,
    top_issuers: [
      {
        issuer_key: "gov",
        issuer_title: "Минфин РФ",
        market_value: 8000,
        weight: 0.2,
        availability_status: "GOVERNMENT_RUSSIAN_FEDERAL",
        rating_raw: null,
        agency_code: null,
      },
    ],
    provider_verdict: "NOT_READY",
    advisory: true,
  },
};

const compareSample = {
  nav: 40000,
  candidate_source: "live_preview",
  candidate_id: "pc_demo",
  comparisons: [
    {
      symbol: "SBER",
      manual_weight: 0.75,
      candidate_weight: 0.25,
      status: "BOTH",
      suggested_action: "REDUCE",
      note: null,
    },
    {
      symbol: "LKOH",
      manual_weight: null,
      candidate_weight: 0.2,
      status: "NOT_IN_MANUAL",
      suggested_action: "INCREASE",
      note: null,
    },
  ],
  manual_analysis: { coverage_pct: 100, quality: "PARTIAL", risk_findings: [] },
};

const rebalanceSample = {
  advisory: true,
  persisted_orders: false,
  nav: 40000,
  cash: 10000,
  projected_cash: 8000,
  plan_rows: [
    {
      instrument_id: 1,
      ticker: "SBER",
      action: "SELL",
      lots_delta: -2,
      units_delta: -20,
      target_weight: 0.25,
      current_weight: 0.75,
      estimated_price: 300,
      estimated_notional: -6000,
      lot_size: 10,
      reason: "TARGET",
    },
  ],
  review_rows: [],
  diagnostics: {},
  cash_safe: true,
};

vi.mock("../api/manualPortfolios", () => ({
  getPortfolioAnalysis: vi.fn(),
  getPortfolioCompareCandidate: vi.fn(),
  getPortfolioRebalance: vi.fn(),
  getPortfolioCashflows: vi.fn(),
  updatePrimaryCash: vi.fn(),
  addPrimaryPosition: vi.fn(),
  deletePrimaryPosition: vi.fn(),
}));

const listPersonalPortfolios = vi.fn();
const getPersonalPortfolio = vi.fn();
const addDraftPosition = vi.fn();

vi.mock("../api/personalPortfolios", async () => {
  const actual = await vi.importActual<typeof import("../api/personalPortfolios")>(
    "../api/personalPortfolios",
  );
  return {
    ...actual,
    listPersonalPortfolios: (...args: unknown[]) => listPersonalPortfolios(...args),
    getPersonalPortfolio: (...args: unknown[]) => getPersonalPortfolio(...args),
    addDraftPosition: (...args: unknown[]) => addDraftPosition(...args),
    patchPersonalPortfolio: vi.fn(),
    deletePersonalPortfolio: vi.fn(),
    createPersonalOperation: vi.fn(),
  };
});

const portfolioCardDraft = {
  id: 1,
  name: "Основной портфель",
  lifecycle_state: "DRAFT" as const,
  cash_rub: "0",
  known_nav_rub: "0",
  positions_count: 0,
  valuation_partial: false,
};

const portfolioCardActive = {
  ...portfolioCardDraft,
  lifecycle_state: "ACTIVE" as const,
  cash_rub: "10000",
  known_nav_rub: "40000",
  positions_count: 1,
};

const personalSummaryDraft = {
  portfolio: {
    id: 1,
    name: "Основной портфель",
    base_currency: "RUB",
    lifecycle_state: "DRAFT" as const,
    status: "ACTIVE",
    is_test: false,
    version: 1,
    has_operations: false,
    journal_state: "EMPTY" as const,
  },
  summary: {
    cash_rub: "0",
    securities_value_rub: "0",
    nav_rub: "0",
    contributed_rub: "0",
    withdrawn_rub: "0",
    investment_pnl_rub: "0",
    realized_pnl_rub: "0",
    valuation_complete: true,
    valuation_partial: false,
    valuation_as_of: null,
    valuation_label: "Оценка недоступна — нет цен",
    missing_price_count: 0,
  },
  positions: [],
  operations: [],
  recommendation_disclaimer: "Модельная рекомендация",
};

vi.mock("../api/dailyPersonalDecision", () => ({
  getDailyPersonalDecision: vi.fn().mockResolvedValue({
    as_of: "2026-09-27",
    status: "NEEDS_SETUP",
    headline: "Сначала добавьте портфель",
    summary: "Пока нет денег и позиций.",
    portfolio: {
      id: 1,
      journal_state: "EMPTY",
      cash_rub: "0",
      securities_value_rub: "0",
      nav_rub: "0",
      contributed_rub: "0",
      withdrawn_rub: "0",
      investment_pnl_rub: "0",
      symbols: [],
    },
    actions: [
      {
        id: "SETUP:portfolio:PORTFOLIO_EMPTY",
        priority: "HIGH",
        action: "SETUP",
        title: "Добавить текущий портфель",
        rationale: "Добавьте текущий портфель",
        reason_codes: ["PORTFOLIO_EMPTY"],
        facts: ["Журнал пуст"],
        limitations: [],
      },
    ],
    risks: [],
    data_quality: {
      valuation_complete: true,
      valuation_partial: false,
      valuation_as_of: null,
      valuation_from: null,
      valuation_to: null,
      valuation_label: null,
      missing_price_count: 0,
      degradations: [],
    },
    context: {},
    disclaimer: "Модельная рекомендация",
  }),
}));

vi.mock("../api/instruments", () => ({
  getCatalogInstrument: vi.fn(),
  searchCatalogInstruments: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 8 }),
}));

vi.mock("../role/KrakenRoleContext", () => ({
  useKrakenRole: () => ({ role: "USER", isUser: true, isOwner: false, setRole: () => undefined }),
  KrakenRoleProvider: ({ children }: { children: unknown }) => children,
}));

vi.mock("../api/fundamentals", async () => {
  const actual = await vi.importActual<typeof import("../api/fundamentals")>("../api/fundamentals");
  return {
    ...actual,
    getPortfolioFundamentalCoverage: vi.fn().mockResolvedValue({
      status: "OK",
      read_only: true,
      industrial_with_reports: 9,
      industrial_mapped: 9,
      bank_unsupported: 5,
      unmapped: 26,
      note: "Portfolio shows fundamental coverage read-only.",
      rows: [
        {
          secid: "LKOH",
          issuer_id: 15,
          support_status: "INDUSTRIAL_RAS_V1",
          reports: 5,
          latest_period_end: "2025-12-31",
          latest_known_at: "2026-03-20",
        },
      ],
    }),
  };
});

import * as instrumentsApi from "../api/instruments";
import * as portfolioApi from "../api/manualPortfolios";

function renderPage(initial = "/portfolio/1") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <HelpProvider>
        <PortfolioProvider>
          <Routes>
            <Route path="/portfolio/:portfolioId" element={<MyPortfolioPage />} />
            <Route path="/portfolio/mine" element={<MyPortfolioPage />} />
          </Routes>
        </PortfolioProvider>
      </HelpProvider>
    </MemoryRouter>,
  );
}

describe("MyPortfolioPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardDraft], count: 1 });
    getPersonalPortfolio.mockResolvedValue(personalSummaryDraft);
    vi.mocked(instrumentsApi.getCatalogInstrument).mockResolvedValue({
      id: 1,
      symbol: "SBER",
      name: "Сбербанк",
      asset_class: "equity",
      instrument_subtype: "equity_common",
      support_level: "FULL",
      primary_board: "TQBR",
      exchange: "MOEX",
      currency: "RUB",
      isin: null,
      is_active: true,
      first_seen_at: null,
      last_seen_at: null,
      research_member: true,
      capabilities: {
        can_live_quote: true,
        can_portfolio_value: true,
        can_predict: true,
        can_fundamental: true,
        can_fixed_income_analyze: false,
        can_rebalance: true,
        can_cashflow_project: false,
        reasons: {},
      },
      coverage: {
        live_quote: true,
        portfolio_value: true,
        predict: true,
        fundamental: true,
        fixed_income: false,
        rebalance: true,
        cashflow: false,
      },
      sources: [],
    });
    vi.mocked(instrumentsApi.searchCatalogInstruments).mockResolvedValue({
      items: [
        {
          id: 1,
          symbol: "SBER",
          name: "Сбербанк",
          asset_class: "equity",
          instrument_subtype: "equity_common",
          support_level: "FULL",
          primary_board: "TQBR",
          exchange: "MOEX",
          currency: "RUB",
          isin: null,
          is_active: true,
          sources: ["MOEX"],
        },
      ],
      total: 1,
      page: 1,
      page_size: 12,
    });
    vi.mocked(portfolioApi.getPortfolioCashflows).mockResolvedValue({
      as_of: "2026-09-07",
      windows: {
        "30d": { coupons: 0, amortizations: 0, redemptions: 0, total: 0 },
        "90d": { coupons: 0, amortizations: 0, redemptions: 0, total: 0 },
        "12m": { coupons: 0, amortizations: 0, redemptions: 0, total: 0 },
      },
      events: [],
      maturity_ladder: {},
      gov_corp: { government: 0, corporate: 0 },
      disclaimer:
        "Выплаты рассчитаны по текущему опубликованному графику облигации и могут измениться.",
    } as never);
  });

  it("shows draft setup on holdings tab", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisEmpty as never);
    renderPage();
    expect(await screen.findByTestId("draft-setup-banner")).toBeInTheDocument();
    expect(screen.getByTestId("add-instrument-open")).toBeInTheDocument();
  });

  it("opens add instrument modal in draft mode", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisEmpty as never);
    renderPage();
    fireEvent.click(await screen.findByTestId("add-instrument-open"));
    expect(screen.getByTestId("add-instrument-modal")).toBeInTheDocument();
  });

  it("sends cost_basis_total_rub for bond draft position", async () => {
    addDraftPosition.mockResolvedValue({ id: 1, portfolio: personalSummaryDraft });
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisEmpty as never);
    vi.mocked(instrumentsApi.searchCatalogInstruments).mockResolvedValue({
      items: [
        {
          id: 2,
          symbol: "OFZ",
          name: "ОФЗ",
          asset_class: "bond",
          instrument_subtype: null,
          support_level: "PARTIAL",
          primary_board: "TQOB",
          exchange: "MOEX",
          currency: "RUB",
          isin: null,
          is_active: true,
          sources: ["MOEX"],
        },
      ],
      total: 1,
      page: 1,
      page_size: 12,
    });
    renderPage();
    fireEvent.click(await screen.findByTestId("add-instrument-open"));
    fireEvent.change(screen.getByTestId("add-instrument-search"), { target: { value: "OFZ" } });
    await waitFor(() => expect(screen.getByTestId("add-instrument-hits")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /OFZ/i }));
    expect(screen.getByTestId("add-instrument-cost-basis")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("add-instrument-cost-basis"), { target: { value: "100000" } });
    fireEvent.click(screen.getByTestId("add-instrument-submit"));
    await waitFor(() => expect(addDraftPosition).toHaveBeenCalled());
    const body = addDraftPosition.mock.calls[0][1] as Record<string, unknown>;
    expect(body.cost_basis_total_rub).toBe(100000);
    expect(body.average_price).toBeUndefined();
  });

  it("renders personal portfolio panel for holdings", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardActive], count: 1 });
    getPersonalPortfolio.mockResolvedValue({
      ...personalSummaryDraft,
      portfolio: {
        ...personalSummaryDraft.portfolio,
        lifecycle_state: "ACTIVE",
        has_operations: true,
        journal_state: "ACTIVE",
      },
    });
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisFilled as never);
    renderPage();
    expect(await screen.findByTestId("personal-portfolio-panel")).toBeInTheDocument();
    expect(screen.getByTestId("model-recommendation-disclaimer")).toBeInTheDocument();
  });

  it("loads decision tab with daily personal decision", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardActive], count: 1 });
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisFilled as never);
    renderPage();
    await screen.findByTestId("personal-portfolio-panel");
    fireEvent.click(screen.getByTestId("tab-decision"));
    expect(await screen.findByTestId("tab-decision-panel")).toBeInTheDocument();
    expect(await screen.findByTestId("daily-decision-panel")).toBeInTheDocument();
    expect(screen.getByTestId("daily-action-SETUP")).toBeInTheDocument();
  });

  it("loads compare tab", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardActive], count: 1 });
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisFilled as never);
    vi.mocked(portfolioApi.getPortfolioCompareCandidate).mockResolvedValue(compareSample as never);
    renderPage();
    await screen.findByTestId("personal-portfolio-panel");
    fireEvent.click(screen.getByTestId("tab-compare"));
    expect(await screen.findByText("LKOH")).toBeInTheDocument();
    expect(screen.getAllByText(/Увеличить|Нет в моём/i).length).toBeGreaterThanOrEqual(1);
  });

  it("loads rebalance tab with disclaimer", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardActive], count: 1 });
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisFilled as never);
    vi.mocked(portfolioApi.getPortfolioRebalance).mockResolvedValue(rebalanceSample as never);
    renderPage();
    await screen.findByTestId("personal-portfolio-panel");
    fireEvent.click(screen.getByTestId("tab-rebalance"));
    expect(await screen.findByText(/Расчётный план, не заявки/i)).toBeInTheDocument();
    expect(screen.getByText("Сократить")).toBeInTheDocument();
  });

  it("shows portfolio credit intelligence on analysis tab", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardActive], count: 1 });
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisFilled as never);
    renderPage();
    await screen.findByTestId("personal-portfolio-panel");
    fireEvent.click(screen.getByTestId("tab-analysis"));
    expect(await screen.findByTestId("portfolio-credit-intelligence")).toBeInTheDocument();
    expect(screen.getByText(/Кредитный риск облигаций/i)).toBeInTheDocument();
    expect(screen.getByText(/Минфин РФ/i)).toBeInTheDocument();
  });

  it("shows no-portfolios onboarding", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [], count: 0 });
    renderPage("/portfolio/mine");
    expect(await screen.findByText(/У вас пока нет портфелей/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Создать портфель/i })).toHaveAttribute("href", "/portfolio");
  });

  it("has page help for manual portfolio", () => {
    expect(getPageHelp("manual_portfolio")?.title).toMatch(/Мой портфель/);
    expect(getPageHelp("manual_portfolio")?.metrics).toEqual(
      expect.arrayContaining([
        "manual_portfolio",
        "rebalance",
        "bond_dirty_value",
        "credit_data_coverage",
        "government_debt",
      ]),
    );
  });
});
