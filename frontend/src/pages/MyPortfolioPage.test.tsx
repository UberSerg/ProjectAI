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

const analysisPortfolioB = {
  ...analysisFilled,
  portfolio: { ...analysisFilled.portfolio, id: 2, name: "Второй портфель" },
  concentration_by_issuer: [
    { issuer_key: "issuer:2", issuer_title: "Лукойл", market_value: 20000, weight: 0.5 },
  ],
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
}));

const listPersonalPortfolios = vi.fn();
const getPersonalPortfolio = vi.fn();
const addDraftPosition = vi.fn();
const patchPersonalPortfolio = vi.fn();
const deletePersonalPortfolio = vi.fn();
const setDraftCash = vi.fn();
const patchDraftPosition = vi.fn();
const deleteDraftPosition = vi.fn();
const clearDraftPortfolio = vi.fn();
const activatePersonalPortfolio = vi.fn();
const resetPersonalPortfolio = vi.fn();

vi.mock("../api/personalPortfolios", async () => {
  const actual = await vi.importActual<typeof import("../api/personalPortfolios")>(
    "../api/personalPortfolios",
  );
  return {
    ...actual,
    listPersonalPortfolios: (...args: unknown[]) => listPersonalPortfolios(...args),
    getPersonalPortfolio: (...args: unknown[]) => getPersonalPortfolio(...args),
    addDraftPosition: (...args: unknown[]) => addDraftPosition(...args),
    patchPersonalPortfolio: (...args: unknown[]) => patchPersonalPortfolio(...args),
    deletePersonalPortfolio: (...args: unknown[]) => deletePersonalPortfolio(...args),
    setDraftCash: (...args: unknown[]) => setDraftCash(...args),
    patchDraftPosition: (...args: unknown[]) => patchDraftPosition(...args),
    deleteDraftPosition: (...args: unknown[]) => deleteDraftPosition(...args),
    clearDraftPortfolio: (...args: unknown[]) => clearDraftPortfolio(...args),
    activatePersonalPortfolio: (...args: unknown[]) => activatePersonalPortfolio(...args),
    resetPersonalPortfolio: (...args: unknown[]) => resetPersonalPortfolio(...args),
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

const portfolioCardB = {
  ...portfolioCardActive,
  id: 2,
  name: "Второй портфель",
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

const draftSberPosition = {
  id: 11,
  instrument_id: 1,
  secid: "SBER",
  name: "Сбербанк",
  asset_class: "equity",
  units: "10",
  lots: null,
  average_price: "250",
  cost_basis_total_rub: "2500",
  cost_basis_status: "KNOWN" as const,
  current_price: "260",
  price_date: "2026-09-25",
  market_value: "2600",
  unrealized_pnl: "100",
  price_available: true,
};

const personalSummaryDraftWithSber = {
  ...personalSummaryDraft,
  summary: {
    ...personalSummaryDraft.summary,
    securities_value_rub: "2600",
    nav_rub: "2600",
  },
  positions: [draftSberPosition],
};

const personalSummaryActive = {
  ...personalSummaryDraft,
  portfolio: {
    ...personalSummaryDraft.portfolio,
    lifecycle_state: "ACTIVE" as const,
    has_operations: true,
    journal_state: "ACTIVE" as const,
  },
  summary: {
    ...personalSummaryDraft.summary,
    cash_rub: "10000",
    securities_value_rub: "30000",
    nav_rub: "40000",
    contributed_rub: "40000",
  },
  operations: [
    {
      id: 7,
      operation_type: "OPENING_CASH",
      status: "ACTIVE",
      occurred_at: "2026-09-20T10:00:00+00:00",
      instrument_id: null,
      lots: null,
      units: null,
      price: null,
      amount: "10000",
      commission: "0",
      currency: "RUB",
      note: null,
    },
  ],
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

vi.mock("../api/decisionMemory", () => ({
  listDecisionMemory: vi.fn().mockResolvedValue({ portfolio_id: 1, items: [], count: 0 }),
  getDecisionMemory: vi.fn(),
  getPossibleMatches: vi.fn(),
  captureDecisionMemory: vi.fn(),
  linkOperation: vi.fn(),
  unlinkOperation: vi.fn(),
  refreshDecisionOutcomes: vi.fn(),
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

import { ApiError } from "../api/client";
import * as instrumentsApi from "../api/instruments";
import * as portfolioApi from "../api/manualPortfolios";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

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
    localStorage.clear();
    vi.stubGlobal("confirm", vi.fn(() => true));
    vi.stubGlobal("alert", vi.fn());
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
      portfolio_id: 1,
      horizons: {
        "30d": { days: 30, gross: 0, coupon: 0, amortization: 0, redemption: 0, event_count: 0 },
        "90d": { days: 90, gross: 0, coupon: 0, amortization: 0, redemption: 0, event_count: 0 },
        "12m": { days: 365, gross: 0, coupon: 0, amortization: 0, redemption: 0, event_count: 0 },
      },
      events: [],
      next_payment: null,
      positions: [],
      analysis: {
        maturity_ladder: {},
        gov_vs_corp: { government: 0, corporate_or_other: 0 },
        bond_position_count: 0,
      },
      note: "Выплаты рассчитаны по текущему опубликованному графику облигации и могут измениться.",
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

  it("renders the portfolio from the deep link", async () => {
    listPersonalPortfolios.mockResolvedValue({
      items: [portfolioCardActive, portfolioCardB],
      count: 2,
    });
    getPersonalPortfolio.mockResolvedValue(personalSummaryActive);
    renderPage("/portfolio/2");
    await screen.findByTestId("my-portfolio-page");
    await waitFor(() => expect(getPersonalPortfolio).toHaveBeenCalled());
    expect(getPersonalPortfolio.mock.calls.every((call) => call[0] === 2)).toBe(true);
    expect(screen.getByRole("heading", { level: 1, name: "Второй портфель" })).toBeInTheDocument();
  });

  it("passes the selected portfolio id to every tab request", async () => {
    listPersonalPortfolios.mockResolvedValue({
      items: [portfolioCardActive, portfolioCardB],
      count: 2,
    });
    getPersonalPortfolio.mockResolvedValue(personalSummaryActive);
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisPortfolioB as never);
    vi.mocked(portfolioApi.getPortfolioCompareCandidate).mockResolvedValue(compareSample as never);
    vi.mocked(portfolioApi.getPortfolioRebalance).mockResolvedValue(rebalanceSample as never);
    renderPage("/portfolio/2");
    await screen.findByTestId("my-portfolio-page");

    fireEvent.click(screen.getByTestId("tab-analysis"));
    await waitFor(() => expect(portfolioApi.getPortfolioAnalysis).toHaveBeenCalledWith(2, expect.anything()));
    fireEvent.click(screen.getByTestId("tab-compare"));
    await waitFor(() =>
      expect(portfolioApi.getPortfolioCompareCandidate).toHaveBeenCalledWith(2, expect.anything()),
    );
    fireEvent.click(screen.getByTestId("tab-rebalance"));
    await waitFor(() => expect(portfolioApi.getPortfolioRebalance).toHaveBeenCalledWith(2, expect.anything()));
    fireEvent.click(screen.getByTestId("tab-payments"));
    await waitFor(() => expect(portfolioApi.getPortfolioCashflows).toHaveBeenCalledWith(2, expect.anything()));
  });

  it("exposes no retired single-portfolio helpers", async () => {
    const manual = await vi.importActual<Record<string, unknown>>("../api/manualPortfolios");
    const personal = await vi.importActual<Record<string, unknown>>("../api/personalPortfolios");
    const retired = [
      "getPrimaryManualPortfolio",
      "updatePrimaryCash",
      "addPrimaryPosition",
      "patchPrimaryPosition",
      "deletePrimaryPosition",
      "getPrimaryAnalysis",
      "getPrimaryCompareCandidate",
      "getPrimaryRebalance",
      "getPrimaryCashflows",
      "getPersonalPrimary",
      "activatePersonalJournal",
    ];
    for (const name of retired) {
      expect(manual).not.toHaveProperty(name);
      expect(personal).not.toHaveProperty(name);
    }
    expect(Object.keys(manual).filter((k) => k.startsWith("getPrimary"))).toEqual([]);
    expect(Object.keys(personal).filter((k) => k.startsWith("getPrimary"))).toEqual([]);
  });

  it("reloads analysis when switching from portfolio A to portfolio B", async () => {
    listPersonalPortfolios.mockResolvedValue({
      items: [portfolioCardActive, portfolioCardB],
      count: 2,
    });
    getPersonalPortfolio.mockResolvedValue(personalSummaryActive);
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockImplementation((id: number) =>
      Promise.resolve((id === 2 ? analysisPortfolioB : analysisFilled) as never),
    );
    renderPage("/portfolio/1?tab=analysis");
    expect(await screen.findByText("Сбер")).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /Основной портфель ▾/ }));
    fireEvent.click(screen.getByRole("button", { name: /Второй портфель/ }));

    expect(await screen.findByText("Лукойл")).toBeInTheDocument();
    expect(screen.queryByText("Сбер")).not.toBeInTheDocument();
    expect(portfolioApi.getPortfolioAnalysis).toHaveBeenCalledWith(2, expect.anything());
  });

  it("ignores a late portfolio A analysis response after switching to B", async () => {
    listPersonalPortfolios.mockResolvedValue({
      items: [portfolioCardActive, portfolioCardB],
      count: 2,
    });
    getPersonalPortfolio.mockResolvedValue(personalSummaryActive);
    const pendingA = deferred<never>();
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockImplementation((id: number) =>
      id === 1 ? (pendingA.promise as never) : Promise.resolve(analysisPortfolioB as never),
    );
    renderPage("/portfolio/1?tab=analysis");
    expect(await screen.findByText(/Загрузка анализа…/)).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /Основной портфель ▾/ }));
    fireEvent.click(screen.getByRole("button", { name: /Второй портфель/ }));
    expect(await screen.findByText("Лукойл")).toBeInTheDocument();

    pendingA.resolve(analysisFilled as never);
    await waitFor(() => expect(screen.getByText("Лукойл")).toBeInTheDocument());
    expect(screen.queryByText("Сбер")).not.toBeInTheDocument();
  });

  it("shows a preliminary analysis for a DRAFT portfolio", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisFilled as never);
    renderPage("/portfolio/1?tab=analysis");
    expect(await screen.findByTestId("draft-preliminary-analysis-note")).toHaveTextContent(
      /История операций ещё не начата\. Анализ относится к текущему составу портфеля\./,
    );
    expect(screen.getByText("Предварительный анализ")).toBeInTheDocument();
    expect(screen.queryByText(/Анализ после начала учёта/i)).not.toBeInTheDocument();
    expect(await screen.findByText("Сбер")).toBeInTheDocument();
  });

  it("marks DRAFT compare and rebalance as preliminary", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisFilled as never);
    vi.mocked(portfolioApi.getPortfolioCompareCandidate).mockResolvedValue(compareSample as never);
    vi.mocked(portfolioApi.getPortfolioRebalance).mockResolvedValue(rebalanceSample as never);
    renderPage("/portfolio/1?tab=compare");
    expect(await screen.findByTestId("draft-preliminary-compare-note")).toHaveTextContent(
      "Предварительный расчёт по текущему составу.",
    );
    fireEvent.click(screen.getByTestId("tab-rebalance"));
    expect(await screen.findByTestId("draft-preliminary-rebalance-note")).toHaveTextContent(
      "Предварительный расчёт по текущему составу.",
    );
  });

  it("keeps Состав usable when analysis fails", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockRejectedValue(
      new ApiError("Request failed (500)", 500),
    );
    renderPage("/portfolio/1?tab=analysis");
    expect(await screen.findByText(/Не удалось загрузить данные/i)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tab-holdings"));
    expect(await screen.findByTestId("draft-setup-banner")).toBeInTheDocument();
  });

  it("never shows raw retired-endpoint wording to USER", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockRejectedValue(
      new ApiError("/manual-portfolios/primary retired", 410, { detail: { code: "PRIMARY_RETIRED" } }),
    );
    renderPage("/portfolio/1?tab=analysis");
    expect(
      await screen.findByText("Не удалось загрузить выбранный портфель. Обновите страницу."),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/PRIMARY_RETIRED/i);
    expect(document.body.textContent).not.toMatch(/singleton/i);
  });

  it("renders the ACTIVE journal with a readable opening label", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardActive], count: 1 });
    getPersonalPortfolio.mockResolvedValue(personalSummaryActive);
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisFilled as never);
    renderPage("/portfolio/1?tab=history");
    expect(await screen.findByText("Журнал операций")).toBeInTheDocument();
    expect(screen.getByText("Начальное состояние · деньги")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/cutover|bootstrap|projection/i);
  });

  it("deletes the portfolio after two confirmations", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardActive], count: 1 });
    getPersonalPortfolio.mockResolvedValue(personalSummaryActive);
    deletePersonalPortfolio.mockResolvedValue({ status: "DELETED", id: 1, name: "Основной портфель" });
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisFilled as never);
    renderPage();
    fireEvent.click(await screen.findByTestId("delete-portfolio-btn"));
    await waitFor(() => expect(deletePersonalPortfolio).toHaveBeenCalledWith(1));
    expect(window.confirm).toHaveBeenCalledTimes(2);
  });

  it("shows not-found for an id outside the portfolio list", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardActive], count: 1 });
    renderPage("/portfolio/999");
    expect(await screen.findByText("Портфель не найден")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /К списку портфелей/i })).toBeInTheDocument();
  });

  it("labels fundamental coverage as a research cohort, not the selected portfolio", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardActive], count: 1 });
    getPersonalPortfolio.mockResolvedValue(personalSummaryActive);
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisFilled as never);
    renderPage("/portfolio/1?tab=analysis");
    const scope = await screen.findByTestId("fundamental-coverage-scope");
    expect(scope).toHaveTextContent(/исследовательская выборка/i);
    expect(scope).toHaveTextContent(/не покрытие\s+выбранного портфеля/i);
  });

  it("shows a newly added instrument without remounting the panel", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisEmpty as never);
    let added = false;
    getPersonalPortfolio.mockImplementation(() =>
      Promise.resolve(added ? personalSummaryDraftWithSber : personalSummaryDraft),
    );
    addDraftPosition.mockImplementation(() => {
      added = true;
      return Promise.resolve({ id: 11, portfolio: personalSummaryDraftWithSber });
    });
    renderPage();

    const panel = await screen.findByTestId("personal-portfolio-panel");
    expect(screen.getByText("Пока нет позиций")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("add-instrument-open"));
    fireEvent.change(screen.getByTestId("add-instrument-search"), { target: { value: "SBER" } });
    await waitFor(() => expect(screen.getByTestId("add-instrument-hits")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /SBER/i }));
    fireEvent.click(screen.getByTestId("add-instrument-submit"));

    await waitFor(() => expect(addDraftPosition).toHaveBeenCalledWith(1, expect.anything()));
    expect(await screen.findByTestId("draft-positions-table")).toHaveTextContent("SBER");
    expect(screen.queryByText("Пока нет позиций")).not.toBeInTheDocument();
    // Same DOM node ⇒ the panel refetched in place instead of being remounted.
    expect(screen.getByTestId("personal-portfolio-panel")).toBe(panel);
    await waitFor(() => expect(listPersonalPortfolios).toHaveBeenCalledTimes(2));
  });

  it("reflects a DRAFT cash edit immediately and refreshes the list", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisEmpty as never);
    const withCash = {
      ...personalSummaryDraft,
      summary: { ...personalSummaryDraft.summary, cash_rub: "50000", nav_rub: "50000" },
    };
    let saved = false;
    getPersonalPortfolio.mockImplementation(() =>
      Promise.resolve(saved ? withCash : personalSummaryDraft),
    );
    setDraftCash.mockImplementation(() => {
      saved = true;
      return Promise.resolve(withCash);
    });
    renderPage();

    fireEvent.click(await screen.findByTestId("draft-cash-edit-btn"));
    fireEvent.change(screen.getByTestId("draft-cash-input"), { target: { value: "50000" } });
    fireEvent.click(screen.getByTestId("draft-cash-submit"));

    await waitFor(() => expect(setDraftCash).toHaveBeenCalledWith(1, 50000));
    await waitFor(() =>
      expect(screen.getByTestId("draft-summary").textContent).toMatch(/50[\s\u00a0]?000/),
    );
    await waitFor(() => expect(listPersonalPortfolios).toHaveBeenCalledTimes(2));
  });

  it("reflects a DRAFT position edit immediately", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisEmpty as never);
    const edited = {
      ...personalSummaryDraftWithSber,
      positions: [{ ...draftSberPosition, units: "40", market_value: "10400" }],
    };
    let saved = false;
    getPersonalPortfolio.mockImplementation(() =>
      Promise.resolve(saved ? edited : personalSummaryDraftWithSber),
    );
    patchDraftPosition.mockImplementation(() => {
      saved = true;
      return Promise.resolve({ id: 11, portfolio: edited });
    });
    renderPage();

    fireEvent.click(await screen.findByTestId("draft-position-edit-11"));
    fireEvent.change(screen.getByTestId("draft-position-units"), { target: { value: "40" } });
    fireEvent.click(screen.getByTestId("draft-position-submit"));

    await waitFor(() => expect(patchDraftPosition).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByTestId("draft-positions-table").textContent).toMatch(/40/),
    );
    await waitFor(() => expect(listPersonalPortfolios).toHaveBeenCalledTimes(2));
  });

  it("removes a DRAFT position immediately", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisEmpty as never);
    let removed = false;
    getPersonalPortfolio.mockImplementation(() =>
      Promise.resolve(removed ? personalSummaryDraft : personalSummaryDraftWithSber),
    );
    deleteDraftPosition.mockImplementation(() => {
      removed = true;
      return Promise.resolve({ status: "DELETED", id: 11, portfolio: personalSummaryDraft });
    });
    renderPage();

    fireEvent.click(await screen.findByTestId("draft-position-remove-11"));
    await waitFor(() => expect(deleteDraftPosition).toHaveBeenCalledWith(1, 11));
    expect(await screen.findByText("Пока нет позиций")).toBeInTheDocument();
    await waitFor(() => expect(listPersonalPortfolios).toHaveBeenCalledTimes(2));
  });

  it("clears the DRAFT portfolio immediately", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisEmpty as never);
    let cleared = false;
    getPersonalPortfolio.mockImplementation(() =>
      Promise.resolve(cleared ? personalSummaryDraft : personalSummaryDraftWithSber),
    );
    clearDraftPortfolio.mockImplementation(() => {
      cleared = true;
      return Promise.resolve(personalSummaryDraft);
    });
    renderPage();

    fireEvent.click(await screen.findByTestId("clear-draft-btn"));
    await waitFor(() => expect(clearDraftPortfolio).toHaveBeenCalledWith(1));
    expect(await screen.findByText("Пока нет позиций")).toBeInTheDocument();
    await waitFor(() => expect(listPersonalPortfolios).toHaveBeenCalledTimes(2));
  });

  it("keeps the stored selection when the deep link points at an unknown portfolio", async () => {
    localStorage.setItem("kraken.selectedPortfolioId", "1");
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardActive], count: 1 });
    renderPage("/portfolio/999999?tab=analysis");

    expect(await screen.findByText("Портфель не найден")).toBeInTheDocument();
    expect(localStorage.getItem("kraken.selectedPortfolioId")).toBe("1");
    expect(getPersonalPortfolio).not.toHaveBeenCalled();
    expect(portfolioApi.getPortfolioAnalysis).not.toHaveBeenCalled();
    expect(portfolioApi.getPortfolioCompareCandidate).not.toHaveBeenCalled();
    expect(portfolioApi.getPortfolioRebalance).not.toHaveBeenCalled();
    expect(portfolioApi.getPortfolioCashflows).not.toHaveBeenCalled();
  });

  it("does not store a non-numeric deep link id", async () => {
    localStorage.setItem("kraken.selectedPortfolioId", "1");
    listPersonalPortfolios.mockResolvedValue({ items: [portfolioCardActive], count: 1 });
    renderPage("/portfolio/abc");

    expect(await screen.findByText("Портфель не найден")).toBeInTheDocument();
    expect(localStorage.getItem("kraken.selectedPortfolioId")).toBe("1");
    expect(getPersonalPortfolio).not.toHaveBeenCalled();
  });

  it("stores the selection for a valid deep link", async () => {
    localStorage.setItem("kraken.selectedPortfolioId", "1");
    listPersonalPortfolios.mockResolvedValue({
      items: [portfolioCardActive, portfolioCardB],
      count: 2,
    });
    getPersonalPortfolio.mockResolvedValue(personalSummaryActive);
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisPortfolioB as never);
    renderPage("/portfolio/2");

    await waitFor(() => expect(getPersonalPortfolio).toHaveBeenCalled());
    expect(getPersonalPortfolio.mock.calls.every((call) => call[0] === 2)).toBe(true);
    await waitFor(() => expect(localStorage.getItem("kraken.selectedPortfolioId")).toBe("2"));
  });

  it("shows not-found for an unknown explicit id even when the collection is empty", async () => {
    localStorage.setItem("kraken.selectedPortfolioId", "1");
    listPersonalPortfolios.mockResolvedValue({ items: [], count: 0 });
    renderPage("/portfolio/999999");

    expect(await screen.findByText("Портфель не найден")).toBeInTheDocument();
    expect(screen.queryByText(/У вас пока нет портфелей/i)).not.toBeInTheDocument();
    expect(localStorage.getItem("kraken.selectedPortfolioId")).not.toBe("999999");
    expect(getPersonalPortfolio).not.toHaveBeenCalled();
    expect(portfolioApi.getPortfolioAnalysis).not.toHaveBeenCalled();
  });

  it("keeps onboarding on /portfolio/mine when the collection is empty", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [], count: 0 });
    renderPage("/portfolio/mine");

    expect(await screen.findByText(/У вас пока нет портфелей/i)).toBeInTheDocument();
    expect(screen.queryByText("Портфель не найден")).not.toBeInTheDocument();
    expect(getPersonalPortfolio).not.toHaveBeenCalled();
  });

  it("uses a dedicated search-results list without plain-list bullets", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisEmpty as never);
    renderPage();
    fireEvent.click(await screen.findByTestId("add-instrument-open"));
    fireEvent.change(screen.getByTestId("add-instrument-search"), { target: { value: "SB" } });
    const hits = await screen.findByTestId("add-instrument-hits");
    expect(hits).toHaveClass("instrument-search-results");
    expect(hits).not.toHaveClass("plain-list");
    expect(hits.querySelector(".instrument-search-result-button")).toBeTruthy();
    expect(screen.getByTestId("add-instrument-modal").querySelector(".modal-actions")).toBeTruthy();
  });

  it("hides hits after selection and blocks stale submit after the query changes", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisEmpty as never);
    vi.mocked(instrumentsApi.searchCatalogInstruments).mockImplementation(async (params) => {
      const search = String((params as { search?: string })?.search || "").toUpperCase();
      if (search.startsWith("GAZ")) {
        return {
          items: [
            {
              id: 7,
              symbol: "GAZP",
              name: "Газпром",
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
        };
      }
      return {
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
      };
    });
    renderPage();
    fireEvent.click(await screen.findByTestId("add-instrument-open"));
    fireEvent.change(screen.getByTestId("add-instrument-search"), { target: { value: "SBER" } });
    await waitFor(() => expect(screen.getByTestId("add-instrument-hits")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /SBER/i }));
    expect(screen.queryByTestId("add-instrument-hits")).not.toBeInTheDocument();
    expect(screen.getByTestId("add-instrument-selected")).toHaveTextContent(/SBER/);

    fireEvent.change(screen.getByTestId("add-instrument-search"), { target: { value: "GAZP" } });
    expect(screen.queryByTestId("add-instrument-selected")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("add-instrument-submit"));
    expect(await screen.findByText("Выберите инструмент")).toBeInTheDocument();
    expect(addDraftPosition).not.toHaveBeenCalled();

    const gazpHit = await screen.findByRole("button", { name: /GAZP/i });
    fireEvent.click(gazpHit);
    fireEvent.click(screen.getByTestId("add-instrument-submit"));
    await waitFor(() =>
      expect(addDraftPosition).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ instrument_id: 7 }),
      ),
    );
  });

  it("does not briefly re-show stale SBER hits after clearing a selection and typing a new query", async () => {
    vi.mocked(portfolioApi.getPortfolioAnalysis).mockResolvedValue(analysisEmpty as never);
    const searchMock = vi.mocked(instrumentsApi.searchCatalogInstruments);
    searchMock.mockImplementation(async (params) => {
      const search = String((params as { search?: string })?.search || "").toUpperCase();
      if (search.startsWith("GAZ") || search === "GA") {
        return {
          items: [
            {
              id: 7,
              symbol: "GAZP",
              name: "Газпром",
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
        };
      }
      return {
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
      };
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("add-instrument-open"));
    fireEvent.change(screen.getByTestId("add-instrument-search"), { target: { value: "SBER" } });
    await waitFor(() => expect(screen.getByTestId("add-instrument-hits")).toHaveTextContent("SBER"));
    fireEvent.click(screen.getByRole("button", { name: /SBER/i }));
    expect(screen.queryByTestId("add-instrument-hits")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("add-instrument-search"), { target: { value: "GA" } });
    expect(screen.queryByTestId("add-instrument-hits")).not.toBeInTheDocument();
    expect(screen.queryByText("Сбербанк")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("add-instrument-search"), { target: { value: "GAZP" } });
    const hits = await screen.findByTestId("add-instrument-hits");
    expect(hits).toHaveTextContent("GAZP");
    expect(hits).not.toHaveTextContent("SBER");
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
