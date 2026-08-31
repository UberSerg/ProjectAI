import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as analyticsApi from "../api/analytics";
import * as workflowsApi from "../api/workflows";
import { ToastProvider } from "../components/Toast";
import { AnalyticsPage } from "./AnalyticsPage";

vi.mock("../api/analytics");
vi.mock("../api/workflows");

function renderAnalyticsPage() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <AnalyticsPage />
      </ToastProvider>
    </MemoryRouter>,
  );
}

describe("AnalyticsPage", () => {
  it("renders overview metrics", async () => {
    vi.mocked(analyticsApi.getAnalyticsOverview).mockResolvedValue({
      active_feature_set: {
        id: "1",
        code: "basic_daily",
        version: 1,
        parameters: {},
        is_active: true,
        description: "V1",
      },
      instruments_active: 43,
      instruments_with_features: 40,
      instrument_feature_rows: 12000,
      latest_calculated_date: "2026-08-28",
      last_feature_run: null,
      quality: { valid: 11800, invalid: 0, warnings: 12 },
    });
    vi.mocked(analyticsApi.getFeatureRuns).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([]);

    renderAnalyticsPage();
    expect(await screen.findByText("basic_daily v1")).toBeInTheDocument();
    expect(screen.getByText("40 / 43")).toBeInTheDocument();
  });

  it("shows empty runs state", async () => {
    vi.mocked(analyticsApi.getAnalyticsOverview).mockResolvedValue({
      active_feature_set: null,
      instruments_active: 0,
      instruments_with_features: 0,
      instrument_feature_rows: 0,
      last_feature_run: null,
      quality: { valid: 0, invalid: 0, warnings: 0 },
    });
    vi.mocked(analyticsApi.getFeatureRuns).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([]);

    renderAnalyticsPage();
    expect(await screen.findByText("Расчётов пока нет")).toBeInTheDocument();
  });
});
