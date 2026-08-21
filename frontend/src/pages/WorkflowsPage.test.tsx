import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as workflowsApi from "../api/workflows";
import { WorkflowsPage } from "./WorkflowsPage";

vi.mock("../api/workflows");

describe("WorkflowsPage", () => {
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
});
