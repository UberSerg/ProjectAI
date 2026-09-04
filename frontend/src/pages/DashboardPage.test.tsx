import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import * as marketApi from "../api/market";
import * as systemApi from "../api/system";
import * as workflowsApi from "../api/workflows";
import { DashboardPage } from "./DashboardPage";

vi.mock("../api/market");
vi.mock("../api/system");
vi.mock("../api/workflows");

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
  });

  it("renders russian overview metrics and real DB statuses", async () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Обзор")).toBeInTheDocument();
    expect(await screen.findByText("43")).toBeInTheDocument();
    expect(screen.getByText("Система работает нормально")).toBeInTheDocument();
    expect(screen.getByText("Основная БД")).toBeInTheDocument();
    expect(screen.getByText("База памяти")).toBeInTheDocument();
    expect(screen.getAllByText("Работает").length).toBeGreaterThanOrEqual(2);
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
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Рыночные данные")).toBeInTheDocument();
    expect(screen.getByText("Симуляции")).toBeInTheDocument();
    expect(screen.getByText("Процессы")).toBeInTheDocument();
    expect(screen.getAllByText("Скоро").length).toBeGreaterThan(0);
  });
});
