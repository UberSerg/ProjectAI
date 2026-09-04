import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as forwardApi from "../api/forward";
import * as shadowApi from "../api/shadow";
import { HelpProvider } from "../help";
import { ShadowPage } from "./ShadowPage";

vi.mock("../api/shadow");
vi.mock("../api/forward");

const portfolioA = {
  id: "1",
  name: "SHADOW_HYSTERESIS_V1",
  status: "WAITING_FOR_FUTURE_MARKET_OPEN",
  policy_name: "RANK_HYSTERESIS_LONG_ONLY_V1",
  risk_name: "RISK_GUARDRAILS_V0",
  activated_at: "2026-09-04T14:15:29.275066+00:00",
  cash: 1_000_000,
  nav: 1_000_000,
  market_value: 0,
  drawdown: 0,
  gross_exposure: 0,
  peak_nav: 1_000_000,
  initial_capital: 1_000_000,
  risk_mode: "normal",
  exposure_cap: 1,
  pending_orders: 9,
  fills: 0,
  position_count: 0,
  last_processed_market_date: "2026-09-02",
  first_forward_batch_id: 1,
  first_forward_as_of_date: "2026-09-02",
  last_decision_iso_week: "2026-W36",
  experiment_group: "SHADOW_FORWARD_V0",
  kind: "FORWARD_SHADOW",
};

const portfolioB = {
  ...portfolioA,
  id: "2",
  name: "SHADOW_HYSTERESIS_DD_V1",
  risk_name: "DRAWDOWN_GUARD_V1",
  dd_trigger: -0.2,
  dd_recovery: -0.1,
  dd_risk_off_gross: 0.5,
  dd_normal_gross: 1,
};

const mgntOrder = {
  id: 1,
  ticker: "MGNT",
  display_name: "Magnit",
  side: "BUY",
  quantity: 71.66,
  target_weight: 0.1111111111111111,
  reason: "ENTER_TOP20",
  status: "PENDING",
  rank: 1,
  predicted_return_20d: 0.18999484146846618,
  eligible_count: 43,
  decision_at: "2026-09-04T14:15:29.275066+00:00",
  min_execution_date: "2026-09-05",
  execution_date: null,
  metadata: {
    kind: "FORWARD_SHADOW",
    policy: "RANK_HYSTERESIS_LONG_ONLY_V1",
    risk_mode: "normal",
    signal_as_of: "2026-09-02",
    forward_batch_id: 1,
    signal_generated_at: "2026-09-04T13:40:38.343892+00:00",
  },
};

