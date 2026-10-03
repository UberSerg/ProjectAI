import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CampaignHistoryList } from "./CampaignHistoryList";
import { DataQualityCard } from "./DataQualityCard";
import { PrimaryEconomicsCard } from "./PrimaryEconomicsCard";
import { RealOosTable } from "./RealOosTable";
import { RobustnessMatrix } from "./RobustnessMatrix";
import { StabilityTables } from "./StabilityTables";
import {
  isDossierEmpty,
  oosRows,
  sortCampaignsNewestFirst,
} from "./campaignFormat";
import { NO_DATA_LABEL, PRIMARY_CONTRACT_LABEL } from "./constants";

describe("campaign format helpers", () => {
  it("treats an empty dossier as empty and does not invent a winner", () => {
    expect(isDossierEmpty({ empty: true })).toBe(true);
    expect(isDossierEmpty({})).toBe(true);
    const rows = oosRows({ rows: [{ variant: "full_v4", rank_ic: 0.04 }] });
    expect(rows.map((row) => row.label)).toEqual(["BASE", "FUND", "EVENTS", "V4 FULL"]);
  });

  it("sorts campaigns newest first by created_at", () => {
    const sorted = sortCampaignsNewestFirst({
      items: [
        { fingerprint: "old", created_at: "2026-01-01T00:00:00Z", date_from: "2022-04-01", date_to: "2024-01-01", status: "COMPLETE" },
        { fingerprint: "new", created_at: "2026-10-01T00:00:00Z", date_from: "2022-04-01", date_to: "2025-01-01", status: "RUNNING" },
      ],
    });
    expect(sorted.map((row) => row.fingerprint)).toEqual(["new", "old"]);
  });
});

describe("DataQualityCard", () => {
  it("shows нет данных for missing fields instead of 0", () => {
    render(<DataQualityCard quality={{ pit_status: { missing: true } }} />);
    expect(screen.getByTestId("data-quality-fund")).toHaveTextContent(NO_DATA_LABEL);
    expect(screen.getByTestId("data-quality-events")).toHaveTextContent(NO_DATA_LABEL);
    expect(screen.getByTestId("data-quality-issuer")).toHaveTextContent(NO_DATA_LABEL);
    expect(screen.getByTestId("data-quality-fund").textContent).not.toMatch(/^0$|0 %/);
    expect(screen.getByTestId("campaign-data-quality").textContent).not.toMatch(/accuracy/i);
  });
});

describe("RealOosTable", () => {
  it("renders BASE/FUND/EVENTS/V4 FULL without a WINNER badge", () => {
    render(
      <RealOosTable
        oos={{
          rows: [
            { variant: "base", rank_ic: 0.02, spread: 0.01, n: 100, ci_low: 0.0, ci_high: 0.04 },
            { variant: "full_v4", rank_ic: 0.03, spread: 0.01, n: 100, ci_low: 0.01, ci_high: 0.05 },
          ],
        }}
      />,
    );
    expect(screen.getByTestId("oos-row-base")).toHaveTextContent("BASE");
    expect(screen.getByTestId("oos-row-fund")).toHaveTextContent("FUND");
    expect(screen.getByTestId("oos-row-events")).toHaveTextContent("EVENTS");
    expect(screen.getByTestId("oos-row-full_v4")).toHaveTextContent("V4 FULL");
    expect(screen.getByTestId("campaign-oos").textContent).not.toMatch(/WINNER/i);
  });
});

describe("PrimaryEconomicsCard", () => {
  it("labels PRIMARY RESEARCH CONTRACT 20 / top 20 / 30bps", () => {
    render(
      <PrimaryEconomicsCard
        contract={{
          rebalance_sessions: 20,
          selection_top_pct: 20,
          cost_bps_per_side: 30,
          cumulative_price_return: 0.1,
        }}
      />,
    );
    expect(screen.getByTestId("campaign-primary-economics")).toHaveTextContent(PRIMARY_CONTRACT_LABEL);
    expect(screen.getByTestId("primary-contract-spec")).toHaveTextContent("20 sessions");
    expect(screen.getByTestId("primary-contract-spec")).toHaveTextContent("top 20%");
    expect(screen.getByTestId("primary-contract-spec")).toHaveTextContent("30 bps");
  });
});

describe("RobustnessMatrix", () => {
  it("switches cost without highlighting the maximum return cell", () => {
    render(
      <RobustnessMatrix
        matrix={{
          cells: [
            { rebalance_sessions: 20, selection_top_pct: 20, cost_bps: 0, total_return: 0.5 },
            { rebalance_sessions: 10, selection_top_pct: 10, cost_bps: 0, total_return: 0.9 },
            { rebalance_sessions: 20, selection_top_pct: 20, cost_bps: 30, total_return: 0.12 },
          ],
        }}
      />,
    );
    fireEvent.click(screen.getByTestId("robustness-cost-0"));
    const maxCell = screen.getByTestId("robustness-cell-10-10-0");
    const primaryAt0 = screen.getByTestId("robustness-cell-20-20-0");
    expect(maxCell.getAttribute("data-max-highlight")).toBe("false");
    expect(maxCell.className).not.toMatch(/max|winner/i);
    expect(primaryAt0.getAttribute("data-primary")).toBe("false");
    fireEvent.click(screen.getByTestId("robustness-cost-30"));
    expect(screen.getByTestId("robustness-cell-20-20-30").getAttribute("data-primary")).toBe("true");
    expect(screen.getByTestId("robustness-cell-20-20-30")).toHaveClass("robustness-cell-primary");
  });
});

describe("StabilityTables", () => {
  it("renders compact year/fold/identity/activity tables", () => {
    render(
      <StabilityTables
        stability={{
          years: [{ year: 2023, rank_ic: 0.02, n: 40 }],
          folds: [{ fold: "fold-1", rank_ic: 0.01, n: 20 }],
          identity_basis: [{ key: "DATED_WINDOW", label: "DATED_WINDOW", rank_ic: 0.03, n: 10 }],
          activity: [{ key: "inactive", label: "historical inactive", rank_ic: 0.0, n: 5 }],
        }}
      />,
    );
    expect(screen.getByTestId("stability-years")).toHaveTextContent("2023");
    expect(screen.getByTestId("stability-folds")).toHaveTextContent("fold-1");
    expect(screen.getByTestId("stability-identity")).toHaveTextContent("DATED_WINDOW");
    expect(screen.getByTestId("stability-activity")).toHaveTextContent("historical inactive");
  });
});

describe("CampaignHistoryList", () => {
  it("lists fingerprint, window and status", () => {
    render(
      <CampaignHistoryList
        campaigns={[
          {
            fingerprint: "abc123def456",
            fingerprint_short: "abc123",
            date_from: "2022-04-01",
            date_to: "2025-09-01",
            status: "COMPLETE",
          },
        ]}
        selected="abc123def456"
        onSelect={() => undefined}
      />,
    );
    expect(screen.getByTestId("campaign-row-abc123def456")).toHaveTextContent("abc123");
    expect(screen.getByTestId("campaign-row-abc123def456")).toHaveTextContent("2022-04-01");
    expect(screen.getByTestId("campaign-row-abc123def456")).toHaveTextContent("COMPLETE");
  });
});
