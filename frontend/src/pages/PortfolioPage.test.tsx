import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PortfolioPage } from "./PortfolioPage";

const listPersonalPortfolios = vi.fn();
const getHubValuations = vi.fn();
const createPersonalPortfolio = vi.fn();
const deletePersonalPortfolio = vi.fn();
const patchPersonalPortfolio = vi.fn();

vi.mock("../api/personalPortfolios", () => ({
  listPersonalPortfolios: (...args: unknown[]) => listPersonalPortfolios(...args),
  getHubValuations: (...args: unknown[]) => getHubValuations(...args),
  createPersonalPortfolio: (...args: unknown[]) => createPersonalPortfolio(...args),
  deletePersonalPortfolio: (...args: unknown[]) => deletePersonalPortfolio(...args),
  patchPersonalPortfolio: (...args: unknown[]) => patchPersonalPortfolio(...args),
}));

const stablePortfolios = [
  {
    id: 1,
    name: "1",
    lifecycle_state: "ACTIVE",
    cash_rub: "3.340000",
    positions_count: 0,
  },
  {
    id: 2,
    name: "Смешанный",
    lifecycle_state: "ACTIVE",
    cash_rub: "100000",
    positions_count: 2,
  },
];

vi.mock("../portfolio/PortfolioContext", () => ({
  usePortfolioContext: () => ({
    portfolios: stablePortfolios,
    selectedPortfolioId: 1,
    selectPortfolio: vi.fn(),
    refreshList: vi.fn(async () => []),
    loading: false,
    error: null,
  }),
}));

describe("PortfolioPage hub balance", () => {
  beforeEach(() => {
    getHubValuations.mockReset();
  });

  it("shows cash-only total as 3,34 ₽ and full NAV for complete book", async () => {
    getHubValuations.mockResolvedValue({
      items: [
        {
          portfolio_id: 1,
          cash_rub: "3.34",
          securities_value_rub: "0",
          known_nav_rub: "3.34",
          total_nav_rub: "3.34",
          valuation_complete: true,
          valuation_partial: false,
          valuation_unavailable: false,
          valuation_as_of: null,
          valuation_label: "Только денежные средства",
          missing_price_count: 0,
          positions_count: 0,
        },
        {
          portfolio_id: 2,
          cash_rub: "100000",
          securities_value_rub: "250000",
          known_nav_rub: "350000",
          total_nav_rub: "350000",
          valuation_complete: true,
          valuation_partial: false,
          valuation_unavailable: false,
          valuation_as_of: "2026-10-28",
          valuation_label: "Оценка по ценам на 28.10.2026",
          missing_price_count: 0,
          positions_count: 2,
        },
      ],
      count: 2,
    });

    render(
      <MemoryRouter>
        <PortfolioPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("hub-total-1")).toHaveTextContent(/3,34/);
      expect(screen.getByTestId("hub-total-2")).toHaveTextContent(/350/);
    });
    expect(screen.getByTestId("hub-cash-1")).toHaveTextContent(/3,34/);
    expect(getHubValuations).toHaveBeenCalled();
  });

  it("does not present known_nav as full total when partial", async () => {
    getHubValuations.mockResolvedValue({
      items: [
        {
          portfolio_id: 1,
          cash_rub: "100000",
          securities_value_rub: "100",
          known_nav_rub: "100100",
          total_nav_rub: null,
          valuation_complete: false,
          valuation_partial: true,
          valuation_unavailable: false,
          valuation_as_of: null,
          valuation_label: "Частичная оценка",
          missing_price_count: 1,
          positions_count: 2,
        },
        {
          portfolio_id: 2,
          cash_rub: "0",
          securities_value_rub: "0",
          known_nav_rub: "0",
          total_nav_rub: null,
          valuation_complete: false,
          valuation_partial: false,
          valuation_unavailable: true,
          valuation_as_of: null,
          valuation_label: "нет цен",
          missing_price_count: 2,
          positions_count: 2,
        },
      ],
      count: 2,
    });

    render(
      <MemoryRouter>
        <PortfolioPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("hub-total-1")).toHaveTextContent(/недоступна/i);
    });
    expect(screen.getByTestId("hub-total-1")).toHaveTextContent(/Оценённая часть/);
    expect(screen.getByTestId("hub-total-1")).not.toHaveTextContent(/Общая стоимость:.*100/);
    expect(screen.getByTestId("hub-total-2")).toHaveTextContent(/недоступна/i);
  });

  it("does not show 0 ₽ for securities when hub valuation API fails", async () => {
    getHubValuations.mockRejectedValue(new Error("network down"));

    render(
      <MemoryRouter>
        <PortfolioPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("hub-total-1")).toHaveTextContent(/временно недоступна/i);
    });
    expect(screen.getByTestId("hub-securities-1")).toHaveTextContent(/Оценка недоступна/);
    expect(screen.getByTestId("hub-securities-1")).not.toHaveTextContent(/0/);
    expect(screen.getByTestId("hub-securities-2")).toHaveTextContent(/Оценка недоступна/);
  });

  it("shows dash for securities when a portfolio is missing from hub response", async () => {
    getHubValuations.mockResolvedValue({
      items: [
        {
          portfolio_id: 1,
          cash_rub: "3.34",
          securities_value_rub: "0",
          known_nav_rub: "3.34",
          total_nav_rub: "3.34",
          valuation_complete: true,
          valuation_partial: false,
          valuation_unavailable: false,
          valuation_as_of: null,
          valuation_label: "Только денежные средства",
          missing_price_count: 0,
          positions_count: 0,
        },
        // portfolio 2 deliberately omitted
      ],
      count: 1,
    });

    render(
      <MemoryRouter>
        <PortfolioPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("hub-total-1")).toHaveTextContent(/3,34/);
    });
    expect(screen.getByTestId("hub-total-2")).toHaveTextContent(/недоступна/i);
    expect(screen.getByTestId("hub-securities-2")).toHaveTextContent(/Оценка недоступна|—/);
    expect(screen.getByTestId("hub-securities-2")).not.toHaveTextContent(/^0/);
  });
});
