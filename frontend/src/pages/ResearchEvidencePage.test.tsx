import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import * as evidenceApi from "../api/researchEvidence";
import type { EvidenceDossierV1, ResearchEvidenceOverview } from "../api/researchEvidence";
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

const sampleDossier: EvidenceDossierV1 = {
  identity: {
    campaign_version: "CanonicalEvidenceCampaignV1",
    fingerprint: "deadbeefcafebabe00112233",
    fingerprint_short: "deadbeefcafe",
    v3_run_id: 11,
    v4_run_id: 12,
    date_from: "2022-04-01",
    date_to: "2025-08-01",
    data_snapshot_hash: "snapsha256abc",
  },
  data_quality: {
    price_coverage: 0.91,
    pit_status: "PASS",
    v4_fundamental_coverage: { missing: true },
    event_coverage: { missing: true },
    issuer_identity_basis: { missing: true },
    bank_fi_unsupported: { missing: true },
    total_return_status: "incomplete",
  },
  historical_oos: {
    rows: [
      { variant: "base", rank_ic: 0.02, spread: 0.01, n: 200, ci_low: 0, ci_high: 0.04 },
      { variant: "fund", rank_ic: 0.022, spread: 0.01, n: 200, ci_low: -0.01, ci_high: 0.05 },
      { variant: "events", rank_ic: 0.021, spread: 0.01, n: 200, ci_low: -0.01, ci_high: 0.04 },
      { variant: "full_v4", rank_ic: 0.03, spread: 0.012, n: 200, ci_low: 0.01, ci_high: 0.05 },
    ],
  },
  stability: {
    years: [{ year: 2023, rank_ic: 0.02, n: 80 }],
    folds: [{ fold: "F1", rank_ic: 0.01, n: 40 }],
    identity_basis: [{ label: "CURRENT_ONLY", rank_ic: 0.01, n: 20 }],
    activity: [{ label: "active", rank_ic: 0.03, n: 50 }],
  },
  economics_primary: {
    rebalance_sessions: 20,
    selection_top_pct: 20,
    cost_bps_per_side: 30,
    cumulative_price_return: 0.08,
    benchmark_return: 0.05,
    max_drawdown: -0.2,
    turnover: 3.1,
    average_cash_weight: 0.12,
    unresolved_exits: 0,
  },
  economics_robustness: {
    cells: [
      { rebalance_sessions: 20, selection_top_pct: 20, cost_bps: 30, total_return: 0.08 },
      { rebalance_sessions: 10, selection_top_pct: 10, cost_bps: 0, total_return: 0.4 },
    ],
  },
  prospective: { empty: true },
  evidence_completeness: {
    data_integrity: "PARTIAL",
    historical_oos: "COMPLETE",
    economics: "COMPLETE",
    prospective: "EMPTY",
    owner_review_state: "EVIDENCE_DOSSIER_COMPLETE",
  },
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
    vi.mocked(evidenceApi.listResearchEvidenceCampaigns).mockResolvedValue({ items: [] });
    vi.mocked(evidenceApi.getResearchEvidenceCampaignDossier).mockResolvedValue({ empty: true });
    vi.mocked(evidenceApi.launchCanonicalEvidenceCampaignV1).mockResolvedValue({
      status: "queued",
      campaign_version: "CanonicalEvidenceCampaignV1",
    });
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
      empty: false,
      personal_decision_memory: {
        captures_total: 3,
        horizons: [
          {
            horizon_sessions: 20,
            matured_count: 3,
            pending_count: 0,
            unavailable_count: 0,
            status: "INSUFFICIENT_SAMPLE",
            price_return: { status: "INSUFFICIENT_SAMPLE" },
          },
        ],
      },
      forward_predictions: { freshness: { matured_count: 2, pending_count: 1 } },
    });
    renderPage();
    expect(await screen.findByTestId("evidence-historical-oos")).toBeInTheDocument();
    expect(screen.getByTestId("evidence-regression")).toHaveTextContent("Regression");
    expect(screen.getByTestId("evidence-ranker")).toHaveTextContent("Ranker");
    const divider = screen.getByTestId("evidence-prospective-divider");
    expect(divider).toHaveTextContent("Проспективные наблюдения");
    expect(screen.getByTestId("evidence-pdm")).toHaveTextContent("Personal Decision Memory");
    expect(screen.getByTestId("evidence-forward")).toHaveTextContent("Forward Predictions");
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
    expect(screen.queryByRole("button", { name: "Запустить каноническое исследование" })).not.toBeInTheDocument();
  });

  it("lets OWNER request an exact frozen rerun without dumping prediction rows", async () => {
    vi.mocked(evidenceApi.runResearchEvidence).mockResolvedValue({
      status: "queued",
      message: "Пересчёт поставлен в очередь.",
      experiment_id: "exp-v4-1",
    });
    renderPage("OWNER");
    const button = await screen.findByRole("button", { name: "Пересчитать доказательства" });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => {
      expect(screen.getByTestId("evidence-run-result")).toHaveTextContent("Пересчёт поставлен в очередь.");
    });
    expect(evidenceApi.runResearchEvidence).toHaveBeenCalledWith({ experiment_id: "exp-v4-1" });
  });

  it("disables OWNER rerun without an existing experiment", async () => {
    vi.mocked(evidenceApi.getResearchEvidenceOverview).mockResolvedValue({
      experiment: null,
      dataset: null,
      historical_models: { regression: null, ranker: null },
      ablation: null,
      economics: null,
      prospective: { empty: true },
      limitations: [],
    });
    renderPage("OWNER");
    const button = await screen.findByRole("button", { name: "Пересчитать доказательства" });
    expect(button).toBeDisabled();
    expect(screen.getByTestId("evidence-rerun-hint")).toHaveTextContent(
      /существующий эксперимент/,
    );
  });

  it("shows empty canonical dossier without crashing", async () => {
    renderPage();
    expect(await screen.findByText("Каноническое досье ещё не собрано")).toBeInTheDocument();
    expect(screen.getByTestId("campaign-history")).toBeInTheDocument();
  });

  it("lets OWNER launch CanonicalEvidenceCampaignV1 without a free-form universe", async () => {
    vi.mocked(evidenceApi.launchCanonicalEvidenceCampaignV1).mockResolvedValue({
      status: "queued",
      message: "Каноническое исследование поставлено в очередь.",
      fingerprint: "deadbeefcafebabe00112233",
      campaign_version: "CanonicalEvidenceCampaignV1",
    });
    vi.mocked(evidenceApi.listResearchEvidenceCampaigns)
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({
        items: [
          {
            fingerprint: "deadbeefcafebabe00112233",
            fingerprint_short: "deadbeefcafe",
            date_from: "2022-04-01",
            date_to: "2025-08-01",
            status: "RUNNING",
            created_at: "2026-10-03T00:00:00Z",
          },
        ],
      });
    vi.mocked(evidenceApi.getResearchEvidenceCampaignDossier).mockResolvedValue(sampleDossier);
    renderPage("OWNER");
    const button = await screen.findByRole("button", { name: "Запустить каноническое исследование" });
    fireEvent.click(button);
    await waitFor(() => {
      expect(evidenceApi.launchCanonicalEvidenceCampaignV1).toHaveBeenCalledWith({
        campaign_version: "CanonicalEvidenceCampaignV1",
        exact_rerun: null,
      });
    });
    expect(evidenceApi.launchCanonicalEvidenceCampaignV1).not.toHaveBeenCalledWith(
      expect.objectContaining({ instrument_ids: expect.anything() }),
    );
    expect(await screen.findByTestId("campaign-identity")).toHaveTextContent("CanonicalEvidenceCampaignV1");
    expect(screen.getByTestId("campaign-identity")).toHaveTextContent("deadbeefcafe");
    expect(screen.getByTestId("data-quality-fund")).toHaveTextContent("нет данных");
    expect(screen.getByTestId("campaign-primary-economics")).toHaveTextContent("PRIMARY RESEARCH CONTRACT");
    expect(screen.getByTestId("campaign-primary-economics")).toHaveTextContent("30 bps");
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/LIVE READY|PRODUCTION READY|WINNER/i);
    expect(text).not.toMatch(/\baccuracy\b/i);
  });

  it("shows existing campaign artifact and exact rerun with the same semantics", async () => {
    vi.mocked(evidenceApi.listResearchEvidenceCampaigns).mockResolvedValue({
      items: [
        {
          fingerprint: "deadbeefcafebabe00112233",
          fingerprint_short: "deadbeefcafe",
          date_from: "2022-04-01",
          date_to: "2025-08-01",
          status: "COMPLETE",
          created_at: "2026-10-02T00:00:00Z",
        },
        {
          fingerprint: "olderfp0001",
          date_from: "2022-04-01",
          date_to: "2024-01-01",
          status: "COMPLETE",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    });
    vi.mocked(evidenceApi.getResearchEvidenceCampaignDossier).mockResolvedValue(sampleDossier);
    renderPage("OWNER");
    expect(await screen.findByTestId("campaign-identity")).toHaveTextContent("V3 run");
    expect(screen.getByTestId("campaign-history").textContent).toMatch(/deadbeefcafe[\s\S]*olderfp0001|deadbeefcafe/);
    const rows = screen.getAllByRole("row");
    const bodyText = rows.map((row) => row.textContent).join(" | ");
    expect(bodyText.indexOf("deadbeefcafe")).toBeLessThan(bodyText.indexOf("olderfp0001"));
    const rerun = await screen.findByRole("button", { name: "Точный пересчёт с теми же семантиками" });
    fireEvent.click(rerun);
    await waitFor(() => {
      expect(evidenceApi.launchCanonicalEvidenceCampaignV1).toHaveBeenCalledWith({
        campaign_version: "CanonicalEvidenceCampaignV1",
        exact_rerun: true,
      });
    });
  });

  it("renders structured campaign dossier errors in Russian without [object Object]", async () => {
    vi.mocked(evidenceApi.listResearchEvidenceCampaigns).mockResolvedValue({
      items: [{ fingerprint: "broken-fp", status: "COMPLETE", created_at: "2026-10-03T00:00:00Z" }],
    });
    vi.mocked(evidenceApi.getResearchEvidenceCampaignDossier).mockRejectedValue(
      new ApiError("Ошибка запроса (404)", 404, { detail: { message: "Досье кампании не найдено" } }),
    );
    renderPage();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Досье кампании не найдено");
    expect(alert.textContent).not.toContain("[object Object]");
  });
});
