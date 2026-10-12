import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as intelligenceApi from "../../api/intelligence";
import { CompanyIntelligencePage } from "./CompanyIntelligencePage";
import { SignalStateBadge } from "./SignalStateBadge";

vi.mock("../../api/intelligence");

const sampleSnapshot: intelligenceApi.IntelligenceSnapshot = {
  schema: "IntelligenceSnapshotV1",
  instrument_id: 42,
  symbol: "SBER",
  name: "Sberbank",
  as_of: "2026-10-01",
  generated_at: "2026-10-07T10:00:00+00:00",
  freshness: "STALE_OR_UNWIRED",
  coverage: [
    { domain: "technical", status: "UNKNOWN", detail: "model_collector_not_integrated" },
    { domain: "risk", status: "UNKNOWN", detail: "UNKNOWN" },
  ],
  signals: [
    {
      model_id: "TechnicalModelV1",
      model_version: "1",
      semantic: "TECHNICAL",
      instrument_id: 42,
      as_of: "2026-10-01",
      horizon: "unspecified",
      state: "UNKNOWN",
      abstain_reason: "model_collector_not_integrated",
    },
    {
      model_id: "FundamentalModelV1",
      model_version: "1",
      semantic: "FUNDAMENTAL",
      instrument_id: 42,
      as_of: "2026-10-01",
      horizon: "unspecified",
      state: "UNKNOWN",
      abstain_reason: "model_collector_not_integrated",
    },
  ],
  committee: {
    as_of: "2026-10-01",
    instrument_id: 42,
    advisory_state: "ABSTAIN",
    independent_model_votes: [],
    blockers: ["no_integrated_independent_models"],
    data_gaps: ["signal_unavailable:TechnicalModelV1"],
    what_would_change_decision: ["wire_at_least_one_non_unknown_signal"],
    committee_policy_version: "committee_policy_v1_predeclared",
  },
  risk: {
    as_of: "2026-10-01",
    instrument_id: 42,
    risk_state: "UNKNOWN",
    risk_flags: ["risk_module_not_integrated"],
  },
  fundamentals_summary: { status: "UNKNOWN", issuer_kind: "UNKNOWN" },
  macro_summary: { status: "UNKNOWN" },
  recent_events: [],
  knowledge_evaluations: [],
  intraday_summary: { coverage_status: "UNKNOWN", interval: "60m", bars_used: 0 },
  limitations: ["advisory_research_only", "unknown_is_not_neutral"],
  production_isolation: { persist_registry: false, broker_execution: false },
};

function renderPage(path = "/intelligence") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <CompanyIntelligencePage />
    </MemoryRouter>,
  );
}

describe("SignalStateBadge", () => {
  it("renders UNKNOWN and NEUTRAL with distinct classes", () => {
    const { rerender } = render(<SignalStateBadge state="UNKNOWN" testId="state" />);
    expect(screen.getByTestId("state")).toHaveClass("intel-state-unknown");
    expect(screen.getByTestId("state")).not.toHaveClass("intel-state-neutral");
    rerender(<SignalStateBadge state="NEUTRAL" testId="state" />);
    expect(screen.getByTestId("state")).toHaveClass("intel-state-neutral");
    expect(screen.getByTestId("state")).not.toHaveClass("intel-state-unknown");
  });
});

