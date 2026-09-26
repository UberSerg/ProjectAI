import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import * as investmentApi from "../api/investment";
import * as manualApi from "../api/manualPortfolios";
import * as marketApi from "../api/market";
import * as relationsApi from "../api/relations";
import * as shadowApi from "../api/shadow";
import * as systemApi from "../api/system";
import * as workflowsApi from "../api/workflows";
import { DashboardPage } from "./DashboardPage";
import { PortfolioPage } from "./PortfolioPage";

vi.mock("../api/market");
vi.mock("../api/system");
vi.mock("../api/workflows");
vi.mock("../api/investment");
vi.mock("../api/shadow");
vi.mock("../api/manualPortfolios");
vi.mock("../api/relations");

const analysisFixture = {
  portfolio: {
    id: 1,
    name: "PRIMARY",
    source: "MANUAL",
    base_currency: "RUB",
    cash_rub: 50000,
    version: 1,
    created_at: null,
    updated_at: null,
    positions: [{ id: 1, instrument_id: 10, units: 10, average_price: 100, note: null, non_standard_lot: false }],
  },
  cash_rub: 50000,
  market_value_supported: 150000,
  nav: 200000,
  positions: [
    {
      position_id: 1,
      instrument_id: 10,
      symbol: "SBER",
      units: 10,
      market_value: 150000,
      unit_price: 15000,
      quality: "LIVE",
      price_source: "LAST",
      supported: true,
      detail: {},
      capabilities: {},
      suggested_action: "KEEP",
      research_member: true,
      weight: 0.75,
    },
  ],
  allocation: [{ symbol: "SBER", weight: 0.75, sleeve: "EQUITY" }],
  concentration_by_issuer: [
    { issuer_key: "sber", issuer_title: "Сбербанк", market_value: 150000, weight: 0.75 },
  ],
  risk_findings: [
    {
      code: "CONCENTRATION",
      severity: "warning",
      message: "Высокая концентрация в одном эмитенте",
      symbol: "SBER",
    },
  ],
  coverage_pct: 1,
  quality: "LIVE",
  unsupported_count: 0,
  advisory: true,
  note: "Advisory оценка",
};

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.mocked(manualApi.getPrimaryAnalysis).mockResolvedValue(analysisFixture as never);
    vi.mocked(manualApi.getPrimaryRebalance).mockResolvedValue({
      advisory: true,
      persisted_orders: false,
      nav: 200000,
      cash: 50000,
      projected_cash: 40000,
      plan_rows: [
        {
          instrument_id: 10,
          ticker: "SBER",
          action: "REDUCE",
          lots_delta: -1,
          units_delta: -10,
          target_weight: 0.4,
          current_weight: 0.75,
          estimated_price: 15000,
          estimated_notional: -150000,
          lot_size: 10,
          reason: "Снизить концентрацию относительно кандидата",
        },
      ],
      review_rows: [],
      diagnostics: {},
      cash_safe: true,
    } as never);
    vi.mocked(manualApi.getPrimaryCompareCandidate).mockResolvedValue({
      nav: 200000,
      candidate_source: "preview",
      comparisons: [],
      manual_analysis: { coverage_pct: 1, quality: "LIVE", risk_findings: [] },
    } as never);
    vi.mocked(relationsApi.getPortfolioRelationsMatrix).mockResolvedValue({
      symbols: ["SBER"],
      metric: { label_ru: "Корреляция", window_observations: 60, window_label_ru: "60 дней" },
      cells: [],
      summary: {
        pair_count: 0,
        available_pair_count: 0,
        unavailable_pair_count: 0,
        status: "INSUFFICIENT_DATA",
      },
    } as never);
    vi.mocked(shadowApi.getShadowLive).mockResolvedValue({
      kind: "FORWARD_SHADOW",
      intraday_enabled: false,
      last_intraday_refresh: null,
      portfolios: [
        {
          id: "1",
          name: "SHADOW_HYSTERESIS_V1",
          status: "WAITING_FOR_FUTURE_MARKET_OPEN",
          policy_name: "RANK_HYSTERESIS_LONG_ONLY_V1",
          risk_name: "RISK_GUARDRAILS_V0",
          cash: 1_000_000,
          nav: 1_000_000,
          initial_capital: 1_000_000,
          risk_mode: "normal",
          exposure_cap: 1,
          pending_orders: 0,
          fills: 0,
          position_count: 0,
          live: { cash: 1_000_000, market_value: 0, nav: 1_000_000, positions: [] },
        },
      ],
    });
    vi.mocked(systemApi.getSystemHealth).mockResolvedValue({
      status: "ok",
      services: {
        backend: "ok",
        core_database: "ok",
        memory_database: "ok",
        redis: "ok",
        worker: "ok",
      },
    });
    vi.mocked(marketApi.getMarketSummary).mockResolvedValue({
      instruments_count: 43,
      active_instruments_count: 43,
      records_count: 28250,
      series_count: 5,
      batches_count: 10,
      dq_warnings: 6,
      dq_errors: 0,
      last_successful_update: "2026-08-20T00:00:00Z",
    });
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([
      {
        id: "1",
        name: "update",
        workflow_type: "MarketDataUpdate",
        status: "SUCCESS",
        started_at: "2026-08-21T10:00:00Z",
        finished_at: "2026-08-21T10:00:04Z",
        duration_seconds: 4,
        error: null,
        steps: [],
      },
    ]);
    vi.mocked(investmentApi.getHurdle).mockResolvedValue({
      status: "OK",
      annual_rate: 0.18,
      hurdle_1y: 0.18,
      as_of: "2026-09-01",
    } as never);
    vi.mocked(investmentApi.decideInvestment).mockResolvedValue({
      as_of: "2026-09-05",
      capital: "100000",
      cbr_hurdle_annual: 0.18,
      equity_opportunity: { calibration_status: "INSUFFICIENT_SAMPLE" },
      decision: {
        equity_weight: 0.25,
        fixed_income_weight: 0.65,
        cash_weight: 0.1,
        status: "RESEARCH_ONLY",
        explanations: ["Тестовое объяснение"],
        warnings: ["Equity confidence неизвестна"],
      },
      calibration: { uncertainty_note: "Мало проверенных прогнозов" },
      bond_safety_reminder: "Высокая доходность может отражать риск",
    } as never);
  });

  it("renders dark personal cockpit with portfolio summary and actions", async () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("kraken-cockpit")).toBeInTheDocument();
    expect(await screen.findByText("Обзор портфеля")).toBeInTheDocument();
    expect(await screen.findByTestId("cockpit-nav")).toBeInTheDocument();
    expect(await screen.findByTestId("cockpit-allocation")).toBeInTheDocument();
    expect(await screen.findByTestId("cockpit-performance")).toBeInTheDocument();
    expect(await screen.findByTestId("cockpit-risk")).toBeInTheDocument();
    expect(await screen.findByTestId("cockpit-recommendations")).toBeInTheDocument();
    expect(await screen.findByText("Что Kraken предлагает сделать")).toBeInTheDocument();
    expect(await screen.findByText(/Сократить SBER/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Подробнее" }).length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByTestId("dashboard-virtual-portfolio")).toBeInTheDocument();
    expect(await screen.findByText("Недавние события")).toBeInTheDocument();
  });

  it("renders error state when health fails", async () => {
    vi.mocked(systemApi.getSystemHealth).mockRejectedValue(new Error("boom"));
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Не удалось получить данные")).toBeInTheDocument();
  });
});