function mockHappyPath() {
  vi.mocked(shadowApi.getShadowOverview).mockResolvedValue({
    kind: "FORWARD_SHADOW",
    experiment_group: "SHADOW_FORWARD_V0",
    activated_at: portfolioA.activated_at,
    automatic_schedule: "not_configured",
    portfolios: [portfolioA, portfolioB],
  });
  vi.mocked(shadowApi.getShadowOrders).mockImplementation(async (id) => {
    if (String(id) === "1" || String(id) === "2") {
      return [
        mgntOrder,
        ...Array.from({ length: 8 }, (_, i) => ({
          ...mgntOrder,
          id: i + 2,
          ticker: `T${i + 2}`,
          rank: i + 2,
          predicted_return_20d: 0.1 - i * 0.01,
        })),
      ];
    }
    return [];
  });
  vi.mocked(shadowApi.getShadowFills).mockResolvedValue([]);
  vi.mocked(shadowApi.getShadowNav).mockResolvedValue([]);
  vi.mocked(shadowApi.getShadowDecisions).mockResolvedValue([
    {
      id: 1,
      forward_batch_id: 1,
      signal_as_of_date: "2026-09-02",
      signal_generated_at: "2026-09-04T13:40:38.343892+00:00",
      decision_at: "2026-09-04T14:15:29.275066+00:00",
      iso_week: "2026-W36",
      targets: Array.from({ length: 9 }, () => ({})),
      risk_mode: "normal",
      policy_name: "RANK_HYSTERESIS_LONG_ONLY_V1",
    },
  ]);
  vi.mocked(forwardApi.getLatestForwardBatch).mockResolvedValue({
    batch: {
      id: "1",
      as_of_date: "2026-09-02",
      segment: "FORWARD_LIVE",
      status: "SUCCESS",
      candidate_name: "prediction_ml_candidate",
      candidate_version: "v0",
      candidate_config_hash: "4828047608080c1a75f3c365b9fcf52ed9e84c866fa23799087a69a99dddb649",
      feature_schema_hash: "abc",
      prediction_hash: "d7e8a1918c45c1d8cb778a08ce7b2afad82f1560c42e9709470b3eb39f788644",
      eligible_count: 43,
      ineligible_count: 0,
      prediction_count: 43,
      pit_status: "PASS",
      generated_at: "2026-09-04T13:40:38.343892+00:00",
    },
    predictions: [
      {
        instrument_id: 53,
        ticker: "MGNT",
        as_of_date: "2026-09-02",
        predicted_return_20d: 0.18999484146846618,
        rank: 1,
        eligible_count: 43,
        percentile: 1,
        quality_status: "ok",
        outcome_status: "pending",
        candidate_config_hash: "48280476",
        generated_at: "2026-09-04T13:40:38.343892+00:00",
      },
      ...Array.from({ length: 9 }, (_, i) => ({
        instrument_id: i + 2,
        ticker: `T${i + 2}`,
        as_of_date: "2026-09-02",
        predicted_return_20d: 0.1 - i * 0.01,
        rank: i + 2,
        eligible_count: 43,
        percentile: 0.9,
        quality_status: "ok",
        outcome_status: "pending",
        candidate_config_hash: "48280476",
        generated_at: "2026-09-04T13:40:38.343892+00:00",
      })),
    ],
  });
  vi.mocked(forwardApi.listForwardBatches).mockResolvedValue([
    {
      id: "1",
      as_of_date: "2026-09-02",
      segment: "FORWARD_LIVE",
      status: "SUCCESS",
      candidate_name: "prediction_ml_candidate",
      candidate_version: "v0",
      candidate_config_hash: "48280476",
      feature_schema_hash: "abc",
      prediction_hash: "d7e8a1918c45c1d8cb778a08ce7b2afad82f1560c42e9709470b3eb39f788644",
      eligible_count: 43,
      ineligible_count: 0,
      prediction_count: 43,
      pit_status: "PASS",
      generated_at: "2026-09-04T13:40:38.343892+00:00",
    },
  ]);
}

function renderPage() {
  return render(
    <MemoryRouter>
      <HelpProvider>
        <ShadowPage />
      </HelpProvider>
    </MemoryRouter>,
  );
}

describe("ShadowPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockHappyPath();
  });

  it("loads live experiment with two portfolios and pending-only truth", async () => {
    renderPage();
    expect(await screen.findByText("Живой эксперимент")).toBeInTheDocument();
    expect(screen.getByText(/не пересчитывает прошлое/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Рейтинговый портфель/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/защита от просадки/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Сделок пока нет")).toBeInTheDocument();
    expect(screen.getAllByText(/Ожидаем открытие рынка/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/ошибка эксперимента/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/1[\u00a0 ]000[\u00a0 ]000/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("MGNT").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("2026-W36").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/История NAV начнёт строиться/i)).toBeInTheDocument();
    expect(screen.getByText(/не настроено/i)).toBeInTheDocument();
    expect(screen.getAllByText("SHADOW_HYSTERESIS_V1").length).toBeGreaterThanOrEqual(1);
  });

  it("opens MGNT explanation without saying bought", async () => {
    renderPage();
    expect(await screen.findAllByText(/Ожидает покупки/i)).toBeTruthy();
    const row = screen.getAllByText(/Ожидает покупки/i)[0].closest("tr");
    expect(row).toBeTruthy();
    fireEvent.click(row!);
    expect(await screen.findByText("Почему принято это решение?")).toBeInTheDocument();
    expect(screen.getByText(/выбран для покупки/i)).toBeInTheDocument();
    expect(screen.queryByText(/MGNT куплен/i)).not.toBeInTheDocument();
  });

  it("shows API error state", async () => {
    vi.mocked(shadowApi.getShadowOverview).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByText(/boom/i)).toBeInTheDocument();
  });

  it("maps waiting status and A/B risk difference", async () => {
    renderPage();
    expect(await screen.findByText(/Базовые ограничения риска/i)).toBeInTheDocument();
    expect(screen.getByText(/Активируется при просадке/i)).toBeInTheDocument();
    expect(screen.getAllByText(/защита от просадки/i).length).toBeGreaterThanOrEqual(1);
  });
});
