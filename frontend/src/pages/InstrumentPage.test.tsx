import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as marketApi from "../api/market";
import { InstrumentPage } from "./InstrumentPage";

vi.mock("../api/market");

describe("InstrumentPage", () => {
  it("renders instrument overview in russian", async () => {
    vi.mocked(marketApi.getInstrument).mockResolvedValue({
      id: "45",
      symbol: "LKOH",
      name: "Lukoil",
      asset_class: "equity",
      exchange: "MOEX",
      currency: "RUB",
      sources: ["MOEX"],
      first_timestamp: "2024-01-03T00:00:00Z",
      last_timestamp: "2026-08-20T00:00:00Z",
      records_count: 670,
      is_active: true,
      last_close: 7000,
      mappings: [{ source: "MOEX", source_symbol: "LKOH" }],
    });
    vi.mocked(marketApi.getCandles).mockResolvedValue([
      { timestamp: "2026-08-19T00:00:00Z", open: 1, high: 2, low: 1, close: 1.5, volume: 10 },
      { timestamp: "2026-08-20T00:00:00Z", open: 1.5, high: 2, low: 1.4, close: 1.8, volume: 12 },
    ]);
    vi.mocked(marketApi.getBatches).mockResolvedValue([]);
    vi.mocked(marketApi.getDataQualityIssues).mockResolvedValue([]);

    render(
      <MemoryRouter initialEntries={["/market/instruments/45"]}>
        <Routes>
          <Route path="/market/instruments/:instrumentId" element={<InstrumentPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Lukoil")).toBeInTheDocument();
    expect(screen.getAllByText("LKOH").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Обзор" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Котировки" })).toBeInTheDocument();
  });

  it("does not crash when detail API omits sources", async () => {
    vi.mocked(marketApi.getInstrument).mockResolvedValue({
      id: "44",
      symbol: "SBER",
      name: "Sberbank",
      asset_class: "equity",
      exchange: "MOEX",
      currency: "RUB",
      first_timestamp: "2024-01-03T00:00:00Z",
      last_timestamp: "2026-08-20T00:00:00Z",
      records_count: 670,
      is_active: true,
      last_close: 280,
      mappings: [{ source: "MOEX", source_symbol: "SBER" }],
    } as marketApi.Instrument);
    vi.mocked(marketApi.getCandles).mockResolvedValue([]);
    vi.mocked(marketApi.getBatches).mockResolvedValue([]);
    vi.mocked(marketApi.getDataQualityIssues).mockResolvedValue([]);

    render(
      <MemoryRouter initialEntries={["/market/instruments/44"]}>
        <Routes>
          <Route path="/market/instruments/:instrumentId" element={<InstrumentPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Sberbank")).toBeInTheDocument();
    expect(screen.getAllByText("MOEX").length).toBeGreaterThan(0);
  });
});
