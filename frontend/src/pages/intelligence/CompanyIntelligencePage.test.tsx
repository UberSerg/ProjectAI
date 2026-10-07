import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
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
});
