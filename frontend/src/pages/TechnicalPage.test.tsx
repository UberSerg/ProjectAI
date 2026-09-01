import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as technicalApi from "../api/technical";
import * as workflowsApi from "../api/workflows";
import { ToastProvider } from "../components/Toast";
import { TechnicalPage } from "./TechnicalPage";

vi.mock("../api/technical");
vi.mock("../api/workflows");

function renderTechnicalPage() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <TechnicalPage />
      </ToastProvider>
    </MemoryRouter>,
  );
}

const emptyOverview: technicalApi.TechnicalOverview = {
  active_model: "rules_v1",
  technical_feature_set: "technical_daily v1",
  as_of: null,
  instruments_analyzed: 0,
  bullish: 0,
  neutral: 0,
  bearish: 0,
  invalid: 0,
  warnings: 0,
  last_run: null,
};

describe("TechnicalPage", () => {
  it("renders loading state", () => {
    vi.mocked(technicalApi.getTechnicalOverview).mockReturnValue(new Promise(() => {}));
    vi.mocked(technicalApi.getTechnicalRuns).mockReturnValue(new Promise(() => {}));
    vi.mocked(technicalApi.getTechnicalSignals).mockReturnValue(new Promise(() => {}));
    vi.mocked(workflowsApi.getWorkflows).mockReturnValue(new Promise(() => {}));

    renderTechnicalPage();
    expect(screen.getByText("Загрузка технического анализа…")).toBeInTheDocument();
  });

  it("renders error state", async () => {
    vi.mocked(technicalApi.getTechnicalOverview).mockRejectedValue(new Error("backend down"));
    vi.mocked(technicalApi.getTechnicalRuns).mockResolvedValue([]);
    vi.mocked(technicalApi.getTechnicalSignals).mockResolvedValue([]);
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([]);

    renderTechnicalPage();
    expect(await screen.findByText("backend down")).toBeInTheDocument();
  });

  it("renders overview state counters", async () => {
    vi.mocked(technicalApi.getTechnicalOverview).mockResolvedValue({
      ...emptyOverview,
      active_model: "rules_v1",
      technical_feature_set: "technical_daily v1",
      as_of: "2026-08-28",
      instruments_analyzed: 40,
      bullish: 12,
      neutral: 20,
      bearish: 8,
      invalid: 3,
    });
    vi.mocked(technicalApi.getTechnicalRuns).mockResolvedValue([]);
    vi.mocked(technicalApi.getTechnicalSignals).mockResolvedValue([]);
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([]);

    renderTechnicalPage();
    expect(await screen.findByText("rules_v1")).toBeInTheDocument();
    expect(screen.getByText("technical_daily v1")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows empty signals state", async () => {
    vi.mocked(technicalApi.getTechnicalOverview).mockResolvedValue(emptyOverview);
    vi.mocked(technicalApi.getTechnicalRuns).mockResolvedValue([]);
    vi.mocked(technicalApi.getTechnicalSignals).mockResolvedValue([]);
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([]);

    renderTechnicalPage();
    expect(await screen.findByText("Сигналов пока нет — запустите обновление или backfill.")).toBeInTheDocument();
    expect(screen.getByText("Расчётов пока нет")).toBeInTheDocument();
  });

  it("renders signal table rows", async () => {
    vi.mocked(technicalApi.getTechnicalOverview).mockResolvedValue({
      ...emptyOverview,
      as_of: "2026-08-28",
      bullish: 1,
      instruments_analyzed: 1,
    });
    vi.mocked(technicalApi.getTechnicalRuns).mockResolvedValue([]);
    vi.mocked(technicalApi.getTechnicalSignals).mockResolvedValue([
      {
        id: "1",
        instrument_id: "45",
        ticker: "LKOH",
        as_of_date: "2026-08-28",
        score: 0.42,
        confidence: 0.75,
        direction: "bullish",
        model_code: "rules_v1",
        model_version: 1,
        model_config_hash: "abc",
        factor_contributions: { trend: 0.2, momentum: 0.1, rsi: 0.05, volume: 0.07 },
        is_valid: true,
        quality_flags: {},
        rsi14: 58.2,
        sma20_distance: 0.03,
        ema20_distance: 0.02,
        atr14_pct: 0.015,
        volume_zscore_20d: 1.2,
      },
    ]);
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([]);

    renderTechnicalPage();
    expect(await screen.findByText("LKOH")).toBeInTheDocument();
    expect(screen.getAllByText("Бычье").length).toBeGreaterThan(0);
    expect(screen.getByText("0.42")).toBeInTheDocument();
  });

  it("passes filters to signals API", async () => {
    vi.mocked(technicalApi.getTechnicalOverview).mockResolvedValue(emptyOverview);
    vi.mocked(technicalApi.getTechnicalRuns).mockResolvedValue([]);
    vi.mocked(technicalApi.getTechnicalSignals).mockResolvedValue([]);
    vi.mocked(workflowsApi.getWorkflows).mockResolvedValue([]);

    renderTechnicalPage();
    await screen.findByText("Сигналов пока нет — запустите обновление или backfill.");

    expect(technicalApi.getTechnicalSignals).toHaveBeenCalledWith(
      expect.objectContaining({
        valid_only: true,
        limit: 100,
      }),
      expect.anything(),
    );
  });
});
