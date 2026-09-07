import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as investmentApi from "../api/investment";
import { HelpProvider } from "../help";
import { BondDetailPage } from "./BondDetailPage";

vi.mock("../api/investment", () => ({
  getBondDetail: vi.fn(),
  getBondAccountingPreview: vi.fn(),
}));

describe("BondDetailPage", () => {
  beforeEach(() => {
    vi.mocked(investmentApi.getBondDetail).mockResolvedValue({
      instrument_id: 1,
      symbol: "SU26238RMFS4",
      name: "ОФЗ 26238",
      bond_type: "OFZ",
      support_status: "SUPPORTED",
      credit_quality_status: "UNKNOWN",
      credit_status: "UNKNOWN",
      liquidity_status: "GOOD",
      investment_eligibility: "RESEARCH_ONLY",
      real_portfolio_eligible: false,
      clean_price_percent: 95.1,
      nkd: 12.3,
      dirty_estimate: 963.4,
      cashflows: [
        {
          cashflow_date: "2026-12-01",
          cashflow_type: "COUPON",
          amount: 35.5,
          currency: "RUB",
          source: "MOEX",
        },
      ],
      why_kraken_ru: "Поддержка учёта: SUPPORTED. Eligibility: RESEARCH_ONLY.",
      data_quality: { known_at_quality: "CURRENT_STATE_ONLY", source: "MOEX" },
    });
    vi.mocked(investmentApi.getBondAccountingPreview).mockResolvedValue({
      status: "READY",
      clean_total: 951,
      nkd_total: 12.3,
      dirty_purchase: 963.3,
      fees: 0.5,
      coupon_total: 100,
      redemption_total: 1000,
      total_return_before_tax: 136.7,
    });
  });

  it("renders bond detail from mock API and back link", async () => {
    render(
      <HelpProvider>
        <MemoryRouter initialEntries={["/bonds/SU26238RMFS4"]}>
          <Routes>
            <Route path="/bonds/:secid" element={<BondDetailPage />} />
          </Routes>
        </MemoryRouter>
      </HelpProvider>,
    );

    expect(await screen.findByTestId("bond-detail-page")).toBeInTheDocument();
    expect(screen.getByText(/ОФЗ 26238/)).toBeInTheDocument();
    expect(screen.getByTestId("bond-why-kraken")).toHaveTextContent(/SUPPORTED/);
    expect(screen.getByText("COUPON")).toBeInTheDocument();
    const back = screen.getAllByRole("link", { name: /К списку облигаций/i });
    expect(back[0]).toHaveAttribute("href", "/bonds");
  });
});