describe("CompanyIntelligencePage", () => {
  beforeEach(() => {
    vi.mocked(intelligenceApi.getIntelligenceSnapshot).mockReset();
    vi.mocked(intelligenceApi.refreshIntelligence).mockReset();
  });

  it("shows empty prompt without instrument id", () => {
    renderPage();
    expect(screen.getByTestId("company-intelligence-page")).toBeInTheDocument();
    expect(screen.getByText(/Укажите instrument_id/i)).toBeInTheDocument();
  });

  it("loads snapshot sections without accuracy or winner language", async () => {
    vi.mocked(intelligenceApi.getIntelligenceSnapshot).mockResolvedValue(sampleSnapshot);
    renderPage("/intelligence?instrument_id=42&as_of=2026-10-01");

    expect(await screen.findByTestId("intel-identity")).toBeInTheDocument();
    expect(screen.getByText("SBER")).toBeInTheDocument();
    expect(screen.getByTestId("intel-advisory-state")).toHaveAttribute("data-state", "ABSTAIN");
    expect(screen.getByTestId("intel-risk-state")).toHaveAttribute("data-state", "UNKNOWN");
    expect(screen.getByTestId("intel-models")).toBeInTheDocument();
    expect(screen.getByTestId("intel-what-would-change")).toHaveTextContent(
      "wire_at_least_one_non_unknown_signal",
    );
    expect(screen.getByTestId("intel-coverage")).toBeInTheDocument();

    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/accuracy|winner|AI certainty|production-ready/i);
  });

  it("submits lookup form", async () => {
    vi.mocked(intelligenceApi.getIntelligenceSnapshot).mockResolvedValue(sampleSnapshot);
    renderPage();
    fireEvent.change(screen.getByTestId("intel-instrument-id"), { target: { value: "42" } });
    fireEvent.click(screen.getByRole("button", { name: /Загрузить/i }));
    await waitFor(() => {
      expect(intelligenceApi.getIntelligenceSnapshot).toHaveBeenCalled();
    });
  });

  it("labels refresh as a product action without stub wording", async () => {
    vi.mocked(intelligenceApi.getIntelligenceSnapshot).mockResolvedValue(sampleSnapshot);
    renderPage("/intelligence?instrument_id=42&as_of=2026-10-01");

    const button = await screen.findByRole("button", { name: "Обновить данные" });
    expect(button).toBeEnabled();
    expect(button).toHaveTextContent("Обновить данные");
    expect(button.textContent ?? "").not.toMatch(/stub/i);
    expect(document.body.textContent ?? "").not.toMatch(/stub/i);
  });

  it("clicking refresh forces a live fetch and reloads the snapshot", async () => {
    const refreshed: intelligenceApi.IntelligenceSnapshot = {
      ...sampleSnapshot,
      freshness: "FRESH",
      generated_at: "2026-10-07T12:00:00+00:00",
    };
    let releaseRefresh: (value: intelligenceApi.IntelligenceRefreshResult) => void = () => {};
    const refreshGate = new Promise<intelligenceApi.IntelligenceRefreshResult>((resolve) => {
      releaseRefresh = resolve;
    });
    vi.mocked(intelligenceApi.getIntelligenceSnapshot)
      .mockResolvedValueOnce(sampleSnapshot)
      .mockResolvedValueOnce(refreshed);
    vi.mocked(intelligenceApi.refreshIntelligence).mockReturnValue(refreshGate);

    renderPage("/intelligence?instrument_id=42&as_of=2026-10-01");
    const button = await screen.findByRole("button", { name: "Обновить данные" });
    expect(screen.getByText("STALE_OR_UNWIRED")).toBeInTheDocument();

    fireEvent.click(button);

    await waitFor(() => {
      expect(button).toBeDisabled();
    });
    expect(screen.getByTestId("intel-refresh-note")).toHaveTextContent("Обновление данных…");
    expect(screen.getByText("SBER")).toBeInTheDocument();
    expect(screen.getByText("STALE_OR_UNWIRED")).toBeInTheDocument();
    expect(intelligenceApi.refreshIntelligence).toHaveBeenCalledTimes(1);
    expect(intelligenceApi.refreshIntelligence).toHaveBeenCalledWith(42, {
      as_of: "2026-10-01",
      force: true,
    });
    expect(intelligenceApi.getIntelligenceSnapshot).toHaveBeenCalledTimes(1);

    releaseRefresh({
      status: "COMPLETED",
      accepted: true,
      instrument_id: 42,
      as_of: "2026-10-01",
      message: "Данные обновлены",
    });

    await waitFor(() => {
      expect(intelligenceApi.getIntelligenceSnapshot).toHaveBeenCalledTimes(2);
    });
    expect(intelligenceApi.getIntelligenceSnapshot).toHaveBeenLastCalledWith(42, "2026-10-01");
    expect(await screen.findByText("FRESH")).toBeInTheDocument();
    expect(screen.queryByText("STALE_OR_UNWIRED")).not.toBeInTheDocument();
    expect(screen.getByTestId("intel-refresh-note")).toHaveTextContent("Данные обновлены");
    expect(screen.getByRole("button", { name: "Обновить данные" })).toBeEnabled();
  });

  it("failed refresh does not replace the loaded snapshot", async () => {
    vi.mocked(intelligenceApi.getIntelligenceSnapshot).mockResolvedValue(sampleSnapshot);
    vi.mocked(intelligenceApi.refreshIntelligence).mockRejectedValue(new Error("source unavailable"));

    renderPage("/intelligence?instrument_id=42&as_of=2026-10-01");
    expect(await screen.findByText("SBER")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Обновить данные" }));

    expect(await screen.findByTestId("intel-refresh-note")).toHaveTextContent("source unavailable");
    expect(screen.getByText("SBER")).toBeInTheDocument();
    expect(screen.getByText("STALE_OR_UNWIRED")).toBeInTheDocument();
    expect(screen.getByTestId("intel-identity")).toBeInTheDocument();
    expect(intelligenceApi.getIntelligenceSnapshot).toHaveBeenCalledTimes(1);
    expect(intelligenceApi.refreshIntelligence).toHaveBeenCalledWith(42, {
      as_of: "2026-10-01",
      force: true,
    });
  });

  it("renders negative and unknown events without styling unknown as neutral", async () => {
    const withEvents: intelligenceApi.IntelligenceSnapshot = {
      ...sampleSnapshot,
      freshness: "PARTIAL",
      fundamentals_summary: {
        status: "PARTIAL",
        issuer_kind: "BANK_FI",
        provider: "cbr_forms",
        period_end: "2026-06-30",
        metrics: { NET_PROFIT: 1200, EQUITY: 800 },
        missing_metrics: ["NIM"],
        limitations: ["bank_metrics_partial"],
      },
      macro_summary: {
        status: "PARTIAL",
        regimes: { rates: "RESTRICTIVE" },
        observations: { key_rate: { value: 16 } },
        sources: ["cbr"],
      },
      committee: {
        ...sampleSnapshot.committee!,
        advisory_state: "HOLD",
        confidence: 0.42,
        confidence_semantic: "AGREEMENT",
        disagreement_score: 0.2,
        primary_drivers: ["event:EARNINGS"],
        counterarguments: ["risk_flags"],
        data_gaps: ["macro_partial"],
      },
      signals: [
        {
          ...sampleSnapshot.signals[0],
          state: "NEGATIVE",
          score: -0.4,
          confidence: 0.5,
          confidence_semantic: "EVIDENCE_COMPLETENESS",
          limitations: ["thin_history"],
        },
      ],
      recent_events: [
        {
          evidence_role: "extracted_event",
          event_type: "EARNINGS",
          materiality: "HIGH",
          direction: "NEGATIVE",
          published_at: "2026-09-28T08:00:00+00:00",
          known_at: "2026-09-28T09:00:00+00:00",
          provider: "interfax",
          title: "SBER profit drop",
          source_document_id: 7,
          mapping_basis: "ticker_exact",
        },
        {
          evidence_role: "extracted_event",
          event_type: "OTHER",
          materiality: "UNKNOWN",
          direction: "UNKNOWN",
          published_at: "2026-09-20T08:00:00+00:00",
          known_at: "2026-09-20T09:00:00+00:00",
          provider: "moex",
          title: "Unclear filing",
          source_document_id: 8,
          mapping_basis: "issuer_name",
        },
        {
          evidence_role: "extracted_event",
          event_type: "GUIDANCE",
          materiality: "LOW",
          direction: "ABSTAIN",
          published_at: "2026-09-10T08:00:00+00:00",
          known_at: "2026-09-10T09:00:00+00:00",
          provider: "moex",
          title: "No stance",
          source_document_id: 9,
          mapping_basis: "manual",
        },
        {
          evidence_role: "unscored_news",
          event_type: null,
          materiality: null,
          direction: null,
          provider: "interfax",
          title: "Bare headline",
          source_document_id: 10,
          mapping_basis: "headline_only",
        },
      ],
    };
    vi.mocked(intelligenceApi.getIntelligenceSnapshot).mockResolvedValue(withEvents);
    renderPage("/intelligence?instrument_id=42&as_of=2026-10-01");

    const negative = await screen.findByTestId("intel-event-direction-0");
    expect(negative).toHaveAttribute("data-state", "NEGATIVE");
    expect(negative).toHaveClass("intel-state-negative");
    expect(negative).not.toHaveClass("intel-state-neutral");
    expect(screen.getByTestId("intel-event-materiality-0")).toHaveTextContent("HIGH");
    expect(screen.getByTestId("intel-event-0")).toHaveTextContent("SBER profit drop");
    expect(screen.getByTestId("intel-event-0")).toHaveTextContent("ticker_exact");

    const unknown = screen.getByTestId("intel-event-direction-1");
    expect(unknown).toHaveAttribute("data-state", "UNKNOWN");
    expect(unknown).toHaveClass("intel-state-unknown");
    expect(unknown).not.toHaveClass("intel-state-neutral");

    const abstain = screen.getByTestId("intel-event-direction-2");
    expect(abstain).toHaveAttribute("data-state", "ABSTAIN");
    expect(abstain).toHaveClass("intel-state-abstain");
    expect(abstain).not.toHaveClass("intel-state-neutral");

    const unscored = screen.getByTestId("intel-event-3");
    expect(unscored).toHaveAttribute("data-evidence-role", "unscored_news");
    expect(screen.getByTestId("intel-event-direction-3")).toHaveAttribute("data-state", "UNSCORED");
    expect(screen.getByTestId("intel-event-direction-3")).toHaveTextContent("не оценено");
    expect(unscored.querySelector(".intel-state-neutral")).toBeNull();
    expect(unscored).not.toHaveTextContent("NEUTRAL");

    expect(screen.getByTestId("intel-fundamentals")).toHaveTextContent("Bank fundamentals");
    expect(screen.getByTestId("intel-fundamentals")).toHaveTextContent("NET_PROFIT");
    expect(screen.getByTestId("intel-macro")).toHaveTextContent("RESTRICTIVE");
    expect(screen.getByTestId("intel-primary-drivers")).toHaveTextContent("event:EARNINGS");
    expect(screen.getByTestId("intel-committee-confidence-semantic")).toHaveTextContent("AGREEMENT");
    expect(screen.getByRole("button", { name: "Обновить данные" })).toBeEnabled();

    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/accuracy|probability of profit|AI certainty/i);
  });
});
