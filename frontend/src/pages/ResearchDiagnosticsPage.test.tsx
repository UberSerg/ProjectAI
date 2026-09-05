import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as modelEdgeApi from "../api/modelEdge";
import * as researchApi from "../api/researchLab";
import { HelpProvider } from "../help";
import { ResearchDiagnosticsPage } from "./ResearchDiagnosticsPage";
import { ResearchExperimentPage } from "./ResearchExperimentPage";
import { ResearchProspectiveModelsPage } from "./ResearchProspectiveModelsPage";

vi.mock("../api/modelEdge", async () => {
  const actual = await vi.importActual<typeof import("../api/modelEdge")>("../api/modelEdge");
  return {
    ...actual,
    getDiagnosticsSummary: vi.fn(),
    getDiagnosticsTopTail: vi.fn(),
    getDiagnosticsStability: vi.fn(),
    getDiagnosticsRegimes: vi.fn(),
    getDiagnosticsDisagreements: vi.fn(),
    getEconomicViability: vi.fn(),
    getProspectiveLatest: vi.fn(),
    listProspectiveBatches: vi.fn(),
    getProspectiveBatch: vi.fn(),
    getProspectiveEvaluation: vi.fn(),
  };
});
vi.mock("../api/researchLab");

describe("ResearchDiagnosticsPage", () => {
  beforeEach(() => {
    vi.mocked(modelEdgeApi.getDiagnosticsSummary).mockResolvedValue({
      models: {
        v0: { rank_ic: 0.05, cagr: 0.04, max_drawdown: -0.3, excess_vs_cash: -0.06 },
        v1: { rank_ic: 0.06, cagr: 0.02, max_drawdown: -0.35, excess_vs_cash: -0.08 },
      },
      conclusion: "V1 лучше упорядочивает список, но V0 исторически дал выше результат портфеля.",
      learned: ["Факт 1"],
    });
    vi.mocked(modelEdgeApi.getDiagnosticsTopTail).mockResolvedValue({
      rows: [{ quantile: 0.2, v0_realized_return: 0.01, v1_realized_return: -0.01 }],
    });
    vi.mocked(modelEdgeApi.getDiagnosticsStability).mockResolvedValue({
      week_to_week_correlation: 0.4,
    });
    vi.mocked(modelEdgeApi.getDiagnosticsRegimes).mockResolvedValue({ rows: [] });
    vi.mocked(modelEdgeApi.getDiagnosticsDisagreements).mockResolvedValue({
      dates: ["2024-01-08"],
      as_of: "2024-01-08",
      rows: [],
    });
    vi.mocked(modelEdgeApi.getEconomicViability).mockResolvedValue({
      annual_rate: 0.1,
      models: { v0: { cagr: 0.04, max_drawdown: -0.3 } },
    });
  });

  it("renders diagnostics route, Rank IC explanation and economic section", async () => {
    render(
      <HelpProvider>
        <MemoryRouter initialEntries={["/research/diagnostics?hurdle=0.10"]}>
          <Routes>
            <Route path="/research/diagnostics" element={<ResearchDiagnosticsPage />} />
          </Routes>
        </MemoryRouter>
      </HelpProvider>,
    );

    expect(await screen.findByText("Почему модели дают такой результат?")).toBeInTheDocument();
    expect(screen.getByTestId("rank-ic-vs-portfolio")).toHaveTextContent(/верхнюю часть рейтинга/i);
    expect(screen.getByTestId("main-conclusion")).toHaveTextContent(/V1 лучше/i);
    expect(screen.getByTestId("diagnostics-economic")).toHaveTextContent(/Стоил ли риск результата/i);
    expect(screen.getByTestId("what-we-learned")).toBeInTheDocument();
  });
});

