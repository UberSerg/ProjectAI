import { render, screen } from "@testing-library/react";
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
});
