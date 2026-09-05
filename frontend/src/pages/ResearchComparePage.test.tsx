import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as researchApi from "../api/researchLab";
import { HelpProvider } from "../help";
import { ResearchComparePage } from "./ResearchComparePage";

vi.mock("../api/researchLab");

describe("ResearchComparePage", () => {
  it("shows fair badge, differences, holdout warning", async () => {
    vi.mocked(researchApi.compareResearchRuns).mockResolvedValue({
      runs: [
        {
          id: 1,
          status: "SUCCESS",
          segment: "DEVELOPMENT_OOS",
          date_from: "2020-01-01",
          date_to: "2024-12-31",
          metrics: { total_price_return: 0.1, max_drawdown: -0.2, turnover_ratio: 4 },
          research: { display_name: "A", observed_holdout: false, launchable_again: true },
        },
        {
          id: 2,
          status: "SUCCESS",
          segment: "FINAL_HOLDOUT",
          date_from: "2020-01-01",
          date_to: "2024-12-31",
          metrics: { total_price_return: -0.05, max_drawdown: -0.3, turnover_ratio: 6 },
          research: { display_name: "B", observed_holdout: true, launchable_again: false },
        },
      ],
      fair_comparison: false,
      fair_badge: "Условия различаются",
      differences: [{ field: "segment", human: "Сегмент прогнозов", values: { 1: "DEVELOPMENT_OOS", 2: "FINAL_HOLDOUT" } }],
      metrics_table: [
        {
          metric_id: "total_price_return",
          human_label: "Доходность",
          help_id: "sim_cagr",
          values: { "1": 0.1, "2": -0.05 },
        },
      ],
      interpretation: ["У эксперимента A выше оборот, чем у B."],
      observed_holdout_warning: "HOLDOUT уже наблюдался.",
      cost_family: { present: false, message: "Для этого сравнения нет полного набора сценариев издержек." },
      nav_series: { "1": [], "2": [] },
      normalization: "start_100",
      period_aligned: false,
    } as never);

    render(
      <HelpProvider>
        <MemoryRouter initialEntries={["/research/compare?runs=1,2"]}>
          <Routes>
            <Route path="/research/compare" element={<ResearchComparePage />} />
          </Routes>
        </MemoryRouter>
      </HelpProvider>,
    );

    expect(await screen.findByTestId("fair-badge")).toHaveTextContent(/различаются/i);
    expect(screen.getByTestId("holdout-warning")).toBeInTheDocument();
    expect(screen.getByText(/Сегмент прогнозов/)).toBeInTheDocument();
    expect(screen.getByTestId("enrich-cash-hurdle")).toBeInTheDocument();
    expect(screen.getByTestId("enrich-excess-cash")).toBeInTheDocument();
  });

  it("shows pure model comparison badge when only candidate differs", async () => {
    vi.mocked(researchApi.compareResearchRuns).mockResolvedValue({
      runs: [
        {
          id: 1,
          status: "SUCCESS",
          candidate_config_hash: "aaa",
          date_from: "2020-01-01",
          date_to: "2024-01-01",
          metrics: { total_price_return: 0.1 },
          research: { display_name: "V0", observed_holdout: false, launchable_again: true },
        },
        {
          id: 2,
          status: "SUCCESS",
          candidate_config_hash: "bbb",
          date_from: "2020-01-01",
          date_to: "2024-01-01",
          metrics: { total_price_return: 0.05 },
          research: { display_name: "V1", observed_holdout: false, launchable_again: true },
        },
      ],
      fair_comparison: true,
      fair_badge: "Сопоставимые условия",
      model_comparison: true,
      differences: [],
      metrics_table: [],
      interpretation: [],
      cost_family: { present: false, message: "" },
      nav_series: { "1": [], "2": [] },
      period_aligned: true,
    } as never);

    render(
      <HelpProvider>
        <MemoryRouter initialEntries={["/research/compare?runs=1,2"]}>
          <Routes>
            <Route path="/research/compare" element={<ResearchComparePage />} />
          </Routes>
        </MemoryRouter>
      </HelpProvider>,
    );

    expect(await screen.findByTestId("pure-model-badge")).toHaveTextContent(/Чистое сравнение моделей/);
  });
});
