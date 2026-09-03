import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as marketApi from "../api/market";
import { HelpProvider } from "../help";
import { InstrumentPage } from "./InstrumentPage";

vi.mock("../api/market");
vi.mock("../api/analytics", () => ({
  getInstrumentFeaturesLatest: vi.fn().mockResolvedValue(null),
  hasFeatureQualityWarning: () => false,
  hasInsufficientHistory: () => false,
}));
vi.mock("../api/technical", () => ({
  getInstrumentTechnicalLatest: vi.fn().mockResolvedValue(null),
}));

function renderInstrument(id = "44") {
  return render(
    <HelpProvider>
      <MemoryRouter initialEntries={[`/market/instruments/${id}`]}>
        <Routes>
          <Route path="/market/instruments/:instrumentId" element={<InstrumentPage />} />
        </Routes>
      </MemoryRouter>
    </HelpProvider>,
  );
}

describe("InstrumentPage quotes explorer", () => {
  it("shows range presets and keeps RAW semantics on quotes tab", async () => {
    vi.mocked(marketApi.getInstrument).mockResolvedValue({
      id: "44",
      symbol: "SBER",
      name: "Sberbank",
      asset_class: "equity",
      exchange: "MOEX",
      currency: "RUB",
      sources: ["MOEX"],
      first_timestamp: "2015-01-15T00:00:00Z",
      last_timestamp: "2026-08-20T00:00:00Z",
      records_count: 2800,
      is_active: true,
      last_close: 280,
      mappings: [{ source: "MOEX", source_symbol: "SBER" }],
    });
    vi.mocked(marketApi.getCandles).mockImplementation(async (_id, query) => {
      const limit = typeof query === "number" ? query : query?.limit ?? 30;
      return Array.from({ length: Math.min(limit, 40) }, (_, index) => {
        const day = index + 1;
        const month = day > 28 ? "07" : "08";
        const dom = day > 28 ? day - 28 : day;
        return {
          timestamp: `2026-${month}-${String(dom).padStart(2, "0")}T00:00:00Z`,
          open: 100 + index,
          high: 101 + index,
          low: 99 + index,
          close: 100.5 + index,
          volume: 1000 + index,
          source: "MOEX",
        };
      });
    });
    vi.mocked(marketApi.getBatches).mockResolvedValue([]);
    vi.mocked(marketApi.getDataQualityIssues).mockResolvedValue([]);

    renderInstrument("44");
    expect(await screen.findByText("Sberbank")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Котировки" }));
    expect(await screen.findByRole("button", { name: "1Y" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "MAX" })).toBeInTheDocument();
    expect(screen.getByText(/RAW OHLCV/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "5Y" }));
    await waitFor(() => {
      expect(marketApi.getCandles).toHaveBeenCalled();
    });
  });

  it("shows empty history state for later-listed instrument without candles bounds", async () => {
    vi.mocked(marketApi.getInstrument).mockResolvedValue({
      id: "99",
      symbol: "YDEX",
      name: "Yandex",
      asset_class: "equity",
      exchange: "MOEX",
      currency: "RUB",
      sources: ["MOEX"],
      first_timestamp: null,
      last_timestamp: null,
      records_count: 0,
      is_active: true,
      last_close: null,
    });
    vi.mocked(marketApi.getCandles).mockResolvedValue([]);
    vi.mocked(marketApi.getBatches).mockResolvedValue([]);
    vi.mocked(marketApi.getDataQualityIssues).mockResolvedValue([]);

    renderInstrument("99");
    fireEvent.click(await screen.findByRole("button", { name: "Котировки" }));
    expect(await screen.findByText(/История котировок ещё не загружена/)).toBeInTheDocument();
  });
});
