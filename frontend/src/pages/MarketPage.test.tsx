import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as marketApi from "../api/market";
import { ToastProvider } from "../components/Toast";
import { InstrumentPage } from "./InstrumentPage";
import { MarketPage } from "./MarketPage";

vi.mock("../api/market");

function renderMarketApp(initial = "/market") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <ToastProvider>
        <Routes>
          <Route path="/market" element={<MarketPage />} />
          <Route path="/market/instruments/:instrumentId" element={<InstrumentPage />} />
          <Route path="/market/:instrumentId" element={<InstrumentPage />} />
        </Routes>
      </ToastProvider>
    </MemoryRouter>,
  );
}

describe("MarketPage", () => {
  beforeEach(() => {
    vi.mocked(marketApi.getMarketSummary).mockResolvedValue({
      instruments_count: 43,
      active_instruments_count: 43,
      records_count: 100,
      series_count: 5,
      batches_count: 1,
      dq_warnings: 0,
      dq_errors: 0,
      last_successful_update: "2026-08-20T00:00:00Z",
    });
    vi.mocked(marketApi.getInstruments).mockResolvedValue({
      items: [
        {
          id: "44",
          symbol: "SBER",
          name: "Sberbank",
          asset_class: "equity",
          exchange: "MOEX",
          currency: "RUB",
          sources: ["MOEX"],
          first_timestamp: "2024-01-03T00:00:00Z",
          last_timestamp: "2026-08-20T00:00:00Z",
          records_count: 670,
          is_active: true,
        },
      ],
      total: 1,
      page: 1,
      page_size: 25,
    });
    vi.mocked(marketApi.getInstrument).mockResolvedValue({
      id: "44",
      symbol: "SBER",
      name: "Sberbank",
      asset_class: "equity",
      exchange: "MOEX",
      currency: "RUB",
      sources: ["MOEX"],
      first_timestamp: "2024-01-03T00:00:00Z",
      last_timestamp: "2026-08-20T00:00:00Z",
      records_count: 670,
      is_active: true,
      last_close: 270.66,
      mappings: [],
    });
    vi.mocked(marketApi.getCandles).mockResolvedValue([]);
    vi.mocked(marketApi.getBatches).mockResolvedValue([]);
    vi.mocked(marketApi.getDataQualityIssues).mockResolvedValue([]);
  });

  it("renders russian market table", async () => {
    renderMarketApp();
    expect(await screen.findByText("Рыночные данные")).toBeInTheDocument();
    expect(await screen.findByText("SBER")).toBeInTheDocument();
    expect(screen.getAllByText("Акция").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Обновить данные" })).toBeInTheDocument();
    expect(screen.getByText("MOEX + ЦБ РФ")).toBeInTheDocument();
  });

  it("navigates to instrument page on row click", async () => {
    renderMarketApp();
    await screen.findByText("SBER");
    fireEvent.click(screen.getByRole("link", { name: "SBER, Sberbank" }));
    expect(await screen.findByText("Sberbank")).toBeInTheDocument();
    expect(marketApi.getInstrument).toHaveBeenCalledWith("44", expect.anything());
  });

  it("shows empty state", async () => {
    vi.mocked(marketApi.getInstruments).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 });
    renderMarketApp();
    expect(await screen.findByText("Рыночные данные ещё не загружены")).toBeInTheDocument();
  });

  it("shows reset filters when active", async () => {
    renderMarketApp();
    await screen.findByText("SBER");
    fireEvent.change(screen.getByPlaceholderText("По тикеру или названию"), { target: { value: "SBER" } });
    expect(await screen.findByText("Сбросить фильтры")).toBeInTheDocument();
  });
});