describe("ResearchProspectiveModelsPage", () => {
  it("shows proud empty state when no batches", async () => {
    vi.mocked(modelEdgeApi.getProspectiveLatest).mockResolvedValue({
      status: "ACTIVE",
      activated_at: "2026-09-05T10:00:00Z",
      batch_count: 0,
      pipeline: { experiment_activated: true },
      portfolio_a: { nav: 1_000_000, cash: 1_000_000 },
      portfolio_b: { nav: 1_000_000, cash: 1_000_000 },
    });
    vi.mocked(modelEdgeApi.listProspectiveBatches).mockResolvedValue([]);
    vi.mocked(modelEdgeApi.getProspectiveEvaluation).mockResolvedValue({
      mature_dates: 0,
      sample_maturity: "TOO_EARLY",
    });

    render(
      <HelpProvider>
        <MemoryRouter initialEntries={["/research/prospective-models"]}>
          <Routes>
            <Route path="/research/prospective-models" element={<ResearchProspectiveModelsPage />} />
          </Routes>
        </MemoryRouter>
      </HelpProvider>,
    );

    expect(await screen.findByTestId("prospective-empty-proud")).toHaveTextContent(
      /Эксперимент запущен/i,
    );
    expect(screen.getByTestId("sample-maturity")).toHaveTextContent(/Слишком рано/i);
    expect(screen.getByTestId("prospective-pipeline")).toBeInTheDocument();
  });

  it("does not show V1 ranking score as percent", async () => {
    vi.mocked(modelEdgeApi.getProspectiveLatest).mockResolvedValue({
      status: "ACTIVE",
      batch_count: 1,
      pipeline: {
        experiment_activated: true,
        new_market_data: true,
        paired_predictions: true,
      },
      agreement: { rank_correlation: 0.55, top20_overlap: 0.4 },
    });
    vi.mocked(modelEdgeApi.listProspectiveBatches).mockResolvedValue([
      { id: 9, as_of_date: "2026-09-08", status: "SUCCESS" },
    ]);
    vi.mocked(modelEdgeApi.getProspectiveEvaluation).mockResolvedValue({ mature_dates: 0 });
    vi.mocked(modelEdgeApi.getProspectiveBatch).mockResolvedValue({
      id: 9,
      as_of_date: "2026-09-08",
      predictions: [
        {
          ticker: "SBER",
          v0_expected_return: 0.012,
          v0_rank: 1,
          v1_ranking_score: 0.8731,
          v1_rank: 2,
          v0_selected: true,
          v1_selected: true,
        },
      ],
    });

    render(
      <HelpProvider>
        <MemoryRouter initialEntries={["/research/prospective-models"]}>
          <Routes>
            <Route path="/research/prospective-models" element={<ResearchProspectiveModelsPage />} />
          </Routes>
        </MemoryRouter>
      </HelpProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("v1-ranking-score")).toBeInTheDocument();
    });
    const scoreCell = screen.getByTestId("v1-ranking-score");
    expect(scoreCell.textContent).toMatch(/0\.8731/);
    expect(scoreCell.textContent).not.toMatch(/%/);
    expect(screen.getByTestId("v0-expected-return").textContent).toMatch(/%/);
  });
});

describe("ResearchExperimentPage economic section", () => {
  it("shows cash hurdle block without implying simulation mutation", async () => {
    vi.mocked(researchApi.getResearchRun).mockResolvedValue({
      id: 42,
      status: "SUCCESS",
      segment: "DEVELOPMENT_OOS",
      date_from: "2020-01-01",
      date_to: "2024-12-31",
      metrics: { total_price_return: 0.2, max_drawdown: -0.25, cagr: 0.037 },
      spec: { policy_name: "RANK_HYSTERESIS_LONG_ONLY_V1", commission_bps: 10 },
      research: { display_name: "Exp", observed_holdout: false, launchable_again: true },
    } as never);

    render(
      <HelpProvider>
        <MemoryRouter initialEntries={["/research/42?hurdle=0.10"]}>
          <Routes>
            <Route path="/research/:runId" element={<ResearchExperimentPage />} />
          </Routes>
        </MemoryRouter>
      </HelpProvider>,
    );

    expect(await screen.findByTestId("experiment-economic")).toBeInTheDocument();
    expect(screen.getByTestId("experiment-economic")).toHaveTextContent(/не меняет симуляцию/i);
    expect(screen.getByTestId("experiment-economic-conclusion")).toBeInTheDocument();
  });
});
