import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HelpProvider } from "../help";
import { PortfolioCandidatePage } from "./PortfolioCandidatePage";

const sample = {
  candidate_id: "pc_demo",
  version: "CONCRETE_PORTFOLIO_CANDIDATE_V1",
  as_of: "2026-09-05",
  generated_at: "2026-09-07T10:00:00+00:00",
  capital: "100000",
  currency: "RUB",
  status: "READY_FOR_RESEARCH",
  summary: {
    positions_count: 2,
    equity_positions: 1,
    fixed_income_positions: 1,
    equity_rub: "24000",
    fixed_income_rub: "63732",
    cash_rub: "12256",
    research_only_count: 1,
    executable_count: 1,
  },
  readiness: {
    mode_ru: "Исследовательский режим",
    ready_for_real_money: false,
    banner_ru: "Не готов для автоматического использования реальных денег.",
    reasons_ru: ["Equity confidence: Недостаточно данных", "Taxes: не моделируются"],
  },
  allocation: {
    equity: { target_weight: 0.25, actual_weight: 0.24, target_rub: "25000", actual_rub: "24000" },
    fixed_income: {
      target_weight: 0.65,
      actual_weight: 0.63,
      target_rub: "65000",
      actual_rub: "63732",
    },
    cash: { target_weight: 0.1, actual_weight: 0.13, target_rub: "10000", actual_rub: "12256" },
  },
  positions: [
    {
      instrument_id: 1,
      symbol: "SBER",
      display_name: "Сбербанк",
      sleeve: "EQUITY_ALPHA",
      asset_class: "equity",
      lots: 8,
      units: 80,
      lot_size: 10,
      reference_price: "300",
      estimated_notional: "24000",
      estimated_fees: "12",
      target_weight: 0.25,
      actual_weight: 0.24,
      risk_status: "RESEARCH_ONLY",
      executable: false,
      reason_ru: "Доля акций ограничена калибровкой; позиция только для исследования.",
      warnings_ru: [],
      confidence_label_ru: "Недостаточно данных",
      selection_rank: 1,
      signal_semantic: "EXPECTED_RETURN",
      eligibility: "RESEARCH_ONLY",
    },
    {
      instrument_id: 2,
      symbol: "SU26238RMFS4",
      display_name: "ОФЗ 26238",
      sleeve: "FIXED_INCOME",
      asset_class: "bond",
      lots: 6,
      units: 6,
      lot_size: 1,
      reference_price: "98.5",
      dirty_price: "100.2",
      nkd: "1.7",
      estimated_notional: "63732",
      estimated_fees: "32",
      target_weight: 0.65,
      actual_weight: 0.63,
      risk_status: "APPROVED_WITH_WARNINGS",
      executable: true,
      reason_ru: "Государственная облигация с подтверждённой ликвидностью.",
      warnings_ru: ["Кредитное качество не подтверждено для части universe"],
      credit_status: "UNKNOWN",
      liquidity_status: "OK",
      selection_rank: 1,
      bond_type: "ОФЗ",
      coupon_rate: 0.07,
      maturity_date: "2031-05-15",
      yield_value: 0.145,
      eligibility: "REAL_PORTFOLIO_CANDIDATE",
    },
  ],
  cash: {
    strategic_target_rub: "10000",
    strategic_target_weight: 0.1,
    lot_remainder_rub: "2256",
    total_cash_rub: "12256",
  },
  rejected_candidates: [
    {
      symbol: "CORP_X",
      display_name: "Корпоративная облигация X",
      sleeve: "FIXED_INCOME",
      opportunity_hint: "Доходность ~18.0%",
      risk_status: "BLOCKED",
      reason_ru: "Кредитное качество неизвестно.",
    },
  ],
  warnings: ["Equity confidence неизвестна"],
  reasons_ru: ["Kraken ограничил акции до 25%."],
  money: {
    starting_capital: "100000",
    invested: "87732",
    equity_invested: "24000",
    fixed_income_invested: "63732",
    fees: "44",
    equity_fees: "12",
    fixed_income_fees: "32",
    strategic_cash: "10000",
    lot_remainder: "2256",
    ending_preview_cash: "12256",
    tax_note_ru: "До налогов.",
    broker_note_ru: "Исследовательский профиль издержек.",
  },
  composition: {
    equity: { selected: 1, available: 10 },
    fixed_income: { selected: 1, available: 20 },
  },
  provenance: {
    candidate_version: "CONCRETE_PORTFOLIO_CANDIDATE_V1",
    equity_policy: "EQUITY_COMPOSITION_V1",
    fixed_income_policy: "FIXED_INCOME_COMPOSITION_V1",
  },
  benchmark: { cbr_hurdle_annual: 0.18, note_ru: "Ставка ЦБ ≠ депозит." },
  decision_quality: {
    equity_confidence_label_ru: "Недостаточно данных",
    equity_confidence_reason_ru: "Мало зрелых прогнозов",
  },
  level_explanations: {
    level_1_ru: "Kraken ограничил акции до 25%.",
    level_2_ru: "Мало зрелых прогнозов",
  },
  diff: {
    has_previous: true,
    summary_ru: "Изменения относительно прошлого кандидата.",
    changes: [
      { kind: "position_added", symbol: "SBER", text_ru: "Позиция SBER добавлена." },
      { kind: "lots_changed", symbol: "SU26238RMFS4", text_ru: "SU26238RMFS4: 5 → 6 лот(ов)." },
    ],
  },
  empty_states: {},
};

vi.mock("../api/investment", () => ({
  previewPortfolioCandidate: vi.fn(async () => sample),
  createPortfolioCandidateSnapshot: vi.fn(async () => ({ ...sample, persisted: true })),
}));

describe("PortfolioCandidatePage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders concrete ticker composition and rejected block", async () => {
    render(
      <MemoryRouter>
        <HelpProvider>
          <PortfolioCandidatePage />
        </HelpProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Кандидат портфеля Kraken")).toBeInTheDocument();
    expect(screen.getByText(/Исследовательский режим/)).toBeInTheDocument();
    expect(screen.getByText(/2 позиций/)).toBeInTheDocument();
    expect(screen.getByText("Сбербанк")).toBeInTheDocument();
    expect(screen.getByText("SBER")).toBeInTheDocument();
    expect(screen.getByText("ОФЗ 26238")).toBeInTheDocument();
    expect(screen.getByText("ОФЗ")).toBeInTheDocument();
    expect(screen.getAllByText("Только исследование").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Кредитное качество не подтверждено")).toBeInTheDocument();
    expect(screen.getByText("Что Kraken не включил")).toBeInTheDocument();
    expect(screen.getByText(/Кредитное качество неизвестно/)).toBeInTheDocument();
    expect(screen.getByText("Позиция SBER добавлена.")).toBeInTheDocument();
    expect(screen.queryByText("EQUITY_SLEEVE")).not.toBeInTheDocument();
    expect(screen.queryByText(/Купить/i)).not.toBeInTheDocument();
  });
});
