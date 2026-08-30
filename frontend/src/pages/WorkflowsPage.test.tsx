import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as workflowsApi from "../api/workflows";
import { WorkflowsPage } from "./WorkflowsPage";

vi.mock("../api/workflows");

describe("WorkflowsPage", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
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

    render(
      <MemoryRouter>
        <WorkflowsPage />
      </MemoryRouter>,
    );

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

    render(
      <MemoryRouter>
        <WorkflowsPage />
      </MemoryRouter>,
    );

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

    render(
      <MemoryRouter>
        <WorkflowsPage />
      </MemoryRouter>,
    );

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
