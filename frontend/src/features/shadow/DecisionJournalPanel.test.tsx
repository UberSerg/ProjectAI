import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as shadowApi from "../../api/shadow";
import type { ShadowJournalDay, ShadowJournalResponse } from "../../api/shadow";
import {
  dayClosedHeadline,
  dayWhatHappenedSummary,
  instrumentResultLabel,
  journalCandidateHumanReason,
  journalOrderStatusLabel,
} from "./decisionJournalCopy";
import { DecisionJournalPanel } from "./DecisionJournalPanel";

vi.mock("../../api/shadow");

const PARTIAL_MSG =
  "Для решений этого периода не сохранялось подробное обоснование отбора каждой бумаги. При этом сохранились состав заявок и параметры стратегии. Ниже показаны доступные факты.";

function baseDay(overrides?: Partial<ShadowJournalDay>): ShadowJournalDay {
  return {
    date: "2026-09-03",
    signal_as_of_date: "2026-09-03",
    decision: {
      id: 3,
      forward_batch_id: 1,
      signal_as_of_date: "2026-09-03",
      decision_at: "2026-09-07T13:38:24.403001+00:00",
      iso_week: "2026-W36",
      risk_mode: "normal",
      exposure_cap: 1,
      policy_name: "RANK_HYSTERESIS_LONG_ONLY_V1",
      risk_name: "RISK_GUARDRAILS_V0",
      targets: [{ ticker: "MGNT", rank: 1, action: "ENTER_TOP20" }],
    },
    decision_ids: [3],
    risk_mode: "normal",
    nav: null,
    detail_available: false,
    evidence_level: "PARTIAL",
    message_ru: PARTIAL_MSG,
    recorded_facts: {
      evidence_level: "PARTIAL",
      has_candidate_traces: false,
      targets: [{ ticker: "MGNT", rank: 1, action: "ENTER_TOP20" }],
      order_plan_rows: [],
      policy_name: "RANK_HYSTERESIS_LONG_ONLY_V1",
      risk_name: "RISK_GUARDRAILS_V0",
      order_reasons: ["ENTER_TOP20"],
    },
    candidates: [],
    orders: [
      {
        id: 19,
        decision_id: 3,
        instrument_id: 53,
        ticker: "MGNT",
        side: "BUY",
        quantity: 70,
        target_weight: 0.11,
        target_notional: 110000,
        reason: "ENTER_TOP20",
        status: "FILLED",
        decision_at: "2026-09-07T13:38:24.403001+00:00",
        execution_date: "2026-09-08",
        has_confirmed_fill: true,
        execution_timing: "later",
        fills: [
          {
            id: 17,
            order_id: 19,
            instrument_id: 53,
            ticker: "MGNT",
            side: "BUY",
            quantity: 70,
            raw_open: 1690,
            fill_price: 1698.5,
            notional: 118895,
            commission: 0,
            slippage_cost: 0,
            execution_date: "2026-09-08",
            filled_at: "2026-09-08T06:29:46.101364+00:00",
          },
        ],
      },
      {
        id: 27,
        decision_id: 3,
        instrument_id: 1,
        ticker: "AFLT",
        side: "BUY",
        quantity: 3530,
        target_weight: 0.11,
        target_notional: 100000,
        reason: "ENTER_TOP20",
        status: "CANCELLED",
        has_confirmed_fill: false,
        execution_timing: "none",
        fills: [],
      },
    ],
    fills: [],
    counts: {
      buy: 2,
      sell: 0,
      hold: 0,
      review: 0,
      candidates_reviewed: 0,
      orders: 2,
      buy_orders: 2,
      sell_orders: 0,
      filled_orders: 1,
      cancelled_orders: 1,
      pending_orders: 0,
      rejected_orders: 0,
      fill_records: 1,
      fills: 1,
    },
    total_modeled_costs: { commission: 0, slippage_cost: 0, total: 0 },
    ...overrides,
  };
}

function journalPayload(days: ShadowJournalDay[]): ShadowJournalResponse {
  return {
    portfolio_id: 5,
    date_from: null,
    date_to: null,
    limit: 60,
    ticker: null,
    action: null,
    returned_days: days.length,
    truncated: false,
    order: "asc_by_date",
    days,
  };
}

