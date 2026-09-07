import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HelpProvider } from "../help";
import { PortfolioCandidatePage } from "./PortfolioCandidatePage";

const sample = {
  candidate_id: "pc_demo",
  version: "PORTFOLIO_CANDIDATE_V1",
  as_of: "2026-09-05",
  generated_at: "2026-09-07T10:00:00+00:00",
  capital: "100000",
  currency: "RUB",
  status: "READY_FOR_RESEARCH",
  readiness: {
    mode_ru: "Исследовательский режим",
    ready_for_real_money: false,
    banner_ru: "Не готов для автоматического использования реальных денег.",
    reasons_ru: ["Equity confidence: Недостаточно данных", "Taxes: не моделируются"],
  },
  allocation: {
    equity: { target_weight: 0.25, actual_weight: 0.24, target_rub: "25000", actual_rub: "24012" },
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
      symbol: "EQUITY_SLEEVE",
      display_name: "Акции (research sleeve)",
      sleeve: "EQUITY_ALPHA",
      asset_class: "equity",
      lots: 8,
      units: 80,
      reference_price: "300",
      estimated_notional: "24000",
      estimated_fees: "12",
      target_weight: 0.25,
      actual_weight: 0.24,
      risk_status: "RESEARCH_ONLY",
      executable: false,
      reason_ru: "Доля акций ограничена калибровкой.",
      warnings_ru: [],
      confidence_label_ru: "Недостаточно данных",
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
    invested: "87744",
    fees: "44",
    strategic_cash: "10000",
    lot_remainder: "2256",
    ending_preview_cash: "12256",
    tax_note_ru: "До налогов.",
    broker_note_ru: "Исследовательский профиль издержек.",
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
  diff: { has_previous: false, summary_ru: "Это первый сохранённый кандидат портфеля.", changes: [] },
  empty_states: {},
};

vi.mock("../api/investment", () => ({
  previewPortfolioCandidate: vi.fn(async () => sample),
  createPortfolioCandidateSnapshot: vi.fn(async () => ({ ...sample, persisted: true })),
}));

describe("PortfolioCandidatePage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders candidate cockpit hero and rejected block", async () => {
    render(
      <MemoryRouter>
        <HelpProvider>
          <PortfolioCandidatePage />
        </HelpProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Кандидат портфеля Kraken")).toBeInTheDocument();
    expect(screen.getByText(/Исследовательский режим/)).toBeInTheDocument();
    expect(screen.getByText("Что Kraken не включил")).toBeInTheDocument();
    expect(screen.getByText(/Кредитное качество неизвестно/)).toBeInTheDocument();
    expect(screen.getByText("Недостаточно данных")).toBeInTheDocument();
  });
});
