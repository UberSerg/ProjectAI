import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as marketApi from "../api/market";
import { ToastProvider } from "../components/Toast";
import { MarketPage } from "./MarketPage";

vi.mock("../api/market");

function renderMarket() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <MarketPage />
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
          id: "1",
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
  });

  it("renders russian market table", async () => {
    renderMarket();
    expect(await screen.findByText("Рыночные данные")).toBeInTheDocument();
    expect(await screen.findByText("SBER")).toBeInTheDocument();
    expect(screen.getAllByText("Акция").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Обновить данные" })).toBeInTheDocument();
  });

  it("shows empty state", async () => {
    vi.mocked(marketApi.getInstruments).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 });
    renderMarket();
    expect(await screen.findByText("Рыночные данные ещё не загружены")).toBeInTheDocument();
  });

  it("shows reset filters when active", async () => {
    renderMarket();
    await screen.findByText("SBER");
    fireEvent.change(screen.getByPlaceholderText("По тикеру или названию"), { target: { value: "SBER" } });
    expect(await screen.findByText("Сбросить фильтры")).toBeInTheDocument();
  });
});