describe("PortfolioPage", () => {
  it("renders portfolio hub links", () => {
    render(
      <MemoryRouter>
        <PortfolioPage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Обзор портфеля/i)).toBeInTheDocument();
    expect(screen.getAllByText("Мой портфель").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Собрать портфель").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Инвестиционное решение")).toBeInTheDocument();
    expect(screen.getByText("Проверка риска")).toBeInTheDocument();
  });
});

describe("Navigation", () => {
  it("shows russian nav labels", async () => {
    vi.mocked(systemApi.getSystemHealth).mockResolvedValue({
      status: "ok",
      services: {
        backend: "ok",
        core_database: "ok",
        memory_database: "ok",
        redis: "ok",
        worker: "ok",
      },
    });
    vi.mocked(manualApi.getPrimaryAnalysis).mockResolvedValue(analysisFixture as never);
    vi.mocked(manualApi.getPrimaryRebalance).mockResolvedValue(null as never);
    vi.mocked(manualApi.getPrimaryCompareCandidate).mockResolvedValue(null as never);
    vi.mocked(relationsApi.getPortfolioRelationsMatrix).mockResolvedValue({
      symbols: [],
      metric: { label_ru: "", window_observations: 60 },
      cells: [],
      summary: { pair_count: 0, available_pair_count: 0, unavailable_pair_count: 0, status: "OK" },
    } as never);
    vi.mocked(shadowApi.getShadowLive).mockResolvedValue({
      kind: "FORWARD_SHADOW",
      intraday_enabled: false,
      last_intraday_refresh: null,
      portfolios: [],
    });
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([]);
    vi.mocked(investmentApi.getHurdle).mockResolvedValue(null as never);
    vi.mocked(investmentApi.decideInvestment).mockRejectedValue(new Error("offline"));
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Котировки")).toBeInTheDocument();
    expect(screen.getByText("Исторические симуляции")).toBeInTheDocument();
    expect(screen.getByText("Процессы")).toBeInTheDocument();
    expect(screen.getByText("Портфель")).toBeInTheDocument();
    expect(screen.getByText("Обзор исследований")).toBeInTheDocument();
    expect(screen.getByText("Компании")).toBeInTheDocument();
    expect(screen.queryByText("Скоро")).toBeNull();
  });
});
