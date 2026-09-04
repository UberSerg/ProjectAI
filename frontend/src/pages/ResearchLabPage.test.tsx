import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as researchApi from "../api/researchLab";
import { HelpProvider } from "../help";
import { ResearchLabPage } from "./ResearchLabPage";

vi.mock("../api/researchLab");

const options = {
  candidates: [
    {
      id: "prediction_ml_candidate/v0",
      candidate_name: "prediction_ml_candidate",
      candidate_version: "v0",
      human_name: "Модель прогнозирования V0",
      technical_line: "CatBoostRegressor · 20 trading days",
      research_verdict: "MIXED",
      model_type: "CatBoostRegressor",
      target_label: "forward_return_20d",
      eligible: true,
    },
  ],
  prediction_segments: [
    {
      id: "DEVELOPMENT_OOS",
      human_label: "Development OOS — исторические прогнозы вне обучающей выборки",
      launchable: true,
      date_from: "2017-02-01",
      date_to: "2026-01-05",
    },
    {
      id: "FINAL_HOLDOUT",
      human_label: "FINAL HOLDOUT — только просмотр",
      launchable: false,
      badge: "Уже наблюдавшийся holdout",
      explanation: "Уже использовался для оценки Candidate V0.",
    },
  ],
  policies: [
    {
      id: "RANK_LONG_ONLY_V0",
      technical_id: "RANK_LONG_ONLY_V0",
      human_name: "Базовая рейтинговая",
      description: "Top 20% equal weight",
      parameters: { top_quantile: 0.2 },
      frozen: true,
    },
    {
      id: "RANK_HYSTERESIS_LONG_ONLY_V1",
      technical_id: "RANK_HYSTERESIS_LONG_ONLY_V1",
      human_name: "Рейтинговая с удержанием",
      description: "entry 20 exit 35",
      parameters: { entry_quantile: 0.2, exit_quantile: 0.35 },
      frozen: true,
    },
  ],
  risk_policies: [
    {
      id: "RISK_GUARDRAILS_V0",
      technical_id: "RISK_GUARDRAILS_V0",
      human_name: "Базовые ограничения",
      description: "long only",
      parameters: { max_single_weight: 0.2 },
      frozen: true,
    },
  ],
  cost_presets: [
    { bps: 0, human_label: "0 bps — без издержек", preset: true },
    { bps: 10, human_label: "10 bps — умеренные условные издержки", preset: true },
  ],
  cost_custom: { allowed: true, min_bps: 0, max_bps: 100, human_label: "Пользовательский" },
  defaults: {
    candidate_id: "prediction_ml_candidate/v0",
    segment: "DEVELOPMENT_OOS",
    policy_id: "RANK_HYSTERESIS_LONG_ONLY_V1",
    risk_id: "RISK_GUARDRAILS_V0",
    commission_bps: 10,
    initial_capital: 1_000_000,
    date_from: "2017-02-01",
    date_to: "2026-01-05",
  },
  capital_bounds: { min: 10_000, max: 100_000_000 },
  execution_assumptions: {
    execution: "Next Open",
    fractional_shares: true,
    dividends: "excluded",
    benchmark: "IMOEX price index",
    no_leverage: true,
  },
  period_warnings: { short_calendar_days: 180 },
  holdout_start: "2026-01-01",
};

function renderLab() {
  return render(
    <HelpProvider>
      <MemoryRouter initialEntries={["/research"]}>
        <Routes>
          <Route path="/research" element={<ResearchLabPage />} />
        </Routes>
      </MemoryRouter>
    </HelpProvider>,
  );
}

describe("ResearchLabPage", () => {
  it("loads options, protects HOLDOUT, shows summary and registry", async () => {
    vi.mocked(researchApi.getResearchOptions).mockResolvedValue(options as never);
    vi.mocked(researchApi.listResearchRuns).mockResolvedValue([
      {
        id: 12,
        status: "SUCCESS",
        segment: "DEVELOPMENT_OOS",
        date_from: "2023-01-01",
        date_to: "2024-12-31",
        metrics: { total_price_return: 0.1, max_drawdown: -0.2, turnover_ratio: 5 },
        spec: {
          policy_name: "RANK_HYSTERESIS_LONG_ONLY_V1",
          risk_name: "RISK_GUARDRAILS_V0",
          commission_bps: 10,
        },
        research: { display_name: "Hysteresis · 10 bps", observed_holdout: false, launchable_again: true },
      },
    ] as never);

    renderLab();
    expect(await screen.findByText("Лаборатория")).toBeInTheDocument();
    expect(screen.getByTestId("research-not-live")).toBeInTheDocument();
    expect(screen.getByTestId("holdout-protected")).toBeInTheDocument();
    expect(screen.getByTestId("config-summary")).toHaveTextContent("Development OOS");
    expect(screen.getByText("Hysteresis · 10 bps")).toBeInTheDocument();
  });

  it("launches and shows reuse banner", async () => {
    vi.mocked(researchApi.getResearchOptions).mockResolvedValue(options as never);
    vi.mocked(researchApi.listResearchRuns).mockResolvedValue([]);
    vi.mocked(researchApi.launchResearchRun).mockResolvedValue({
      outcome: "REUSE_EXISTING",
      status: "REUSED",
      message: "Такой эксперимент уже существует.",
      simulation_executed: false,
      run: {
        id: 7,
        status: "SUCCESS",
        segment: "DEVELOPMENT_OOS",
        research: { display_name: "Existing", observed_holdout: false, launchable_again: true },
      },
    } as never);

    renderLab();
    await screen.findByText("Запустить эксперимент");
    fireEvent.click(screen.getByRole("button", { name: "Запустить эксперимент" }));
    await waitFor(() => {
      expect(screen.getByTestId("reuse-banner")).toHaveTextContent(/уже существует/i);
    });
    expect(researchApi.launchResearchRun).toHaveBeenCalled();
  });

  it("limits compare selection to 5", async () => {
    vi.mocked(researchApi.getResearchOptions).mockResolvedValue(options as never);
    vi.mocked(researchApi.listResearchRuns).mockResolvedValue(
      Array.from({ length: 6 }, (_, i) => ({
        id: i + 1,
        status: "SUCCESS",
        segment: "DEVELOPMENT_OOS",
        metrics: {},
        spec: { policy_name: "RANK_LONG_ONLY_V0", risk_name: "RISK_GUARDRAILS_V0", commission_bps: 0 },
        research: { display_name: `E${i + 1}`, observed_holdout: false, launchable_again: true },
      })) as never,
    );
    renderLab();
    await screen.findByText("E1");
    for (let i = 1; i <= 6; i += 1) {
      fireEvent.click(screen.getByLabelText(`Выбрать ${i}`));
    }
    expect(screen.getByRole("button", { name: /Сравнить \(5\)/ })).toBeInTheDocument();
  });
});