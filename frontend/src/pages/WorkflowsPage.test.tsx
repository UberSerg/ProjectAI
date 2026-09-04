import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as researchCycleApi from "../api/researchCycle";
import * as workflowsApi from "../api/workflows";
import { HelpProvider } from "../help";
import { WorkflowsPage } from "./WorkflowsPage";

vi.mock("../api/workflows");
vi.mock("../api/researchCycle");

const operationalBase = {
  health: "IN_SYNC",
  health_human: "Контур синхронизирован",
  watermarks: {
    raw_market_latest_date: "2026-09-03",
    forward_latest_as_of: "2026-09-03",
    forward_latest_batch_id: 7,
    shadow_portfolios: [
      { id: 1, status: "WAITING_FOR_FUTURE_MARKET_OPEN", last_processed_market_date: "2026-09-02" },
    ],
    forward_outcome_latest_status: "PENDING",
  },
  latest_cycle: {
    id: 42,
    name: "DAILY_RESEARCH_CYCLE_V0",
    status: "NO_CHANGES",
    started_at: "2026-09-04T18:30:00Z",
    finished_at: "2026-09-04T18:30:12Z",
    error: null,
    market_watermark_before: "2026-09-02",
    market_watermark_after: "2026-09-03",
    latest_forward_batch_id: 7,
    duration_seconds: 12,
    step_results: {
      RELATIONS_V2: { status: "SKIPPED_NOT_DUE" },
      CORPORATE_ACTION_UPDATE: { status: "NO_CHANGES" },
    },
  },
  schedule: { enabled: false, hour: 18, minute: 30, timezone: "UTC" },
  outcome_maturity: {
    batch_id: 7,
    as_of: "2026-09-03",
    future_trading_observations: 3,
    required: 20,
    status: "Ожидаем",
    matured: false,
  },
  automatic_schedule: "disabled" as const,
};

function mockResearchCycle() {
  vi.mocked(researchCycleApi.getResearchCycleLatest).mockResolvedValue({
    run: {
      id: "42",
      name: "DAILY_RESEARCH_CYCLE_V0",
      workflow_type: "DAILY_RESEARCH_CYCLE_V0",
      status: "NO_CHANGES",
      started_at: "2026-09-04T18:30:00Z",
      finished_at: "2026-09-04T18:30:12Z",
      error: null,
      meta: {
        duration_seconds: 12,
        step_results: {
          RELATIONS_V2: { status: "SKIPPED_NOT_DUE" },
          CORPORATE_ACTION_UPDATE: { status: "NO_CHANGES" },
          MARKET_UPDATE: { status: "SUCCESS" },
        },
      },
      steps: [
        { name: "MARKET_UPDATE", status: "SUCCESS" },
        { name: "CORPORATE_ACTION_UPDATE", status: "SUCCESS" },
        { name: "RELATIONS_V2", status: "SUCCESS" },
      ],
    },
    operational: operationalBase,
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <HelpProvider>
        <WorkflowsPage />
      </HelpProvider>
    </MemoryRouter>,
  );
}

describe("WorkflowsPage", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockResearchCycle();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("shows research cycle card with human statuses", async () => {
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("Ежедневный исследовательский цикл")).toBeInTheDocument();
    expect(screen.getAllByText(/Контур синхронизирован/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Без изменений/i).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByText(/Шаги цикла/));
    expect(await screen.findByText("Обновление рынка")).toBeInTheDocument();
    expect(screen.getByText("Корпоративные действия")).toBeInTheDocument();
    expect(screen.getAllByText(/не требовалось/i).length).toBeGreaterThan(0);
  });

  it("shows human readable workflow names and steps", async () => {
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([
      {
        id: "9",
        name: "backfill",
        workflow_type: "MarketDataBackfill",
        status: "WARNING",
        started_at: "2026-08-21T10:00:00Z",
        finished_at: "2026-08-21T10:00:33Z",
        duration_seconds: 33,
        error: null,
        steps: [
          { name: "Download MOEX", status: "SUCCESS" },
          { name: "Run Data Quality", status: "WARNING" },
        ],
      },
    ]);

    renderPage();

    expect((await screen.findAllByText("Загрузка истории котировок")).length).toBeGreaterThan(0);
    expect(screen.getByText("Получение данных MOEX")).toBeInTheDocument();
    expect(screen.getByText("Проверка качества")).toBeInTheDocument();
  });

  it("updates details when selecting another workflow", async () => {
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
        steps: [{ name: "Finish", status: "SUCCESS" }],
      },
      {
        id: "2",
        name: "dq",
        workflow_type: "DataQualityCheck",
        status: "WARNING",
        started_at: "2026-08-21T11:00:00Z",
        finished_at: "2026-08-21T11:00:02Z",
        duration_seconds: 2,
        error: null,
        steps: [{ name: "Run Data Quality", status: "WARNING" }],
      },
    ]);

    renderPage();

    expect((await screen.findAllByText("Обновление рыночных данных")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Проверка качества данных"));
    expect(await screen.findByText("DataQualityCheck")).toBeInTheDocument();
    expect(screen.getByText("Проверка качества")).toBeInTheDocument();
  });

  it("polls while RUNNING then stops after SUCCESS", async () => {
    const running = {
      id: "42",
      name: "update",
      workflow_type: "MarketDataUpdate",
      status: "RUNNING",
      started_at: "2026-08-30T10:00:00Z",
      finished_at: null,
      duration_seconds: null,
      error: null,
      steps: [{ name: "Download MOEX", status: "RUNNING" }],
    };
    const success = {
      ...running,
      status: "SUCCESS",
      finished_at: "2026-08-30T10:00:05Z",
      duration_seconds: 5,
      steps: [{ name: "Download MOEX", status: "SUCCESS" }],
    };

    const getWorkflows = vi
      .mocked(workflowsApi.getWorkflows)
      .mockResolvedValueOnce([running])
      .mockResolvedValueOnce([running])
      .mockResolvedValue([success]);

    renderPage();

    expect((await screen.findAllByText("Выполняется")).length).toBeGreaterThan(0);
    const callsAfterLoad = getWorkflows.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    await waitFor(() => expect(getWorkflows.mock.calls.length).toBeGreaterThan(callsAfterLoad));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect((await screen.findAllByText("Успешно")).length).toBeGreaterThan(0);

    const callsAfterSuccess = getWorkflows.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(getWorkflows.mock.calls.length).toBe(callsAfterSuccess);
  });
});
