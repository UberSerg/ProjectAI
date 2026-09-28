import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KrakenRoleProvider } from "../../role/KrakenRoleContext";
import { ROLE_STORAGE_KEY } from "../../role/types";
import { PersonalPortfolioPanel } from "./PersonalPortfolioPanel";

const getPersonalPortfolio = vi.fn();
const createPersonalOperation = vi.fn();
const activatePersonalPortfolio = vi.fn();
const clearDraftPortfolio = vi.fn();
const resetPersonalPortfolio = vi.fn();
const searchCatalogInstruments = vi.fn();

vi.mock("../../api/personalPortfolios", () => ({
  getPersonalPortfolio: (...args: unknown[]) => getPersonalPortfolio(...args),
  createPersonalOperation: (...args: unknown[]) => createPersonalOperation(...args),
  activatePersonalPortfolio: (...args: unknown[]) => activatePersonalPortfolio(...args),
  clearDraftPortfolio: (...args: unknown[]) => clearDraftPortfolio(...args),
  resetPersonalPortfolio: (...args: unknown[]) => resetPersonalPortfolio(...args),
}));

vi.mock("../../api/instruments", () => ({
  searchCatalogInstruments: (params?: unknown, signal?: AbortSignal) =>
    searchCatalogInstruments(params, signal),
}));

vi.mock("../../api/system", () => ({
  reportClientError: vi.fn(),
}));

const emptySummary = {
  portfolio: {
    id: 1,
    name: "Основной портфель",
    base_currency: "RUB",
    lifecycle_state: "DRAFT" as const,
    status: "ACTIVE",
    is_test: false,
    version: 1,
    has_operations: false,
    journal_state: "EMPTY" as const,
    journal_cutover_at: null,
  },
  summary: {
    cash_rub: "0",
    securities_value_rub: "0",
    nav_rub: "0",
    contributed_rub: "0",
    withdrawn_rub: "0",
    investment_pnl_rub: "0",
    realized_pnl_rub: "0",
    valuation_complete: true,
    valuation_partial: false,
    valuation_as_of: null,
    valuation_label: "Оценка недоступна — нет цен",
    missing_price_count: 0,
  },
  positions: [],
  operations: [],
  recommendation_disclaimer: "Модельная рекомендация",
};

