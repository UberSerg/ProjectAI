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
const setDraftCash = vi.fn();
const patchDraftPosition = vi.fn();
const deleteDraftPosition = vi.fn();
const searchCatalogInstruments = vi.fn();

vi.mock("../../api/personalPortfolios", () => ({
  getPersonalPortfolio: (...args: unknown[]) => getPersonalPortfolio(...args),
  createPersonalOperation: (...args: unknown[]) => createPersonalOperation(...args),
  activatePersonalPortfolio: (...args: unknown[]) => activatePersonalPortfolio(...args),
  clearDraftPortfolio: (...args: unknown[]) => clearDraftPortfolio(...args),
  resetPersonalPortfolio: (...args: unknown[]) => resetPersonalPortfolio(...args),
  setDraftCash: (...args: unknown[]) => setDraftCash(...args),
  patchDraftPosition: (...args: unknown[]) => patchDraftPosition(...args),
  deleteDraftPosition: (...args: unknown[]) => deleteDraftPosition(...args),
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

const draftEquityPosition = {
  id: 11,
  instrument_id: 1,
  secid: "SBER",
  name: "Сбербанк",
  asset_class: "equity",
  units: "100",
  lots: "10",
  average_price: "250",
  cost_basis_total_rub: "25000",
  cost_basis_status: "KNOWN" as const,
  current_price: "260",
  price_date: "2026-09-25",
  market_value: "26000",
  unrealized_pnl: "1000",
  price_available: true,
};

const draftBondPosition = {
  id: 12,
  instrument_id: 9,
  secid: "OFZ",
  name: "ОФЗ 26240",
  asset_class: "bond",
  units: "2",
  lots: "2",
  average_price: null,
  cost_basis_total_rub: null,
  cost_basis_status: "UNKNOWN" as const,
  current_price: "967.5",
  price_date: "2026-09-20",
  market_value: "1935",
  unrealized_pnl: null,
  price_available: true,
  pnl_unavailable_reason: "Себестоимость не указана — прибыль пока не рассчитывается.",
};

const draftSummary = {
  ...emptySummary,
  summary: {
    ...emptySummary.summary,
    cash_rub: "50000",
    securities_value_rub: "27935",
    nav_rub: "77935",
  },
  positions: [draftEquityPosition, draftBondPosition],
};

function renderPanel() {
  return render(
    <MemoryRouter>
      <KrakenRoleProvider>
        <PersonalPortfolioPanel portfolioId={1} />
      </KrakenRoleProvider>
    </MemoryRouter>,
  );
}

describe("PersonalPortfolioPanel DRAFT manager", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    vi.stubGlobal("confirm", vi.fn(() => true));
    getPersonalPortfolio.mockReset();
    setDraftCash.mockReset();
    patchDraftPosition.mockReset();
    deleteDraftPosition.mockReset();
    clearDraftPortfolio.mockReset();
    resetPersonalPortfolio.mockReset();
    searchCatalogInstruments.mockReset();
    searchCatalogInstruments.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 8 });
    getPersonalPortfolio.mockResolvedValue(draftSummary);
  });

  it("edits DRAFT cash and allows zero", async () => {
    setDraftCash.mockResolvedValue({
      ...draftSummary,
      summary: { ...draftSummary.summary, cash_rub: "0" },
    });
    renderPanel();
    fireEvent.click(await screen.findByTestId("draft-cash-edit-btn"));
    expect(screen.getByTestId("draft-cash-modal")).toBeInTheDocument();
    expect(screen.getByText("Свободные деньги, ₽")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("draft-cash-input"), { target: { value: "0" } });
    fireEvent.click(screen.getByTestId("draft-cash-submit"));
    await waitFor(() => expect(setDraftCash).toHaveBeenCalledWith(1, 0));
  });

  it("uses draft wording instead of journal wording", async () => {
    renderPanel();
    await screen.findByTestId("draft-summary");
    expect(screen.getByText("Свободные деньги")).toBeInTheDocument();
    expect(screen.getByText("Текущая стоимость портфеля")).toBeInTheDocument();
    expect(screen.queryByText("Внесено")).not.toBeInTheDocument();
  });

  it("edits a DRAFT equity position", async () => {
    patchDraftPosition.mockResolvedValue({ id: 11, portfolio: draftSummary });
    renderPanel();
    fireEvent.click(await screen.findByTestId("draft-position-edit-11"));
    expect(screen.getByTestId("draft-position-modal")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("draft-position-units"), { target: { value: "120" } });
    fireEvent.change(screen.getByTestId("draft-position-avg-price"), { target: { value: "240" } });
    fireEvent.change(screen.getByTestId("draft-position-note"), { target: { value: "докупил" } });
    fireEvent.click(screen.getByTestId("draft-position-submit"));
    await waitFor(() => expect(patchDraftPosition).toHaveBeenCalled());
    expect(patchDraftPosition.mock.calls[0][0]).toBe(1);
    expect(patchDraftPosition.mock.calls[0][1]).toBe(11);
    expect(patchDraftPosition.mock.calls[0][2]).toMatchObject({
      units: "120",
      average_price: "240",
      note: "докупил",
    });
  });

  it("clears the cost basis of a DRAFT position", async () => {
    patchDraftPosition.mockResolvedValue({ id: 11, portfolio: draftSummary });
    renderPanel();
    fireEvent.click(await screen.findByTestId("draft-position-edit-11"));
    fireEvent.click(screen.getByTestId("draft-position-clear-cost"));
    fireEvent.click(screen.getByTestId("draft-position-submit"));
    await waitFor(() => expect(patchDraftPosition).toHaveBeenCalled());
    const body = patchDraftPosition.mock.calls[0][2] as Record<string, unknown>;
    expect(body.clear_cost_basis).toBe(true);
    expect(body.average_price).toBeUndefined();
  });

  it("asks for a RUB total and never a MOEX percent for a bond", async () => {
    renderPanel();
    await screen.findByTestId("draft-positions-table");
    expect(screen.getByTestId("draft-positions-table")).toHaveTextContent("Не указана");
    fireEvent.click(screen.getByTestId("draft-position-edit-12"));
    expect(screen.getByText("Общая себестоимость позиции, ₽")).toBeInTheDocument();
    expect((screen.getByTestId("draft-position-cost-total") as HTMLInputElement).value).toBe("");
    expect(screen.queryByTestId("draft-position-avg-price")).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId("draft-position-cost-total"), { target: { value: "1900" } });
    patchDraftPosition.mockResolvedValue({ id: 12, portfolio: draftSummary });
    fireEvent.click(screen.getByTestId("draft-position-submit"));
    await waitFor(() => expect(patchDraftPosition).toHaveBeenCalled());
    expect(patchDraftPosition.mock.calls[0][2]).toMatchObject({ cost_basis_total_rub: "1900" });
  });

  it("removes a DRAFT position after confirmation", async () => {
    deleteDraftPosition.mockResolvedValue({ status: "DELETED", id: 12, portfolio: emptySummary });
    renderPanel();
    fireEvent.click(await screen.findByTestId("draft-position-remove-12"));
    expect(window.confirm).toHaveBeenCalledWith("Убрать OFZ из портфеля?");
    await waitFor(() => expect(deleteDraftPosition).toHaveBeenCalledWith(1, 12));
  });

  it("clears the whole DRAFT portfolio", async () => {
    clearDraftPortfolio.mockResolvedValue(emptySummary);
    renderPanel();
    fireEvent.click(await screen.findByTestId("clear-draft-btn"));
    await waitFor(() => expect(clearDraftPortfolio).toHaveBeenCalledWith(1));
    expect(await screen.findByText("Пока нет позиций")).toBeInTheDocument();
  });

  it("resets an ACTIVE portfolio only after two confirmations", async () => {
    getPersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: {
        ...emptySummary.portfolio,
        lifecycle_state: "ACTIVE",
        has_operations: true,
        journal_state: "ACTIVE",
      },
    });
    resetPersonalPortfolio.mockResolvedValue(emptySummary);
    renderPanel();
    fireEvent.click(await screen.findByTestId("reset-portfolio-btn"));
    await waitFor(() => expect(resetPersonalPortfolio).toHaveBeenCalledWith(1));
    expect(window.confirm).toHaveBeenCalledTimes(2);
  });
});

