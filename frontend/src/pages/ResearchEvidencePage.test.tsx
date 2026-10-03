import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import * as evidenceApi from "../api/researchEvidence";
import type { ResearchEvidenceOverview } from "../api/researchEvidence";
import { HelpProvider } from "../help";
import { KrakenRoleProvider } from "../role/KrakenRoleContext";
import { ROLE_STORAGE_KEY } from "../role/types";
import { ResearchEvidencePage } from "./ResearchEvidencePage";

vi.mock("../api/researchEvidence");

const fullOverview: ResearchEvidenceOverview = {
  experiment: {
    id: "exp-v4-1",
    name: "Dataset V4 evidence",
    purpose: "Проверить, даёт ли V4 устойчивый OOS-сигнал без смешения с prospective.",
    checking: ["PIT=0", "Rank IC по семьям моделей"],
  },
  dataset: {
    universe_v3: 180,
    universe_v4: 176,
    labels: ["forward_return_20d"],
    feature_count_v3: 40,
    feature_count_v4: 62,
    sample_identity_match: true,
    pit_violations: 0,
    fund_coverage: 0.72,
    event_coverage: 0.41,
    current_only_share: 0.18,
    bank_fi_unsupported: 12,
    total_return_status: "incomplete",
  },
  historical_models: {
    regression: { family: "regression", rank_ic: 0.041, spread: 0.012, n: 420, consistent: true },
    ranker: {
      family: "ranker",
      rank_ic: 0.055,
      spread: 0.02,
      n: 418,
      consistent: true,
      fold_year: [{ year: 2020, rank_ic: 0.05, spread: 0.02, n: 80 }],
    },
  },
  ablation: {
    rows: [
      { variant: "base", mean_oos_ic: 0.03, spread: 0.01, bootstrap_ci_low: 0.01, bootstrap_ci_high: 0.05, n: 400 },
      { variant: "fund", mean_oos_ic: 0.034, spread: 0.011, bootstrap_ci_low: 0.012, bootstrap_ci_high: 0.052, n: 400 },
      { variant: "events", mean_oos_ic: 0.031, spread: 0.01, bootstrap_ci_low: 0.01, bootstrap_ci_high: 0.05, n: 400 },
      { variant: "full_v4", mean_oos_ic: 0.038, spread: 0.012, bootstrap_ci_low: 0.015, bootstrap_ci_high: 0.058, n: 400 },
    ],
  },
  economics: {
    return_kind: "PRICE_RETURN",
    dividends: "excluded",
    benchmark: "IMOEX",
    scenarios: [
      { id: "gross", commission_bps: 0, total_return: 0.21, cagr: 0.04, max_drawdown: -0.32, turnover_ratio: 4.2, excess_vs_benchmark: 0.01 },
      { id: "net_10bps", commission_bps: 10, total_return: 0.18, cagr: 0.035, max_drawdown: -0.33, turnover_ratio: 4.2, excess_vs_benchmark: -0.01 },
      { id: "net_30bps", commission_bps: 30, total_return: 0.12, cagr: 0.02, max_drawdown: -0.35, turnover_ratio: 4.2, excess_vs_benchmark: -0.04 },
      { id: "net_50bps", commission_bps: 50, total_return: 0.06, cagr: 0.01, max_drawdown: -0.38, turnover_ratio: 4.2, excess_vs_benchmark: -0.07 },
    ],
  },
  prospective: { empty: true, n_observations: 0 },
  limitations: [],
};

function renderPage(role: "OWNER" | "USER" = "OWNER") {
  localStorage.setItem(ROLE_STORAGE_KEY, role);
  return render(
    <HelpProvider>
      <KrakenRoleProvider>
        <MemoryRouter initialEntries={["/research/evidence"]}>
          <Routes>
            <Route path="/research/evidence" element={<ResearchEvidencePage />} />
          </Routes>
        </MemoryRouter>
      </KrakenRoleProvider>
    </HelpProvider>,
  );
}

