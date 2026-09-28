import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PortfolioProvider } from "./PortfolioContext";
import { PortfolioSwitcher } from "./PortfolioSwitcher";

const listPersonalPortfolios = vi.fn();
const createPersonalPortfolio = vi.fn();

vi.mock("../api/personalPortfolios", () => ({
  listPersonalPortfolios: (...args: unknown[]) => listPersonalPortfolios(...args),
  createPersonalPortfolio: (...args: unknown[]) => createPersonalPortfolio(...args),
}));

const cardA = {
  id: 1,
  name: "Основной портфель",
  lifecycle_state: "ACTIVE",
  cash_rub: "10000",
  positions_count: 1,
};

const cardB = {
  ...cardA,
  id: 2,
  name: "Второй портфель",
  lifecycle_state: "DRAFT",
};

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname}</span>;
}

function renderSwitcher() {
  return render(
    <MemoryRouter initialEntries={["/portfolio/1"]}>
      <PortfolioProvider>
        <PortfolioSwitcher />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </PortfolioProvider>
    </MemoryRouter>,
  );
}

describe("PortfolioSwitcher", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    listPersonalPortfolios.mockResolvedValue({ items: [cardA, cardB], count: 2 });
  });

  it("offers a create action when there are no portfolios", async () => {
    listPersonalPortfolios.mockResolvedValue({ items: [], count: 0 });
    renderSwitcher();
    expect(await screen.findByRole("button", { name: "Создать портфель" })).toBeInTheDocument();
  });

  it("lists portfolios with lifecycle labels and navigates on selection", async () => {
    renderSwitcher();
    fireEvent.click(await screen.findByRole("button", { name: /Основной портфель ▾/ }));
    expect(screen.getByRole("button", { name: /Основной портфель Учёт/ })).toBeInTheDocument();
    const target = screen.getByRole("button", { name: /Второй портфель Настройка/ });
    fireEvent.click(target);
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/portfolio/2"));
    expect(localStorage.getItem("kraken.selectedPortfolioId")).toBe("2");
  });

  it("creates a portfolio and switches to it", async () => {
    createPersonalPortfolio.mockResolvedValue({
      portfolio: { id: 3, name: "Третий портфель", lifecycle_state: "DRAFT" },
      summary: { cash_rub: "0", nav_rub: "0", valuation_partial: false },
      positions: [],
    });
    listPersonalPortfolios
      .mockResolvedValueOnce({ items: [cardA, cardB], count: 2 })
      .mockResolvedValue({
        items: [cardA, cardB, { ...cardB, id: 3, name: "Третий портфель" }],
        count: 3,
      });
    renderSwitcher();
    fireEvent.click(await screen.findByRole("button", { name: /Основной портфель ▾/ }));
    fireEvent.click(screen.getByRole("button", { name: "+ Создать портфель" }));
    fireEvent.change(screen.getByPlaceholderText("Основной"), {
      target: { value: "Третий портфель" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() =>
      expect(createPersonalPortfolio).toHaveBeenCalledWith({ name: "Третий портфель" }),
    );
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/portfolio/3"));
  });
});