describe("PersonalPortfolioPanel", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("confirm", vi.fn(() => true));
    getPersonalPortfolio.mockReset();
    createPersonalOperation.mockReset();
    activatePersonalPortfolio.mockReset();
    clearDraftPortfolio.mockReset();
    resetPersonalPortfolio.mockReset();
    setDraftCash.mockReset();
    patchDraftPosition.mockReset();
    deleteDraftPosition.mockReset();
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

  it("offers only human operation types in the selector", async () => {
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

    const select = screen.getByTestId("op-type") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "COMMISSION"]);
    expect(select.textContent).not.toMatch(/Начальное состояние/);
  });

  it("still labels Kraken opening rows in the journal", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    getPersonalPortfolio.mockResolvedValue({
      ...emptySummary,
      portfolio: {
        ...emptySummary.portfolio,
        lifecycle_state: "ACTIVE",
        has_operations: true,
        journal_state: "ACTIVE",
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
        {
          id: 2,
          operation_type: "OPENING_POSITION",
          status: "ACTIVE",
          occurred_at: "2026-09-27T12:00:00+00:00",
          instrument_id: 1,
          lots: null,
          units: "10",
          price: "250",
          amount: null,
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
    await waitFor(() => expect(screen.getByTestId("personal-operations")).toBeInTheDocument());
    expect(screen.getByText("Начальное состояние · деньги")).toBeInTheDocument();
    expect(screen.getByText("Начальное состояние · позиция")).toBeInTheDocument();
  });

  it("refetches when the page bumps refreshToken", async () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    getPersonalPortfolio.mockResolvedValue(emptySummary);
    const { rerender } = render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} refreshToken={0} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(getPersonalPortfolio).toHaveBeenCalledTimes(1));

    rerender(
      <MemoryRouter>
        <KrakenRoleProvider>
          <PersonalPortfolioPanel portfolioId={1} refreshToken={1} />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(getPersonalPortfolio).toHaveBeenCalledTimes(2));
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