describe("PersonalPortfolioPanel", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("confirm", vi.fn(() => true));
    getPersonalPortfolio.mockReset();
    createPersonalOperation.mockReset();
    activatePersonalPortfolio.mockReset();
    clearDraftPortfolio.mockReset();
    resetPersonalPortfolio.mockReset();
    searchCatalogInstruments.mockReset();
    searchCatalogInstruments.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 8 });
  });

  it("shows draft setup when portfolio not activated", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    getPersonalPortfolio.mockResolvedValue(emptySummary);
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("draft-setup-banner")).toBeInTheDocument());
    expect(screen.getByText(/История операций ещё не начата/i)).toBeInTheDocument();
    expect(screen.getByTestId("activate-journal-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("add-operation-btn")).not.toBeInTheDocument();
  });

  it("shows draft metrics and activate CTA", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    getPersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: { ...emptySummary.portfolio, lifecycle_state: "DRAFT" },
      summary: {
        ...emptySummary.summary,
        cash_rub: "50000",
        securities_value_rub: "25000",
        nav_rub: "75000",
      },
      positions: [
        {
          instrument_id: 1,
          secid: "SBER",
          name: "Sber",
          units: "100",
          lots: null,
          average_price: "250",
          cost_basis_status: "KNOWN",
          current_price: "260",
          price_date: "2026-09-25",
          market_value: "26000",
          unrealized_pnl: "1000",
          price_available: true,
        },
      ],
    });
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("draft-summary")).toBeInTheDocument());
    expect(screen.getByTestId("activate-journal-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("add-operation-btn")).not.toBeInTheDocument();
  });

  it("activation success enters ACTIVE mode", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    getPersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: { ...emptySummary.portfolio, lifecycle_state: "DRAFT" },
      summary: { ...emptySummary.summary, cash_rub: "50000", nav_rub: "50000" },
    });
    activatePersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: {
        ...emptySummary.portfolio,
        lifecycle_state: "ACTIVE",
        journal_state: "ACTIVE",
        has_operations: true,
        journal_cutover_at: "2026-09-27T12:00:00+00:00",
      },
      summary: {
        ...emptySummary.summary,
        cash_rub: "50000",
        contributed_rub: "50000",
        nav_rub: "50000",
        investment_pnl_rub: "0",
      },
      operations: [
        {
          id: 1,
          operation_type: "OPENING_CASH",
          status: "ACTIVE",
          occurred_at: "2026-09-27T12:00:00+00:00",
          instrument_id: null,
          lots: null,
          units: null,
          price: null,
          amount: "50000",
          commission: "0",
          currency: "RUB",
          note: null,
        },
      ],
    });
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("activate-journal-btn")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("activate-journal-btn"));
    await waitFor(() => expect(screen.getByTestId("personal-summary")).toBeInTheDocument());
    expect(screen.getByTestId("add-operation-btn")).toBeInTheDocument();
    expect(activatePersonalPortfolio).toHaveBeenCalledWith(1);
  });

  it("shows contribution vs investment pnl and owner reconciliation", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "OWNER");
    getPersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: {
        ...emptySummary.portfolio,
        lifecycle_state: "ACTIVE",
        has_operations: true,
        journal_state: "ACTIVE",
      },
      summary: {
        ...emptySummary.summary,
        cash_rub: "130000",
        nav_rub: "130000",
        contributed_rub: "130000",
        investment_pnl_rub: "0",
        valuation_label: "Оценка по ценам на 25.09.2026",
      },
      reconciliation: { status: "OK", cash_ok: true, positions_ok: true },
    });
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("personal-summary")).toBeInTheDocument());
    expect(screen.getByText("Инвестиционный результат")).toBeInTheDocument();
    expect(screen.getByTestId("owner-reconciliation")).toHaveTextContent("OK");
  });

  it("shows bond P&L unavailable", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    getPersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: {
        ...emptySummary.portfolio,
        lifecycle_state: "ACTIVE",
        has_operations: true,
        journal_state: "ACTIVE",
      },
      summary: {
        ...emptySummary.summary,
        cash_rub: "0",
        securities_value_rub: "1935",
        nav_rub: "1935",
        contributed_rub: "1935",
        investment_pnl_rub: "0",
        valuation_as_of: "2026-09-20",
        valuation_label: "Оценка по ценам на 20.09.2026",
      },
      positions: [
        {
          instrument_id: 9,
          secid: "OFZ",
          name: "Облигация",
          asset_class: "bond",
          units: "2",
          lots: "2",
          average_price: null,
          cost_basis_status: "UNKNOWN",
          current_price: "967.5",
          price_date: "2026-09-20",
          market_value: "1935",
          unrealized_pnl: null,
          price_available: true,
          pnl_unavailable_reason: "Для облигаций расчёт результата будет доступен",
        },
      ],
      operations: [],
    });
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("personal-positions")).toBeInTheDocument());
    expect(screen.getByText(/P&L недоступен/i)).toBeInTheDocument();
  });

  it("opens add operation modal with datetime-local", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    getPersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: {
        ...emptySummary.portfolio,
        lifecycle_state: "ACTIVE",
        has_operations: true,
        journal_state: "ACTIVE",
      },
    });
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("add-operation-btn")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("add-operation-btn"));
    expect(screen.getByTestId("add-operation-modal")).toBeInTheDocument();
    expect(screen.getByTestId("op-occurred-at")).toHaveAttribute("type", "datetime-local");
  });

  it("uses second-precision datetime-local for post-activation ops", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    getPersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: {
        ...emptySummary.portfolio,
        lifecycle_state: "ACTIVE",
        has_operations: true,
        journal_state: "ACTIVE",
        journal_cutover_at: "2026-09-27T13:11:37.123456+00:00",
      },
    });
    const { defaultOccurredLocal, toIsoOccurredAt } = await import("./PersonalPortfolioPanel");
    const cutover = new Date("2026-09-27T13:11:37.123456Z");
    const justAfter = new Date(cutover.getTime() + 1000);
    const local = defaultOccurredLocal(justAfter);
    expect(local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/);
    const iso = toIsoOccurredAt(local);
    expect(new Date(iso).getTime()).toBeGreaterThan(cutover.getTime());

    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("add-operation-btn")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("add-operation-btn"));
    const input = screen.getByTestId("op-occurred-at");
    expect(input).toHaveAttribute("type", "datetime-local");
    expect(input).toHaveAttribute("step", "1");
    expect((input as HTMLInputElement).value).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/,
    );
  });

  it("shows unavailable investment result when pnl is null", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    getPersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: {
        ...emptySummary.portfolio,
        lifecycle_state: "ACTIVE",
        has_operations: true,
        journal_state: "ACTIVE",
      },
      summary: {
        ...emptySummary.summary,
        cash_rub: "60000",
        securities_value_rub: "40000",
        nav_rub: "100000",
        contributed_rub: "100000",
        investment_pnl_rub: null,
        valuation_partial: true,
        missing_price_count: 1,
        valuation_as_of: null,
        valuation_label: "Частичная оценка · цены на 25.09.2026 · для 1 позиции цена недоступна",
      },
    });
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("personal-summary")).toBeInTheDocument());
    expect(screen.getByText(/Результат недоступен/i)).toBeInTheDocument();
    expect(screen.getByTestId("valuation-partial")).toBeInTheDocument();
  });

  it("reuses idempotency key on same payload network retry", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    getPersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: {
        ...emptySummary.portfolio,
        lifecycle_state: "ACTIVE",
        has_operations: true,
        journal_state: "ACTIVE",
      },
    });
    createPersonalOperation
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValueOnce({ operation_id: 1, portfolio: emptySummary });
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("add-operation-btn")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("add-operation-btn"));
    fireEvent.change(screen.getByTestId("op-amount"), { target: { value: "100000" } });
    fireEvent.click(screen.getByTestId("op-submit"));
    await waitFor(() => expect(createPersonalOperation).toHaveBeenCalledTimes(1));
    const firstKey = (createPersonalOperation.mock.calls[0][1] as { idempotencyKey: string })
      .idempotencyKey;
    fireEvent.click(screen.getByTestId("op-submit"));
    await waitFor(() => expect(createPersonalOperation).toHaveBeenCalledTimes(2));
    const secondKey = (createPersonalOperation.mock.calls[1][1] as { idempotencyKey: string })
      .idempotencyKey;
    expect(secondKey).toBe(firstKey);
  });

  it("blocks bond trade confirmation in UI", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    getPersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: {
        ...emptySummary.portfolio,
        lifecycle_state: "ACTIVE",
        has_operations: true,
        journal_state: "ACTIVE",
      },
    });
    searchCatalogInstruments.mockResolvedValue({
      items: [
        {
          id: 99,
          symbol: "OFZ",
          name: "ОФЗ тест",
          asset_class: "bond",
          instrument_subtype: null,
          support_level: "PARTIAL",
          primary_board: "TQOB",
          exchange: "MOEX",
          currency: "RUB",
          isin: null,
          is_active: true,
          sources: ["MOEX"],
        },
      ],
      total: 1,
      page: 1,
      page_size: 8,
    });
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("add-operation-btn")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("add-operation-btn"));
    fireEvent.change(screen.getByTestId("op-type"), { target: { value: "BUY" } });
    fireEvent.change(screen.getByTestId("op-instrument"), { target: { value: "OFZ" } });
    await waitFor(() => expect(screen.getByTestId("op-instrument-hits")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /OFZ/i }));
    expect(screen.getByTestId("bond-trade-blocked")).toBeInTheDocument();
    expect(screen.getByTestId("op-submit")).toBeDisabled();
  });
});
