import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MarketPage } from "./MarketPage";

const mocks = vi.hoisted(() => ({
  getInstruments: vi.fn(),
  runMarketUpdate: vi.fn(),
  runBackfill: vi.fn(),
  runDataQuality: vi.fn(),
}));

vi.mock("../api/market", () => mocks);

function renderPage() {
  return render(<MemoryRouter><MarketPage /></MemoryRouter>);
}

describe("MarketPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders an empty market table state", async () => {
    mocks.getInstruments.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 });
    renderPage();
    expect(await screen.findByText("No instruments match the current filters.")).toBeInTheDocument();
  });

  it("renders a market table error", async () => {
    mocks.getInstruments.mockRejectedValue(new Error("market offline"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("market offline");
  });
});
