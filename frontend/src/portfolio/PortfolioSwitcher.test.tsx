import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PortfolioProvider, usePortfolioContext } from "./PortfolioContext";
import { PortfolioSwitcher } from "./PortfolioSwitcher";

const listPersonalPortfolios = vi.fn();
const createPersonalPortfolio = vi.fn();

vi.mock("../api/personalPortfolios", () => ({
  listPersonalPortfolios: (...args: unknown[]) => listPersonalPortfolios(...args),
  createPersonalPortfolio: (...args: unknown[]) => createPersonalPortfolio(...args),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

function RefreshProbe() {
  const { refreshList, portfolios } = usePortfolioContext();
  return (
    <>
      <button type="button" onClick={() => void refreshList()}>Refresh portfolio list</button>
      <span data-testid="portfolio-names">{portfolios.map((p) => p.name).join("|")}</span>
    </>
  );
}

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
    expect(await screen.findByRole("button", { name: "Создать первый портфель" })).toBeInTheDocument();
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
  it("retains created portfolio after a successful POST and failed list GET", async () => {
    createPersonalPortfolio.mockResolvedValue({
      portfolio: { id: 3, name: "Created despite GET failure", lifecycle_state: "DRAFT" },
      summary: { cash_rub: "0", nav_rub: "0", valuation_partial: false },
      positions: [],
    });
    listPersonalPortfolios
      .mockResolvedValueOnce({ items: [cardA, cardB], count: 2 })
      .mockRejectedValueOnce(new Error("List temporarily unavailable"));
    renderSwitcher();
    fireEvent.click(await screen.findByRole("button", { name: /Основной портфель ▾/ }));
    fireEvent.click(screen.getByRole("button", { name: "+ Создать портфель" }));
    fireEvent.change(screen.getByPlaceholderText("Основной"), {
      target: { value: "Created despite GET failure" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/portfolio/3"));
    expect(createPersonalPortfolio).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /Created despite GET failure ▾/ }));
    expect(screen.getByRole("button", { name: /Created despite GET failure Настройка/ })).toBeInTheDocument();
  });

  it("ignores out-of-order list responses", async () => {
    const older = deferred<{ items: typeof cardA[]; count: number }>();
    const newer = deferred<{ items: typeof cardA[]; count: number }>();
    listPersonalPortfolios
      .mockResolvedValueOnce({ items: [cardA], count: 1 })
      .mockImplementationOnce(() => older.promise)
      .mockImplementationOnce(() => newer.promise);
    render(
      <MemoryRouter>
        <PortfolioProvider>
          <RefreshProbe />
        </PortfolioProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("portfolio-names")).toHaveTextContent("Основной портфель"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh portfolio list" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh portfolio list" }));
    await act(async () => { newer.resolve({ items: [cardB], count: 1 }); });
    expect(screen.getByTestId("portfolio-names")).toHaveTextContent("Второй портфель");
    await act(async () => { older.resolve({ items: [cardA], count: 1 }); });
    expect(screen.getByTestId("portfolio-names")).toHaveTextContent("Второй портфель");
    expect(screen.getByTestId("portfolio-names")).not.toHaveTextContent("Основной портфель");
  });

});
