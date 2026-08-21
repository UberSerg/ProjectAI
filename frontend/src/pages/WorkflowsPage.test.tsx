import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkflowsPage } from "./WorkflowsPage";

const mocks = vi.hoisted(() => ({
  getWorkflows: vi.fn(),
  getWorkflow: vi.fn(),
}));

vi.mock("../api/workflows", () => mocks);

describe("WorkflowsPage", () => {
  it("renders workflow history", async () => {
    mocks.getWorkflows.mockResolvedValue([
      {
        id: "wf-1",
        name: "Daily market update",
        workflow_type: "market_update",
        status: "succeeded",
        started_at: "2026-08-21T09:00:00Z",
        finished_at: "2026-08-21T09:05:00Z",
        error: null,
        steps: [],
      },
    ]);
    render(<WorkflowsPage />);
    expect(screen.getByRole("heading", { name: "Workflows" })).toBeInTheDocument();
    expect(await screen.findByText("Daily market update")).toBeInTheDocument();
  });
});