describe("decisionJournalCopy V4.1", () => {
  it("russifies order statuses without inventing meaning", () => {
    expect(journalOrderStatusLabel("FILLED")).toBe("Исполнено");
    expect(journalOrderStatusLabel("CANCELLED")).toBe("Отменено");
    expect(journalOrderStatusLabel("WEIRD")).toBe("Статус не определён");
  });

  it("builds closed headline from buy orders", () => {
    expect(dayClosedHeadline(baseDay())).toBe("Kraken сформировал 2 заявки на покупку");
  });

  it("summarizes later fills without claiming foresight wording as fact invention", () => {
    const text = dayWhatHappenedSummary(baseDay());
    expect(text).toContain("покупку");
    expect(text).toContain("позднее");
    expect(text).not.toContain("FILLED");
  });

  it("labels instrument results from confirmed fills", () => {
    const day = baseDay();
    expect(instrumentResultLabel(day.orders[0]!).label).toBe("Исполнено позднее");
    expect(instrumentResultLabel(day.orders[1]!).label).toBe("Отменено");
  });

  it("does not invent HOLD from bare REVIEW", () => {
    expect(journalCandidateHumanReason({ action: "REVIEW" })).toBe("Ревизия.");
    expect(journalCandidateHumanReason({ action: "REVIEW" })).not.toMatch(/удерж/i);
  });
});

describe("DecisionJournalPanel V4.1", () => {
  beforeEach(() => {
    vi.mocked(shadowApi.getShadowJournal).mockReset();
    vi.mocked(shadowApi.getShadowCandidateHistory).mockReset();
  });

  it("renders human closed card without decorative BUY 0 badges or English FILLED", async () => {
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(journalPayload([baseDay()]));
    render(<DecisionJournalPanel portfolioId={5} portfolioLabel="Рейтинговый" />);

    await waitFor(() => {
      expect(screen.getByTestId("shadow-journal-day-2026-09-03")).toBeInTheDocument();
    });
    const card = screen.getByTestId("shadow-journal-day-2026-09-03");
    expect(within(card).getByTestId("shadow-journal-day-headline")).toHaveTextContent(/заявк/i);
    expect(within(card).getByTestId("shadow-journal-counts")).toHaveTextContent("Заявки");
    expect(within(card).getByTestId("shadow-journal-day-nav-missing")).toHaveTextContent(
      /Общая стоимость портфеля/i,
    );
    expect(card.textContent).not.toMatch(/\bBUY 0\b/);
    expect(card.textContent).not.toMatch(/\bFILLED\b/);
    expect(card.textContent).not.toMatch(/Decision #/);
  });

  it("expands day into summary, instruments, why — later fill is Исполнено позднее", async () => {
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(journalPayload([baseDay()]));
    render(<DecisionJournalPanel portfolioId={5} ownerMode />);

    await waitFor(() => screen.getByTestId("shadow-journal-day-expand"));
    fireEvent.click(screen.getByTestId("shadow-journal-day-expand"));

    expect(screen.getByTestId("shadow-journal-day-summary").textContent).toMatch(/позднее/i);
    expect(screen.getByTestId("shadow-journal-block-instruments")).toHaveTextContent("MGNT");
    expect(screen.getByTestId("shadow-journal-block-instruments")).toHaveTextContent(
      "Исполнено позднее",
    );
    expect(screen.getByTestId("shadow-journal-block-instruments")).toHaveTextContent("Отменено");
    expect(screen.getByTestId("shadow-journal-missing-reason")).toHaveTextContent(/не сохранялось/i);

    fireEvent.click(screen.getByTestId("shadow-journal-instr-toggle-MGNT"));
    expect(screen.getByTestId("shadow-journal-instr-detail-MGNT")).toHaveTextContent("1 698,5");
    expect(screen.getByTestId("shadow-journal-instr-detail-MGNT")).toHaveTextContent(
      /исполнено позднее даты решения/i,
    );
    expect(screen.getByTestId("shadow-journal-block-tech")).toBeInTheDocument();
  });

  it("shows status_fill_mismatch without claiming Исполнено", async () => {
    const day = baseDay({
      orders: [
        {
          id: 99,
          decision_id: 3,
          instrument_id: 1,
          ticker: "SBER",
          side: "BUY",
          quantity: 10,
          target_weight: 0.1,
          target_notional: 1000,
          status: "FILLED",
          has_confirmed_fill: false,
          execution_timing: "status_fill_mismatch",
          fills: [],
        },
      ],
      counts: {
        buy: 1,
        sell: 0,
        hold: 0,
        review: 0,
        candidates_reviewed: 0,
        orders: 1,
        buy_orders: 1,
        filled_orders: 0,
        cancelled_orders: 0,
        pending_orders: 0,
        rejected_orders: 0,
        fill_records: 0,
      },
    });
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(journalPayload([day]));
    render(<DecisionJournalPanel portfolioId={5} />);
    await waitFor(() => screen.getByTestId("shadow-journal-day-expand"));
    fireEvent.click(screen.getByTestId("shadow-journal-day-expand"));
    expect(screen.getByTestId("shadow-journal-block-instruments")).toHaveTextContent(
      "Статус без исполнения",
    );
    expect(screen.getByTestId("shadow-journal-block-instruments").textContent).not.toMatch(
      /^Исполнено$/,
    );
  });
});
