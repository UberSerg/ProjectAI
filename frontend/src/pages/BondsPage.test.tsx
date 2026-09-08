import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { BondsPage } from "./BondsPage";

vi.mock("../api/investment", () => ({
  getBondsCatalog: vi.fn(),
}));

import { getBondsCatalog } from "../api/investment";

describe("BondsPage catalog V2", () => {
  beforeEach(() => {
    vi.mocked(getBondsCatalog).mockResolvedValue({
      items: [
        {
          instrument_id: 1,
          symbol: "SU26238",
          name: "ОФЗ 26238",
          is_government_debt: true,
          bond_type: "Government",
          badges: [
            { id: "price", label: "Цена", state: "ready" },
            { id: "cashflow", label: "Выплаты", state: "ready" },
            { id: "government", label: "Государственный долг", state: "ready" },
          ],
          clean_price_percent: 98.5,
          master_only: false,
        },
        {
          instrument_id: 2,
          symbol: "CORP1",
          name: "Corp Bond",
          is_government_debt: false,
          bond_type: "Corporate",
          badges: [
            { id: "price", label: "Цена", state: "missing" },
            { id: "cashflow", label: "Выплаты", state: "missing" },
            { id: "credit", label: "Кредит", state: "source_not_ready" },
          ],
          master_only: true,
        },
      ],
      page: 1,
      page_size: 25,
      total: 2,
      summary: {
        active: 2,
        valuation_ready: 1,
        cashflow_ready: 1,
        credit_ready: 0,
        ofz: 1,
        corporate: 1,
      },
      catalog_version: "bonds_v2",
    });
  });

  it("renders summary cards, badges and pagination", async () => {
    render(
      <MemoryRouter>
        <BondsPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("bonds-catalog-v2")).toBeInTheDocument();
    });
    expect(screen.getByTestId("bonds-summary-cards")).toBeInTheDocument();
    expect(screen.getAllByText("ОФЗ / госдолг").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Государственный долг")).toBeInTheDocument();
    expect(screen.getByTestId("bonds-pagination")).toBeInTheDocument();
    expect(screen.getByTestId("bond-row-SU26238")).toBeInTheDocument();
  });
});
