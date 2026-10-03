import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DatasetCard } from "./DatasetCard";
import { AblationTable } from "./AblationTable";
import { LimitationsList } from "./LimitationsList";
import { ProspectiveSection } from "./ProspectiveSection";
import { REQUIRED_LIMITATIONS } from "./constants";
import {
  ablationRows,
  isOverviewEmpty,
  isOverviewPartial,
  isProspectiveEmpty,
  mergeLimitations,
} from "./format";

describe("researchEvidence format helpers", () => {
  it("treats a blank overview as empty and a one-sided payload as partial", () => {
    expect(isOverviewEmpty({})).toBe(true);
    expect(
      isOverviewPartial({
        experiment: { id: "x" },
        dataset: { universe_v4: 1 },
        historical_models: { regression: null, ranker: null },
      }),
    ).toBe(true);
  });

  it("always keeps the required limitation codes", () => {
    const merged = mergeLimitations([]);
    expect(merged.map((row) => row.code)).toEqual(REQUIRED_LIMITATIONS.map((row) => row.code));
  });

  it("fills ablation variants without inventing a winner", () => {
    const rows = ablationRows({ rows: [{ variant: "base", mean_oos_ic: 0.02 }] });
    expect(rows.map((r) => r.label)).toEqual(["Base", "+Fund", "+Events", "Full V4"]);
  });

  it("does not treat missing prospective as historical data", () => {
    expect(isProspectiveEmpty(null)).toBe(true);
    expect(isProspectiveEmpty({ n_observations: 0 })).toBe(true);
  });
});

describe("DatasetCard", () => {
  it("shows V3/V4 universe, PIT=0 and Total Return status", () => {
    render(
      <DatasetCard
        dataset={{
          universe_v3: 100,
          universe_v4: 98,
          labels: ["forward_return_20d"],
          pit_violations: 0,
          sample_identity_match: true,
          total_return_status: "incomplete",
          current_only_share: 0.2,
        }}
      />,
    );
    expect(screen.getByTestId("evidence-dataset-card")).toHaveTextContent("Universe V3");
    expect(screen.getByTestId("evidence-dataset-card")).toHaveTextContent("PIT-нарушения");
    expect(screen.getByTestId("evidence-dataset-card")).toHaveTextContent("0");
    expect(screen.getByTestId("evidence-dataset-card")).toHaveTextContent("неполный");
    expect(screen.getByTestId("evidence-dataset-card").textContent).not.toMatch(/accuracy/i);
  });
});

describe("AblationTable", () => {
  it("renders Base/+Fund/+Events/Full V4 without a WINNER badge", () => {
    render(
      <AblationTable
        ablation={{
          rows: [
            { variant: "full_v4", mean_oos_ic: 0.04, bootstrap_ci_low: 0.01, bootstrap_ci_high: 0.06 },
          ],
        }}
      />,
    );
    expect(screen.getByTestId("ablation-row-base")).toHaveTextContent("Base");
    expect(screen.getByTestId("ablation-row-fund")).toHaveTextContent("+Fund");
    expect(screen.getByTestId("ablation-row-events")).toHaveTextContent("+Events");
    expect(screen.getByTestId("ablation-row-full_v4")).toHaveTextContent("Full V4");
    expect(screen.getByTestId("evidence-ablation").textContent).not.toMatch(/WINNER/i);
  });
});

describe("LimitationsList", () => {
  it("lists the required data constraints", () => {
    render(<LimitationsList limitations={[]} />);
    expect(screen.getByTestId("limitation-TR_INCOMPLETE")).toBeInTheDocument();
    expect(screen.getByTestId("limitation-DIVIDENDS_EXCLUDED")).toBeInTheDocument();
    expect(screen.getByTestId("limitation-BANK_FI_PARTIAL")).toBeInTheDocument();
    expect(screen.getByTestId("limitation-DELISTED_PARTIAL")).toBeInTheDocument();
    expect(screen.getByTestId("limitation-CURRENT_ONLY_WEAKER")).toBeInTheDocument();
    expect(screen.getByTestId("limitation-FRACTIONAL_SIZING")).toBeInTheDocument();
    expect(screen.getByTestId("limitation-ASSUMED_COSTS")).toBeInTheDocument();
    expect(screen.getByTestId("limitation-NO_AUTO_CANDIDATE_PROMOTION")).toBeInTheDocument();
  });
});

describe("ProspectiveSection", () => {
  it("uses a visual divider and empty copy instead of blending history", () => {
    render(<ProspectiveSection prospective={null} />);
    expect(screen.getByTestId("evidence-prospective-divider")).toHaveTextContent(
      "Проспективные наблюдения",
    );
    expect(screen.getByText(/не смешиваются с историческим OOS/i)).toBeInTheDocument();
  });
});
