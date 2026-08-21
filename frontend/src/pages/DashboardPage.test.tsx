import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";

const mocks = vi.hoisted(() => ({
  getSystemHealth: vi.fn(),
  getMarketSummary: vi.fn(),
  getInstruments: vi.fn(),
  getBatches: vi.fn(),
  getDataQualityIssues: vi.fn(),
  getWorkflows: vi.fn(),
}));

vi.mock("../api/system", () => ({ getSystemHealth: mocks.getSystemHealth }));
vi.mock("../api/market", () => ({
  getMarketSummary: mocks.getMarketSummary,
  getInstruments: mocks.getInstruments,
  getBatches: mocks.getBatches,
  getDataQualityIssues: mocks.getDataQualityIssues,
}));
vi.mock("../api/workflows", () => ({ getWorkflows: mocks.getWorkflows }));

describe("DashboardPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders loading state", () => {
    mocks.getSystemHealth.mockReturnValue(new Promise(() => undefined));
    mocks.getMarketSummary.mockReturnValue(new Promise(() => undefined));
    mocks.getWorkflows.mockReturnValue(new Promise(() => undefined));
    render(<DashboardPage />);
    expect(screen.getByText("Loading dashboard metrics…")).toBeInTheDocument();
  });

  it("renders error state", async () => {
    mocks.getSystemHealth.mockRejectedValue(new Error("network down"));
    mocks.getMarketSummary.mockRejectedValue(new Error("network down"));
    mocks.getInstruments.mockRejectedValue(new Error("network down"));
    mocks.getBatches.mockRejectedValue(new Error("network down"));
    mocks.getDataQualityIssues.mockRejectedValue(new Error("network down"));
    mocks.getWorkflows.mockRejectedValue(new Error("network down"));
    render(<DashboardPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("network down");
  });
});
