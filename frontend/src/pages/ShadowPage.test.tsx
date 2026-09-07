import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as forwardApi from "../api/forward";
import * as intradayApi from "../api/intraday";
import * as researchCycleApi from "../api/researchCycle";
import * as shadowApi from "../api/shadow";
import { HelpProvider } from "../help";
import { ShadowPage } from "./ShadowPage";

vi.mock("../api/shadow");
vi.mock("../api/forward");
vi.mock("../api/researchCycle");
vi.mock("../api/intraday");

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
  lot_aware: false,
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

const portfolioA_V2 = {
  ...portfolioA,
  id: "3",
  name: "SHADOW_HYSTERESIS_V2",
  experiment_group: "SHADOW_PORTFOLIO_REALISM_V2",
  lot_aware: true,
  execution_version: "LOT_AWARE_V2",
  skipped: [
    {
      ticker: "SBER",
      reason: "INSUFFICIENT_CASH_FOR_ONE_LOT",
      lot_size: 10,
    },
  ],
  order_plan: {
    strategic_cash_reserve: 50_000,
    rounding_remainder: 12_345.67,
    skipped: [
      {
        ticker: "SBER",
        reason: "INSUFFICIENT_CASH_FOR_ONE_LOT",
        lot_size: 10,
      },
    ],
  },
};

const portfolioB_V2 = {
  ...portfolioA_V2,
  id: "4",
  name: "SHADOW_HYSTERESIS_DD_V2",
  risk_name: "DRAWDOWN_GUARD_V1",
  dd_trigger: -0.2,
  dd_recovery: -0.1,
  skipped: [],
  order_plan: {
    strategic_cash_reserve: 50_000,
    rounding_remainder: 0,
    skipped: [],
  },
};

const mgntOrder = {
  id: 1,
  ticker: "MGNT",
  display_name: "Magnit",
  side: "BUY",
  quantity: 600,
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
    lots: 6,
    lot_size: 100,
    units: 600,
  },
};

function mockDailyOps(overrides?: Partial<shadowApi.ShadowDailyOperations>) {
  vi.mocked(shadowApi.getShadowDailyOperations).mockResolvedValue({
    latest_complete_eod_date: "2026-09-05",
    latest_forward_as_of: "2026-09-05",
    order_plan_status: "PRESENT",
    pending_orders: 9,
    ready_for_next_session: true,
    next_execution_session: "2026-09-06",
    status_code: "PENDING_ORDERS_AWAITING_OPEN",
    blocker_code: "PENDING_ORDERS_AWAITING_OPEN",
    eod_readiness: { ready: true, latest_complete_eod_date: "2026-09-05", reason: "eod_complete" },
    last_eod_cycle: {
      workflow_id: 9,
      status: "SUCCESS",
      finished_at: "2026-09-05T18:30:20Z",
      covers_latest_eod: true,
      stale: false,
    },
    ...overrides,
  });
}

function mockLive(overrides?: Partial<shadowApi.ShadowLiveResponse>) {
  vi.mocked(shadowApi.getShadowLive).mockResolvedValue({
    kind: "FORWARD_SHADOW",
    intraday_enabled: true,
    open_execution_policy: "SHADOW_NEXT_SESSION_OPEN_V1",
    last_intraday_refresh: { at: "2026-09-07T07:05:00Z", metrics: {} },
    portfolios: [
      {
        ...portfolioA,
        intraday_enabled: true,
        live: {
          cash: 1_000_000,
          market_value: 0,
          nav: 1_000_000,
          unrealized_pnl: null,
          quote_coverage: 1,
          warnings: [],
          positions: [],
        },
        pending_order_reasons: [
          {
            order_id: 1,
            ticker: "MGNT",
            side: "BUY",
            min_execution_date: "2026-09-05",
            created_at: portfolioA.activated_at,
            reason: "NEXT_SESSION_NOT_STARTED",
            session_date: "2026-09-07",
            market_status: "CLOSED",
            quote_freshness: "SESSION_NOT_STARTED",
          },
        ],
      },
      {
        ...portfolioB,
        intraday_enabled: true,
        live: {
          cash: 1_000_000,
          market_value: 0,
          nav: 1_000_000,
          positions: [],
        },
        pending_order_reasons: [],
      },
    ],
    ...overrides,
  });
}

