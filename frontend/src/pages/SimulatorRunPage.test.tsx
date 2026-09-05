import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as simulatorApi from "../api/simulator";
import { HelpProvider } from "../help";
import { getMetricHelp, getPageHelp } from "../help/registry";
import { formatPercentPoints } from "../utils/format";
import { SimulatorRunPage } from "./SimulatorRunPage";

vi.mock("../api/simulator");

const baseRun = {
  id: 3,
  status: "SUCCESS",
  engineering_status: "PASS",
  research_result: null as string | null,
  segment: "FINAL_HOLDOUT",
  date_from: "2026-01-05",
  date_to: "2026-08-06",
  candidate_config_hash: "candhash001122",
  metrics: {
    initial_nav: 1_000_000,
    final_nav: 940_000,
    total_price_return: -0.06,
    excess_vs_imoex: 0.11,
    max_drawdown: -0.18,
    max_drawdown_peak_date: "2026-02-01",
    max_drawdown_trough_date: "2026-04-01",
    max_drawdown_recovery_date: null,
    sharpe_rf0: -0.4,
    turnover_ratio: 2.1,
    trade_count: 40,
  },
  benchmark: { total_price_return: -0.17 },
  spec: {
    policy_name: "RANK_LONG_ONLY_V0",
    commission_bps: 0,
    slippage_bps: 0,
    rebalance: "weekly",
    execution_timing: "next_open",
    initial_capital: 1_000_000,
    candidate_name: "prediction_ml_candidate",
    candidate_version: "v0",
  },
};

function mockHappyPath() {
  vi.mocked(simulatorApi.getSimulatorRun).mockResolvedValue(baseRun);
  vi.mocked(simulatorApi.getSimulatorNav).mockResolvedValue({
    run_id: 3,
    date_from: "2026-01-05",
    date_to: "2026-08-06",
    rebalance_dates: ["2026-01-12"],
    benchmark_series: [
      { date: "2026-01-05", close: 100 },
      { date: "2026-01-06", close: 99 },
      { date: "2026-01-07", close: 98 },
      { date: "2026-08-06", close: 83 },
    ],
    items: [
      {
        date: "2026-01-05",
        nav: 1_000_000,
        cash: 50_000,
        gross_exposure: 950_000,
        cash_weight: 0.05,
        peak_nav: 1_000_000,
        drawdown: 0,
      },
      {
        date: "2026-01-06",
        nav: 990_000,
        cash: 50_000,
        gross_exposure: 940_000,
        cash_weight: 0.05,
        peak_nav: 1_000_000,
        drawdown: -0.01,
      },
      {
        date: "2026-01-07",
        nav: 980_000,
        cash: 50_000,
        gross_exposure: 930_000,
        cash_weight: 0.05,
        peak_nav: 1_000_000,
        drawdown: -0.02,
      },
      {
        date: "2026-08-06",
        nav: 940_000,
        cash: 40_000,
        gross_exposure: 900_000,
        cash_weight: 0.04,
        peak_nav: 1_000_000,
        drawdown: -0.06,
      },
    ],
  });
  vi.mocked(simulatorApi.getSimulatorFills).mockResolvedValue([
    {
      execution_date: "2026-01-13",
      decision_date: "2026-01-12",
      instrument_id: 1,
      ticker: "SBER",
      side: "BUY",
      quantity: 100,
      fill_price: 280,
      notional: 28_000,
      prediction_date: "2026-01-12",
      predicted_return_20d: 0.04,
      rank: 1,
      target_weight: 0.05,
      reason: "ENTER_TOP20",
      policy_name: "RANK_HYSTERESIS_LONG_ONLY_V1",
      display_name: "Sberbank",
    },
  ]);
  vi.mocked(simulatorApi.getSimulatorCostSensitivity).mockResolvedValue({
    run_id: 3,
    segment: "FINAL_HOLDOUT",
    items: [
      {
        run_id: 3,
        commission_bps: 0,
        total_price_return: -0.06,
        final_nav: 940_000,
        max_drawdown: -0.18,
        is_current: true,
      },
      {
        run_id: 5,
        commission_bps: 5,
        total_price_return: -0.08,
        final_nav: 920_000,
        max_drawdown: -0.19,
        is_current: false,
      },
    ],
  });
  vi.mocked(simulatorApi.listSimulatorRuns).mockResolvedValue([
    {
      ...baseRun,
      id: 2,
      segment: "DEVELOPMENT_OOS",
      metrics: {
        ...baseRun.metrics,
        total_price_return: -0.04,
        excess_vs_imoex: 0.05,
      },
      benchmark: { total_price_return: -0.09 },
    },
    baseRun,
  ]);
  vi.mocked(simulatorApi.getSimulatorDay).mockResolvedValue({
    run_id: 3,
    as_of: "2026-01-06",
    nav: {
      nav: 990_000,
      cash: 50_000,
      gross_exposure: 940_000,
      cash_weight: 0.05,
      peak_nav: 1_000_000,
      drawdown: -0.01,
      positions_count: 1,
    },
    rebalance: false,
    positions: [
      {
        instrument_id: 1,
        ticker: "SBER",
        quantity: 100,
        market_price: 280,
        market_value: 28_000,
        weight: 0.028,
      },
    ],
    orders: [],
    fills: [],
  });
}