describe("ResearchEvidencePage", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(evidenceApi.getResearchEvidenceOverview).mockResolvedValue(fullOverview);
    vi.mocked(evidenceApi.getResearchEvidenceProspective).mockResolvedValue({
      empty: true,
      n_observations: 0,
    });
    vi.mocked(evidenceApi.getResearchEvidenceEconomics).mockResolvedValue(fullOverview.economics!);
  });

  it("shows research-only badges and never accuracy or production-ready wording", async () => {
    renderPage();
    expect(await screen.findByTestId("research-evidence-page")).toBeInTheDocument();
    expect(screen.getByText("Research Evidence Engine V1")).toBeInTheDocument();
    expect(screen.getByTestId("research-only-badge")).toHaveTextContent("RESEARCH ONLY");
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/overall_accuracy|master_score|kraken_score|production_readiness/i);
    expect(text).not.toMatch(/LIVE READY|PRODUCTION READY|AUTO TRADE/i);
    expect(text).not.toMatch(/\baccuracy\b/i);
    expect(text).not.toMatch(/WINNER/i);
    expect(text).toMatch(/Историческая OOS симуляция, не фактический счёт/);
    expect(text).toMatch(/PRICE_RETURN/);
  });

  it("keeps historical OOS and prospective visually separate", async () => {
    vi.mocked(evidenceApi.getResearchEvidenceProspective).mockResolvedValue({
      status: "ACTIVE",
      n_observations: 3,
      rank_ic: 0.01,
      observations: [{ as_of: "2026-09-01", n: 3, rank_ic: 0.01 }],
    });
    renderPage();
    expect(await screen.findByTestId("evidence-historical-oos")).toBeInTheDocument();
    expect(screen.getByTestId("evidence-regression")).toHaveTextContent("Regression");
    expect(screen.getByTestId("evidence-ranker")).toHaveTextContent("Ranker");
    const divider = screen.getByTestId("evidence-prospective-divider");
    expect(divider).toHaveTextContent("Проспективные наблюдения");
    expect(screen.getByTestId("evidence-prospective")).toHaveTextContent("Rank IC (prospective)");
    expect(screen.getByTestId("evidence-historical-oos")).not.toHaveTextContent("Проспективные наблюдения");
  });

  it("renders empty evidence without crashing", async () => {
    vi.mocked(evidenceApi.getResearchEvidenceOverview).mockResolvedValue({
      experiment: null,
      dataset: null,
      historical_models: { regression: null, ranker: null },
      ablation: null,
      economics: null,
      prospective: null,
      limitations: [],
    });
    vi.mocked(evidenceApi.getResearchEvidenceProspective).mockResolvedValue({ empty: true });
    renderPage();
    expect(await screen.findByText("Доказательства ещё не собраны")).toBeInTheDocument();
    expect(screen.getByTestId("evidence-limitations")).toHaveTextContent("Total Return неполный");
    expect(screen.getByTestId("evidence-prospective")).toHaveTextContent("Проспективных наблюдений пока нет");
  });

  it("shows a partial-evidence banner when some blocks are missing", async () => {
    vi.mocked(evidenceApi.getResearchEvidenceOverview).mockResolvedValue({
      experiment: { id: "exp-partial", name: "partial" },
      dataset: { universe_v4: 10, pit_violations: 0, partial: true },
      historical_models: { regression: null, ranker: null },
      ablation: { partial: true, rows: [] },
      economics: null,
      limitations: [],
    });
    renderPage();
    expect(await screen.findByTestId("evidence-partial")).toHaveTextContent(/Частичные доказательства/);
    expect(screen.getByTestId("evidence-dataset-card")).toBeInTheDocument();
  });

  it("renders structured API errors in Russian without [object Object]", async () => {
    vi.mocked(evidenceApi.getResearchEvidenceOverview).mockRejectedValue(
      new ApiError("Ошибка запроса (404)", 404, { detail: { message: "Эксперимент доказательств не найден" } }),
    );
    renderPage();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Эксперимент доказательств не найден");
    expect(alert.textContent).not.toContain("[object Object]");
  });

  it("hides the OWNER run control in USER presentation", async () => {
    renderPage("USER");
    await screen.findByTestId("research-evidence-page");
    expect(screen.queryByRole("button", { name: "Пересчитать доказательства" })).not.toBeInTheDocument();
  });

  it("lets OWNER request a run without dumping prediction rows", async () => {
    vi.mocked(evidenceApi.runResearchEvidence).mockResolvedValue({
      status: "queued",
      message: "Пересчёт поставлен в очередь.",
      experiment_id: "exp-v4-1",
    });
    renderPage("OWNER");
    await screen.findByRole("button", { name: "Пересчитать доказательства" });
    fireEvent.click(screen.getByRole("button", { name: "Пересчитать доказательства" }));
    await waitFor(() => {
      expect(screen.getByTestId("evidence-run-result")).toHaveTextContent("Пересчёт поставлен в очередь.");
    });
    expect(evidenceApi.runResearchEvidence).toHaveBeenCalled();
  });
});
