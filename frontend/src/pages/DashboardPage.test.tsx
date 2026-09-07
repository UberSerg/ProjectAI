import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import * as investmentApi from "../api/investment";
import * as marketApi from "../api/market";
import * as systemApi from "../api/system";
import * as workflowsApi from "../api/workflows";
import { DashboardPage } from "./DashboardPage";
import { PortfolioPage } from "./PortfolioPage";

vi.mock("../api/market");
vi.mock("../api/system");
vi.mock("../api/workflows");
vi.mock("../api/investment");

describe("DashboardPage", () => {
  beforeEach(() => {
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
    vi.mocked(investmentApi.previewPortfolioCandidate).mockResolvedValue({
      candidate_id: "pc_test",
      version: "CONCRETE_PORTFOLIO_CANDIDATE_V1",
      as_of: "2026-09-05",
      generated_at: "2026-09-07T00:00:00Z",
      capital: "100000",
      currency: "RUB",
      status: "READY_FOR_RESEARCH",
      summary: {
        positions_count: 2,
        equity_positions: 1,
        fixed_income_positions: 1,
        equity_rub: "24000",
        fixed_income_rub: "63000",
        cash_rub: "13000",
        research_only_count: 1,
        executable_count: 1,
      },
      readiness: {
        mode_ru: "Исследовательский режим",
        ready_for_real_money: false,
        banner_ru: "Не готов для реальных денег",
        reasons_ru: ["Equity confidence: Недостаточно данных"],
      },
      allocation: {
        equity: { target_weight: 0.25, actual_weight: 0.24, target_rub: "25000", actual_rub: "24000" },
        fixed_income: {
          target_weight: 0.65,
          actual_weight: 0.63,
          target_rub: "65000",
          actual_rub: "63000",
        },
        cash: { target_weight: 0.1, actual_weight: 0.13, target_rub: "10000", actual_rub: "13000" },
      },
      positions: [
        {
          instrument_id: 1,
          symbol: "SBER",
          display_name: "Сбербанк",
          sleeve: "EQUITY_ALPHA",
          asset_class: "equity",
          lots: 8,
          units: 80,
          lot_size: 10,
          reference_price: "300",
          estimated_notional: "24000",
          estimated_fees: "12",
          target_weight: 0.25,
          actual_weight: 0.24,
          risk_status: "RESEARCH_ONLY",
          executable: false,
          reason_ru: "Research-only equity sleeve pick.",
          warnings_ru: [],
          selection_rank: 1,
        },
        {
          instrument_id: 2,
          symbol: "SU26238RMFS4",
          display_name: "ОФЗ 26238",
          sleeve: "FIXED_INCOME",
          asset_class: "bond",
          lots: 6,
          units: 6,
          lot_size: 1,
          reference_price: "98.5",
          dirty_price: "100.2",
          nkd: "1.7",
          estimated_notional: "63000",
          estimated_fees: "30",
          target_weight: 0.65,
          actual_weight: 0.63,
          risk_status: "APPROVED_WITH_WARNINGS",
          executable: true,
          reason_ru: "Government bond research pick.",
          warnings_ru: [],
          credit_status: "UNKNOWN",
          bond_type: "ОФЗ",
          selection_rank: 1,
        },
      ],
      cash: {
        strategic_target_rub: "10000",
        strategic_target_weight: 0.1,
        lot_remainder_rub: "3000",
        total_cash_rub: "13000",
      },
      rejected_candidates: [],
      warnings: ["Equity confidence неизвестна"],
      reasons_ru: ["Тестовое объяснение"],
      money: {
        starting_capital: "100000",
        invested: "87000",
        equity_invested: "24000",
        fixed_income_invested: "63000",
        fees: "42",
        equity_fees: "12",
        fixed_income_fees: "30",
        strategic_cash: "10000",
        lot_remainder: "3000",
        ending_preview_cash: "13000",
      },
      composition: {
        equity: { selected: 1 },
        fixed_income: { selected: 1 },
      },
      provenance: {
        candidate_version: "CONCRETE_PORTFOLIO_CANDIDATE_V1",
        equity_policy: "EQUITY_COMPOSITION_V1",
        fixed_income_policy: "FIXED_INCOME_COMPOSITION_V1",
      },
      benchmark: { cbr_hurdle_annual: 0.18 },
      decision_quality: {
        equity_confidence_label_ru: "Недостаточно данных",
        equity_confidence_reason_ru: "Мало данных",
      },
      diff: {
        has_previous: false,
        summary_ru: "Это первый сохранённый кандидат портфеля.",
        changes: [],
      },
    } as never);
  });

  it("renders russian overview metrics and real DB statuses", async () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Обзор")).toBeInTheDocument();
    expect(await screen.findByText("43")).toBeInTheDocument();
    expect(
      await screen.findByText("Kraken рекомендует исследовательское распределение"),
    ).toBeInTheDocument();
    expect(await screen.findByText("Система работает нормально")).toBeInTheDocument();
    expect(await screen.findByText("Основная БД")).toBeInTheDocument();
    expect(screen.getByText("База памяти")).toBeInTheDocument();
    expect(screen.getAllByText("Работает").length).toBeGreaterThanOrEqual(2);
    expect(await screen.findByText(/2 позиций/)).toBeInTheDocument();
    expect(screen.getByText("Открыть состав")).toBeInTheDocument();
  });

  it("renders error state", async () => {
    vi.mocked(marketApi.getMarketSummary).mockRejectedValue(new Error("boom"));
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
    expect(screen.getByText("Портфель")).toBeInTheDocument();
    expect(screen.getAllByText("Открыть кандидат портфеля").length).toBeGreaterThanOrEqual(1);
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
    vi.mocked(marketApi.getMarketSummary).mockResolvedValue({
      instruments_count: 0,
      active_instruments_count: 0,
      records_count: 0,
      batches_count: 0,
      dq_warnings: 0,
      dq_errors: 0,
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
    expect(screen.getAllByText("Скоро").length).toBeGreaterThan(0);
  });
});