function renderRun(path = "/simulator/3") {
  return render(
    <HelpProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/simulator/:runId" element={<SimulatorRunPage />} />
        </Routes>
      </MemoryRouter>
    </HelpProvider>,
  );
}

describe("SimulatorRunPage", () => {
  beforeEach(() => {
    mockHappyPath();
  });

  it("loads hero metrics and styles absolute loss vs excess pp differently", async () => {
    renderRun();
    expect(await screen.findByText("Симуляция портфеля")).toBeInTheDocument();
    expect(screen.getByText("Доходность портфеля")).toBeInTheDocument();
    expect(screen.getAllByText("IMOEX").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Относительный результат (п.п.)")).toBeInTheDocument();

    const portfolio = screen.getByText("Доходность портфеля").closest("article");
    const excess = screen.getByText("Относительный результат (п.п.)").closest("article");
    expect(portfolio?.querySelector(".value-negative")).toBeTruthy();
    expect(excess?.querySelector(".value-excess")).toBeTruthy();
    expect(excess?.querySelector(".value-positive")).toBeNull();
    expect(excess?.textContent).toContain(formatPercentPoints(0.11));

    expect(screen.getByText("PASS")).toBeInTheDocument();
    expect(screen.getByText("MIXED")).toBeInTheDocument();
    expect(screen.getByText("Модель прогнозирования V0")).toBeInTheDocument();
  });

  it("opens fill explanation with human summary and technical provenance", async () => {
    renderRun();
    expect(await screen.findByText("SBER")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("SBER")[0]);
    expect(await screen.findByText("Почему была сделка?")).toBeInTheDocument();
    expect(screen.getByText(/верхние 20%|выбран для покупки|вошёл/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Технические детали/i }));
    expect(screen.getByText("ENTER_TOP20")).toBeInTheDocument();
  });

  it("loads day inspector when date query is set", async () => {
    renderRun("/simulator/3?from=2026-01-05&to=2026-08-06&date=2026-01-06");
    await waitFor(() => {
      expect(simulatorApi.getSimulatorDay).toHaveBeenCalledWith("3", "2026-01-06", expect.anything());
    });
    expect(await screen.findByText(/Позиции на/)).toBeInTheDocument();
  });

  it("registers help keys used by the dashboard", () => {
    for (const id of [
      "sim_nav",
      "sim_cagr",
      "sim_volatility",
      "sim_sharpe",
      "sim_max_drawdown",
      "sim_turnover",
      "sim_exposure",
      "sim_cash",
      "sim_excess",
      "sim_bps",
      "sim_slippage",
      "sim_commission",
      "sim_oos",
      "sim_holdout",
      "sim_rebalance",
      "sim_next_open",
      "sim_survivorship",
    ]) {
      expect(getMetricHelp(id)?.id).toBe(id);
    }
    expect(getPageHelp("simulator")?.title).toBe("Симуляции");
    expect(getPageHelp("simulator_run")?.title).toBe("Симуляция портфеля");
  });
});
