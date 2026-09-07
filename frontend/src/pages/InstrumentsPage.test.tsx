import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HelpProvider } from "../help";
import { getPageHelp } from "../help/registry";
import { InstrumentCatalogDetailPage, InstrumentsPage } from "./InstrumentsPage";

vi.mock("../api/instruments", () => ({
  searchCatalogInstruments: vi.fn(),
  getCatalogInstrument: vi.fn(),
  getInstrumentMasterSyncStatus: vi.fn(),
  triggerInstrumentMasterSync: vi.fn(),
}));

import * as instrumentsApi from "../api/instruments";

describe("Instruments catalog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(instrumentsApi.getInstrumentMasterSyncStatus).mockResolvedValue({
      id: 1,
      status: "SUCCESS",
      started_at: "2026-09-07T10:00:00+00:00",
      finished_at: "2026-09-07T10:05:00+00:00",
      report: { created: 2, updated: 5, deactivated: 0 },
    });
    vi.mocked(instrumentsApi.searchCatalogInstruments).mockResolvedValue({
      items: [
        {
          id: 1,
          symbol: "SBER",
          name: "Сбербанк",
          asset_class: "equity",
          instrument_subtype: "equity_common",
          support_level: "FULL",
          primary_board: "TQBR",
          exchange: "MOEX",
          currency: "RUB",
          isin: null,
          is_active: true,
          sources: ["MOEX"],
        },
      ],
      total: 1,
      page: 1,
      page_size: 25,
    });
    vi.mocked(instrumentsApi.getCatalogInstrument).mockResolvedValue({
      id: 1,
      symbol: "SBER",
      name: "Сбербанк",
      asset_class: "equity",
      instrument_subtype: "equity_common",
      support_level: "FULL",
      primary_board: "TQBR",
      exchange: "MOEX",
      currency: "RUB",
      isin: "RU0009029540",
      is_active: true,
      first_seen_at: null,
      last_seen_at: null,
      research_member: true,
      capabilities: {
        can_live_quote: true,
        can_portfolio_value: true,
        can_predict: true,
        can_fundamental: true,
        can_fixed_income_analyze: false,
        can_rebalance: true,
        can_cashflow_project: false,
        reasons: {},
      },
      coverage: {
        live_quote: true,
        portfolio_value: true,
        predict: true,
        fundamental: true,
        fixed_income: false,
        rebalance: true,
        cashflow: false,
      },
      sources: [],
    });
  });

  it("shows sync cards and search results", async () => {
    render(
      <MemoryRouter>
        <HelpProvider>
          <InstrumentsPage />
        </HelpProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("instrument-sync-cards")).toBeInTheDocument();
    expect(await screen.findByTestId("instruments-table")).toBeInTheDocument();
    expect(screen.getByText("SBER")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("instruments-search"), { target: { value: "SBER" } });
    await waitFor(() =>
      expect(instrumentsApi.searchCatalogInstruments).toHaveBeenCalledWith(
        expect.objectContaining({ search: "SBER" }),
        expect.anything(),
      ),
    );
  });

  it("renders coverage matrix on detail", async () => {
    render(
      <MemoryRouter initialEntries={["/instruments/SBER"]}>
        <HelpProvider>
          <Routes>
            <Route path="/instruments/:secid" element={<InstrumentCatalogDetailPage />} />
          </Routes>
        </HelpProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("coverage-matrix")).toBeInTheDocument();
    expect(screen.getByText(/Что Kraken умеет/i)).toBeInTheDocument();
  });

  it("registers catalog page help", () => {
    expect(getPageHelp("instruments_catalog")?.about).toMatch(/каталог/i);
    expect(getPageHelp("instruments_catalog")?.about).toMatch(/не означает/i);
  });
});