function mockHappyPath(opts?: { withV2?: boolean }) {
  const portfolios = opts?.withV2
    ? [portfolioA, portfolioB, portfolioA_V2, portfolioB_V2]
    : [portfolioA, portfolioB];
  vi.mocked(shadowApi.getShadowOverview).mockResolvedValue({
    kind: "FORWARD_SHADOW",
    experiment_group: opts?.withV2 ? "SHADOW_PORTFOLIO_REALISM_V2" : "SHADOW_FORWARD_V0",
    activated_at: portfolioA.activated_at,
    automatic_schedule: "not_configured",
    intraday: {
      enabled: true,
      policy: "SHADOW_NEXT_SESSION_OPEN_V1",
      last_refresh: { at: "2026-09-07T07:05:00Z" },
      refresh_minutes: 5,
    },
    portfolios,
  });
  if (opts?.withV2) {
    mockLive({
      portfolios: [
        {
          ...portfolioA_V2,
          intraday_enabled: true,
          live: {
            cash: 950_000,
            market_value: 0,
            nav: 950_000,
            realized_pnl: 0,
            fees_paid: 120,
            unrealized_pnl: 0,
            quote_coverage: 1,
            positions: [],
          },
          pending_order_reasons: [
            {
              order_id: 1,
              ticker: "MGNT",
              side: "BUY",
              min_execution_date: "2026-09-05",
              reason: "NEXT_SESSION_NOT_STARTED",
              session_date: "2026-09-07",
              market_status: "CLOSED",
            },
          ],
        },
        {
          ...portfolioB_V2,
          intraday_enabled: true,
          live: { cash: 950_000, market_value: 0, nav: 950_000, positions: [] },
          pending_order_reasons: [],
        },
        {
          ...portfolioA,
          intraday_enabled: true,
          live: { cash: 1_000_000, market_value: 0, nav: 1_000_000, positions: [] },
          pending_order_reasons: [],
        },
        {
          ...portfolioB,
          intraday_enabled: true,
          live: { cash: 1_000_000, market_value: 0, nav: 1_000_000, positions: [] },
          pending_order_reasons: [],
        },
      ],
    });
  } else {
    mockLive();
  }
  mockDailyOps();
  vi.mocked(intradayApi.getIntradayStatus).mockResolvedValue({
    enabled: true,
    refresh_minutes: 5,
    cache_ttl_seconds: 1200,
    http_timeout_seconds: 20,
    persistence: "redis_ephemeral_only",
    writes_market_candles: false,
    policy: "SHADOW_NEXT_SESSION_OPEN_V1",
    last_refresh: { at: "2026-09-07T07:05:00Z" },
  });
  vi.mocked(shadowApi.getShadowOrders).mockImplementation(async () => {
    return [
      mgntOrder,
      ...Array.from({ length: 8 }, (_, i) => ({
        ...mgntOrder,
        id: i + 2,
        ticker: `T${i + 2}`,
        rank: i + 2,
        predicted_return_20d: 0.1 - i * 0.01,
        metadata: { lots: 1, lot_size: 10, units: 10 },
      })),
    ];
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
  vi.mocked(researchCycleApi.getResearchCycleStatus).mockResolvedValue({
    health: "WAITING_FOR_MARKET",
    health_human: "Ожидаем новые рыночные данные",
    watermarks: {
      raw_market_latest_date: "2026-09-02",
      forward_latest_as_of: "2026-09-02",
      forward_latest_batch_id: 1,
      shadow_portfolios: [
        {
          id: 1,
          status: "WAITING_FOR_FUTURE_MARKET_OPEN",
          last_processed_market_date: "2026-09-02",
        },
      ],
      forward_outcome_latest_status: "PENDING",
    },
    latest_cycle: {
      id: 9,
      name: "DAILY_RESEARCH_CYCLE_V0",
      status: "SUCCESS",
      started_at: "2026-09-04T18:30:00Z",
      finished_at: "2026-09-04T18:30:20Z",
      error: null,
      latest_forward_batch_id: 1,
    },
    schedule: { enabled: false, hour: 18, minute: 30, timezone: "UTC" },
    outcome_maturity: {
      batch_id: 1,
      as_of: "2026-09-02",
      future_trading_observations: 4,
      required: 20,
      status: "Ожидаем",
      matured: false,
    },
    automatic_schedule: "disabled",
  });
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

async function expandResearchDetails() {
  const btn = await screen.findByRole("button", { name: "Показать" });
  fireEvent.click(btn);
}

describe("ShadowPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockHappyPath();
  });

  it("loads live experiment with waiting session status and pending reasons", async () => {
    renderPage();
    expect(await screen.findByText("Живой эксперимент")).toBeInTheDocument();
    expect(screen.getByText(/проверяет решения на новых данных без реальных денег/i)).toBeInTheDocument();
    expect(screen.getByTestId("shadow-live-status")).toHaveTextContent(/Ожидаем торговую сессию/i);
    expect(screen.getByTestId("shadow-market-closed-calm")).toBeInTheDocument();
    expect(screen.getByTestId("shadow-decision-block")).toHaveTextContent(/2026-W36/);
    expect(screen.getByTestId("shadow-pending-reasons")).toHaveTextContent(
      /Следующая сессия ещё не началась/i,
    );
    expect(screen.getByTestId("shadow-readiness")).toHaveTextContent(/READY/i);
    expect(screen.getByTestId("shadow-lifecycle-strip")).toHaveTextContent(/Закрытие/);
    expect(screen.getByText(/не пересчитывает прошлое/i)).toBeInTheDocument();
    expect(screen.getByText("Сделок пока нет")).toBeInTheDocument();
    expect(screen.getAllByText(/Ожидаем открытие рынка/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/ошибка эксперимента/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Ожидаем 4\/20/)).toBeInTheDocument();
    expect(screen.getByText(/Состояние контура/i)).toBeInTheDocument();
    expect(screen.getByTestId("shadow-few-observations")).toHaveTextContent(/Мало наблюдений/i);
  });

  it("prefers Realism V2 arms and shows skip reasons in Russian", async () => {
    mockHappyPath({ withV2: true });
    renderPage();
    expect(await screen.findByTestId("shadow-experiment-v2")).toHaveTextContent(/Realism V2/i);
    expect(screen.getByTestId("shadow-legacy-v1")).toBeInTheDocument();
    expect(await screen.findByTestId("shadow-skipped-reasons")).toHaveTextContent(
      /Не хватает денег даже на один лот/i,
    );
    expect(screen.getByTestId("shadow-cash-card")).toHaveTextContent(/Стратегический резерв/i);
    expect(screen.getByTestId("shadow-pending-orders")).toHaveTextContent(/6×100=600/);
  });

  it("shows updates disabled status without red market-closed panic", async () => {
    mockLive({
      intraday_enabled: false,
      portfolios: [
        {
          ...portfolioA,
          intraday_enabled: false,
          live: { cash: 1_000_000, market_value: 0, nav: 1_000_000, positions: [] },
          pending_order_reasons: [],
        },
      ],
    });
    renderPage();
    expect(await screen.findByTestId("shadow-live-status")).toHaveTextContent(
      /Живые обновления выключены/i,
    );
    expect(screen.getByTestId("shadow-market-closed-calm")).toBeInTheDocument();
    expect(screen.queryByText(/ошибка эксперимента/i)).not.toBeInTheDocument();
  });

  it("shows live positions with lots, avg entry and stale badge", async () => {
    mockLive({
      intraday_enabled: true,
      portfolios: [
        {
          ...portfolioA,
          status: "ACTIVE",
          position_count: 1,
          pending_orders: 0,
          fills: 1,
          live_nav: 1_015_000,
          live: {
            cash: 500_000,
            market_value: 515_000,
            nav: 1_015_000,
            quote_coverage: 1,
            positions: [
              {
                instrument_id: 53,
                ticker: "MGNT",
                quantity: 600,
                lots: 6,
                lot_size: 100,
                avg_entry: 5000,
                mark_price: 5150,
                mark_source: "LAST",
                market_value: 515_000,
                unrealized_pnl: 15_000,
                freshness: "STALE",
                quote_time: "2026-09-07T06:00:00Z",
              },
            ],
          },
          pending_order_reasons: [],
        },
      ],
    });
    renderPage();
    expect(await screen.findByTestId("shadow-live-status")).toHaveTextContent(/Позиции открыты/i);
    const table = await screen.findByTestId("shadow-live-positions");
    expect(within(table).getByText("MGNT")).toBeInTheDocument();
    expect(within(table).getByText("6×100=600")).toBeInTheDocument();
    expect(within(table).getByTestId("stale-badge")).toHaveTextContent(/Устарела/i);
  });

  it("opens MGNT explanation without saying bought", async () => {
    renderPage();
    await expandResearchDetails();
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

  it("maps waiting status and A/B risk difference in research details", async () => {
    renderPage();
    await expandResearchDetails();
    expect(await screen.findByText(/Базовые ограничения риска/i)).toBeInTheDocument();
    expect(screen.getByText(/Активируется при просадке/i)).toBeInTheDocument();
    expect(screen.getAllByText(/защита от просадки/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Рейтинговый портфель/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/История NAV начнёт строиться/i)).toBeInTheDocument();
    expect(screen.getAllByText("SHADOW_HYSTERESIS_V1").length).toBeGreaterThanOrEqual(1);
  });
});
