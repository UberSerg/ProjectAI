import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as relationsApi from "../api/relations";
import * as workflowsApi from "../api/workflows";
import { ToastProvider } from "../components/Toast";
import { RelationsPage } from "./RelationsPage";

vi.mock("../api/relations");
vi.mock("../api/workflows");

function renderRelationsPage() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <RelationsPage />
      </ToastProvider>
    </MemoryRouter>,
  );
}

describe("RelationsPage", () => {
  it("renders overview metrics", async () => {
    vi.mocked(relationsApi.getRelationsOverview).mockResolvedValue({
      active_relation_set: {
        id: "1",
        code: "basic_relations",
        version: 1,
        parameters: {},
        is_active: true,
        description: "V1",
      },
      inputs_active: 48,
      snapshots_total: 1200,
      latest_as_of_date: "2026-08-28",
      last_relation_run: null,
      quality: { valid: 1100, invalid: 100 },
    });
    vi.mocked(relationsApi.getRelationRuns).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(relationsApi.getRelationSnapshots).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([]);

    renderRelationsPage();
    expect(await screen.findByText("basic_relations v1")).toBeInTheDocument();
    expect(screen.getByText("48")).toBeInTheDocument();
  });

  it("shows empty relations state", async () => {
    vi.mocked(relationsApi.getRelationsOverview).mockResolvedValue({
      active_relation_set: null,
      inputs_active: 0,
      snapshots_total: 0,
      last_relation_run: null,
      quality: { valid: 0, invalid: 0 },
    });
    vi.mocked(relationsApi.getRelationRuns).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(relationsApi.getRelationSnapshots).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([]);

    renderRelationsPage();
    expect(await screen.findByText("Расчётов пока нет")).toBeInTheDocument();
  });
});
