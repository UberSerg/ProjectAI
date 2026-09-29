import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BrokerSettingsPanel } from "./BrokerSettingsPanel";
import type { PersonalSummary } from "../../api/personalPortfolios";

const listBrokerAccounts = vi.fn();
const listFeeProfiles = vi.fn();
const createBrokerAccount = vi.fn();
const createFeeProfile = vi.fn();
const assignPortfolioBroker = vi.fn();

vi.mock("../../api/brokerAccounts", () => ({
  listBrokerAccounts: (...args: unknown[]) => listBrokerAccounts(...args),
  listFeeProfiles: (...args: unknown[]) => listFeeProfiles(...args),
  createBrokerAccount: (...args: unknown[]) => createBrokerAccount(...args),
  createFeeProfile: (...args: unknown[]) => createFeeProfile(...args),
}));

vi.mock("../../api/personalPortfolios", () => ({
  assignPortfolioBroker: (...args: unknown[]) => assignPortfolioBroker(...args),
}));

const sberProfile = {
  id: 10,
  code: "SBER_INVESTMENT",
  name: "СберИнвестиции — Инвестиционный",
  broker_code: "SBER",
  broker_name: "СберИнвестиции",
  tariff_name: "Инвестиционный",
  version: 1,
  is_builtin: true,
  read_only: true,
  buy_rate_pct: "0.3",
  sell_rate_pct: "0.3",
};

const account = {
  id: 5,
  name: "Счёт Сбер",
  broker_code: "SBER",
  broker_name: "СберИнвестиции",
  tariff_name: "Инвестиционный",
  fee_profile_id: 10,
  base_currency: "RUB",
  active: true,
  fee_profile: sberProfile,
};

const summaryWithBroker = {
  portfolio: {
    id: 1,
    name: "Основной",
    base_currency: "RUB",
    status: "ACTIVE",
    is_test: false,
    version: 1,
    has_operations: true,
    broker_account_id: 5,
    broker: {
      broker_account_id: 5,
      broker_account_name: "Счёт Сбер",
      broker_code: "SBER",
      broker_name: "СберИнвестиции",
      tariff_name: "Инвестиционный",
      fee_profile_id: 10,
      fee_profile_code: "SBER_INVESTMENT",
      fee_profile_name: sberProfile.name,
      is_builtin: true,
      read_only: true,
    },
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
    valuation_label: "—",
    missing_price_count: 0,
  },
  positions: [],
  operations: [],
  recommendation_disclaimer: "Модельная рекомендация",
} as PersonalSummary;

describe("BrokerSettingsPanel", () => {
  beforeEach(() => {
    listBrokerAccounts.mockReset();
    listFeeProfiles.mockReset();
    createBrokerAccount.mockReset();
    createFeeProfile.mockReset();
    assignPortfolioBroker.mockReset();
    listBrokerAccounts.mockResolvedValue({ items: [account], count: 1 });
    listFeeProfiles.mockResolvedValue({ items: [sberProfile], count: 1 });
  });

  it("shows broker summary and assigns selected account", async () => {
    const onChanged = vi.fn();
    render(
      <BrokerSettingsPanel portfolioId={1} broker={null} onChanged={onChanged} />,
    );
    expect(screen.getByTestId("broker-summary-label")).toHaveTextContent(/не назначен/i);
    fireEvent.click(screen.getByTestId("broker-settings-toggle"));
    await waitFor(() => expect(screen.getByTestId("broker-account-select")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("broker-account-select"), { target: { value: "5" } });
    assignPortfolioBroker.mockResolvedValue(summaryWithBroker);
    fireEvent.click(screen.getByTestId("broker-assign-btn"));
    await waitFor(() => expect(assignPortfolioBroker).toHaveBeenCalledWith(1, 5));
    expect(onChanged).toHaveBeenCalled();
  });

  it("creates custom BUY%/SELL% profile", async () => {
    const onChanged = vi.fn();
    render(
      <BrokerSettingsPanel portfolioId={1} broker={null} onChanged={onChanged} />,
    );
    fireEvent.click(screen.getByTestId("broker-settings-toggle"));
    await waitFor(() => expect(screen.getByTestId("broker-custom-toggle")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("broker-custom-toggle"));
    fireEvent.change(screen.getByTestId("broker-custom-name"), { target: { value: "Мой тариф" } });
    fireEvent.change(screen.getByTestId("broker-custom-broker"), { target: { value: "ТестБрокер" } });
    fireEvent.change(screen.getByTestId("broker-custom-buy"), { target: { value: "0.05" } });
    fireEvent.change(screen.getByTestId("broker-custom-sell"), { target: { value: "0.05" } });
    createFeeProfile.mockResolvedValue({
      ...sberProfile,
      id: 99,
      code: "CUSTOM_0001",
      name: "Мой тариф",
      is_builtin: false,
      read_only: false,
      buy_rate_pct: "0.05",
      sell_rate_pct: "0.05",
    });
    listFeeProfiles.mockResolvedValue({
      items: [
        sberProfile,
        {
          ...sberProfile,
          id: 99,
          code: "CUSTOM_0001",
          name: "Мой тариф",
          is_builtin: false,
          read_only: false,
        },
      ],
      count: 2,
    });
    fireEvent.click(screen.getByTestId("broker-custom-save"));
    await waitFor(() =>
      expect(createFeeProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Мой тариф",
          broker_name: "ТестБрокер",
          buy_rate_pct: "0.05",
          sell_rate_pct: "0.05",
        }),
      ),
    );
  });
});
