import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as shadowApi from "../../api/shadow";
import type {
  ShadowCandidateHistoryResponse,
  ShadowJournalDay,
  ShadowJournalResponse,
} from "../../api/shadow";
import {
  JOURNAL_MISSING_REASON_RU,
  journalCandidateHumanReason,
} from "./decisionJournalCopy";
import { DecisionJournalPanel } from "./DecisionJournalPanel";

vi.mock("../../api/shadow");

const LEGACY_MSG = "Подробный decision trace для этой исторической версии не сохранялся.";

function baseDay(overrides?: Partial<ShadowJournalDay>): ShadowJournalDay {
  return {
    date: "2026-09-02",
    signal_as_of_date: "2026-09-02",
    decision: {
      id: 10,
      forward_batch_id: 1,
      signal_as_of_date: "2026-09-02",
      decision_at: "2026-09-04T14:15:29Z",
      iso_week: "2026-W36",
      risk_mode: "normal",
      exposure_cap: 1,
      policy_name: "RANK_HYSTERESIS_LONG_ONLY_V1",
      risk_name: "RISK_GUARDRAILS_V0",
      targets: [],
    },
    decision_ids: [10],
    risk_mode: "normal",
    nav: {
      as_of_date: "2026-09-02",
      cash: 500_000,
      market_value: 500_000,
      nav: 1_000_000,
      gross_exposure: 0.5,
      drawdown: 0,
      peak_nav: 1_000_000,
      position_count: 2,
    },
    detail_available: true,
    message_ru: null,
    candidates: [],
    orders: [],
    fills: [],
    counts: {
      buy: 0,
      sell: 0,
      hold: 0,
      review: 0,
      candidates_reviewed: 0,
      orders: 0,
      fills: 0,
    },
    total_modeled_costs: { commission: 0, slippage_cost: 0, total: 0 },
    ...overrides,
  };
}

function journalPayload(overrides?: Partial<ShadowJournalResponse>): ShadowJournalResponse {
  return {
    portfolio_id: 3,
    date_from: null,
    date_to: null,
    limit: 60,
    ticker: null,
    action: null,
    returned_days: 2,
    truncated: false,
    order: "asc_by_date",
    days: [
      baseDay({
        candidates: [
          {
            ticker: "SBER",
            rank: 2,
            decision_action: "ENTER",
            reason_codes: ["TOP_ENTRY_BAND"],
            net_edge: 0.04,
            target_weight: 0.1,
          },
          {
            ticker: "GAZP",
            rank: 25,
            decision_action: "REVIEW_HOLD",
            reason_codes: ["EXIT_BAND_INSUFFICIENT_EDGE"],
            replacement_ticker: "SBER",
            net_edge: -0.01,
            review_trigger: true,
          },
        ],
        orders: [
          {
            id: 101,
            decision_id: 10,
            instrument_id: 1,
            ticker: "SBER",
            side: "BUY",
            quantity: 10,
            target_weight: 0.1,
            target_notional: 50_000,
            status: "FILLED",
            min_execution_date: "2026-09-03",
            execution_date: "2026-09-03",
          },
        ],
        fills: [],
        counts: {
          buy: 1,
          sell: 0,
          hold: 0,
          review: 1,
          candidates_reviewed: 2,
          orders: 1,
          fills: 0,
        },
      }),
      baseDay({
        date: "2026-09-03",
        signal_as_of_date: null,
        decision: null,
        decision_ids: [],
        risk_mode: null,
        nav: {
          as_of_date: "2026-09-03",
          cash: 450_000,
          market_value: 551_000,
          nav: 1_001_000,
          gross_exposure: 0.55,
          drawdown: 0,
          peak_nav: 1_001_000,
          position_count: 1,
        },
        detail_available: false,
        message_ru: null,
        candidates: [],
        orders: [],
        fills: [
          {
            id: 201,
            order_id: 101,
            instrument_id: 1,
            ticker: "SBER",
            side: "BUY",
            quantity: 10,
            raw_open: 250,
            fill_price: 250.5,
            notional: 2505,
            commission: 30,
            slippage_cost: 5,
            execution_date: "2026-09-03",
          },
        ],
        counts: {
          buy: 0,
          sell: 0,
          hold: 0,
          review: 0,
          candidates_reviewed: 0,
          orders: 0,
          fills: 1,
        },
        total_modeled_costs: { commission: 30, slippage_cost: 5, total: 35 },
      }),
    ],
    ...overrides,
  };
}

function historyPayload(
  overrides?: Partial<ShadowCandidateHistoryResponse>,
): ShadowCandidateHistoryResponse {
  return {
    portfolio_id: 3,
    ticker: "GAZP",
    detail_available: true,
    message_ru: null,
    returned_events: 2,
    truncated: false,
    order: "asc_by_signal_date",
    events: [
      {
        decision_id: 10,
        iso_week: "2026-W36",
        signal_as_of_date: "2026-09-02",
        action: "REVIEW_HOLD",
        rank: 25,
        reason_codes: ["EXIT_BAND_INSUFFICIENT_EDGE"],
        replacement_ticker: "SBER",
        net_edge: -0.01,
        detail_available: true,
        message_ru: null,
        order: null,
        fill: null,
      },
      {
        decision_id: 11,
        iso_week: "2026-W37",
        signal_as_of_date: "2026-09-09",
        action: "ROTATE",
        rank: 30,
        reason_codes: ["NET_EDGE_POSITIVE"],
        replacement_ticker: "ROSN",
        net_edge: 0.03,
        detail_available: true,
        message_ru: null,
        order: {
          id: 110,
          decision_id: 11,
          instrument_id: 303,
          ticker: "GAZP",
          side: "SELL",
          quantity: 20,
          target_weight: 0,
          target_notional: 0,
          status: "FILLED",
          min_execution_date: "2026-09-10",
          execution_date: "2026-09-10",
        },
        fill: {
          id: 210,
          order_id: 110,
          instrument_id: 303,
          ticker: "GAZP",
          side: "SELL",
          quantity: 20,
          raw_open: 160,
          fill_price: 159.5,
          notional: 3190,
          commission: 40,
          slippage_cost: 8,
          execution_date: "2026-09-10",
        },
      },
    ],
    summary: { first_seen: "2026-09-02", last_seen: "2026-09-09", event_count: 2 },
    ...overrides,
  };
}

async function expandDay(date: string) {
  const day = await screen.findByTestId(`shadow-journal-day-${date}`);
  fireEvent.click(within(day).getByTestId("shadow-journal-day-toggle"));
  expect(within(day).getByTestId("shadow-journal-day-expanded")).toBeInTheDocument();
  return day;
}

describe("DecisionJournalPanel V4", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(journalPayload());
    vi.mocked(shadowApi.getShadowCandidateHistory).mockResolvedValue(historyPayload());
  });

  it("loads journal days grouped by date with closed CTA", async () => {
    render(<DecisionJournalPanel portfolioId={3} portfolioLabel="Рейтинговый портфель" />);
    expect(await screen.findByTestId("shadow-decision-journal")).toBeInTheDocument();
    expect(screen.getByTestId("shadow-journal-portfolio-id")).toHaveTextContent("3");
    const day = screen.getByTestId("shadow-journal-day-2026-09-02");
    expect(within(day).getByTestId("shadow-journal-day-toggle")).toHaveTextContent(/Детали решения/);
    expect(within(day).getByTestId("shadow-journal-day-tickers")).toHaveTextContent("SBER");
    expect(within(day).getByTestId("shadow-journal-counts")).toHaveTextContent(/BUY 1/);
    expect(within(day).queryByTestId("shadow-journal-day-expanded")).not.toBeInTheDocument();
  });

  it("expands A/B/C/D blocks with BUY/SELL/HOLD/REVIEW human reasons", async () => {
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(
      journalPayload({
        days: [
          baseDay({
            candidates: [
              {
                ticker: "SBER",
                decision_action: "BUY",
                reason_codes: ["TOP_ENTRY_BAND"],
                net_edge: 0.02,
              },
              {
                ticker: "LKOH",
                decision_action: "SELL",
                reason_codes: ["RISK_FORCED_EXIT"],
              },
              {
                ticker: "ROSN",
                decision_action: "HOLD",
                reason_codes: ["WITHIN_POLICY_SELECTION"],
              },
              {
                ticker: "GAZP",
                decision_action: "REVIEW_HOLD",
                reason_codes: ["EXIT_BAND_INSUFFICIENT_EDGE"],
                replacement_ticker: "SBER",
              },
            ],
            counts: {
              buy: 1,
              sell: 1,
              hold: 1,
              review: 1,
              candidates_reviewed: 4,
              orders: 0,
              fills: 0,
            },
          }),
        ],
        returned_days: 1,
      }),
    );

    render(<DecisionJournalPanel portfolioId={3} />);
    const day = await expandDay("2026-09-02");
    expect(within(day).getByTestId("shadow-journal-block-a")).toHaveTextContent(/Что знал Kraken/);
    expect(within(day).getByTestId("shadow-journal-block-b")).toHaveTextContent(/Что решил/);
    expect(within(day).getByTestId("shadow-journal-block-c")).toHaveTextContent(/Почему/);
    expect(within(day).getByTestId("shadow-journal-block-d")).toHaveTextContent(/Что произошло/);

    expect(within(day).getByTestId("shadow-journal-human-reason-SBER")).toHaveTextContent(/Покупка/i);
    expect(within(day).getByTestId("shadow-journal-human-reason-SBER")).toHaveTextContent(
      /зоне входа/i,
    );
    expect(within(day).getByTestId("shadow-journal-human-reason-LKOH")).toHaveTextContent(/Продажа/i);
    expect(within(day).getByTestId("shadow-journal-human-reason-ROSN")).toHaveTextContent(
      /Удержание/i,
    );
    expect(within(day).getByTestId("shadow-journal-human-reason-GAZP")).toHaveTextContent(
      /Ревизия: позиция удержана/i,
    );
  });

  it("shows no-orders state and pending order without inventing fills", async () => {
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(
      journalPayload({
        days: [
          baseDay({
            candidates: [{ ticker: "SBER", decision_action: "HOLD", reason_codes: ["WITHIN_POLICY_SELECTION"] }],
            orders: [],
            fills: [],
            counts: {
              buy: 0,
              sell: 0,
              hold: 1,
              review: 0,
              candidates_reviewed: 1,
              orders: 0,
              fills: 0,
            },
          }),
          baseDay({
            date: "2026-09-04",
            candidates: [{ ticker: "SBER", decision_action: "BUY", reason_codes: ["TOP_ENTRY_BAND"] }],
            orders: [
              {
                id: 501,
                decision_id: 10,
                instrument_id: 1,
                ticker: "SBER",
                side: "BUY",
                quantity: 5,
                target_weight: 0.05,
                target_notional: 25_000,
                status: "PENDING",
                min_execution_date: "2026-09-05",
                execution_date: null,
              },
            ],
            fills: [],
            counts: {
              buy: 1,
              sell: 0,
              hold: 0,
              review: 0,
              candidates_reviewed: 1,
              orders: 1,
              fills: 0,
            },
          }),
        ],
        returned_days: 2,
      }),
    );

    render(<DecisionJournalPanel portfolioId={3} />);
    const holdDay = await expandDay("2026-09-02");
    expect(within(holdDay).getByTestId("shadow-journal-no-orders")).toHaveTextContent(
      /Сделок и ордеров за этот день нет/,
    );

    const pendingDay = await expandDay("2026-09-04");
    expect(within(pendingDay).getByTestId("shadow-journal-order-501")).toBeInTheDocument();
    expect(within(pendingDay).getByTestId("shadow-journal-pending-501")).toHaveTextContent(/Pending/i);
    expect(within(pendingDay).queryByTestId(/shadow-journal-fill-/)).not.toBeInTheDocument();
  });

  it("links partial fills by real order_id only", async () => {
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(
      journalPayload({
        days: [
          baseDay({
            orders: [
              {
                id: 101,
                decision_id: 10,
                instrument_id: 1,
                ticker: "SBER",
                side: "BUY",
                quantity: 10,
                target_weight: 0.1,
                target_notional: 50_000,
                status: "PARTIAL",
                min_execution_date: "2026-09-03",
                execution_date: "2026-09-03",
              },
            ],
            fills: [
              {
                id: 201,
                order_id: 101,
                instrument_id: 1,
                ticker: "SBER",
                side: "BUY",
                quantity: 4,
                raw_open: 250,
                fill_price: 250.5,
                notional: 1002,
                commission: 10,
                slippage_cost: 2,
                execution_date: "2026-09-03",
              },
            ],
            counts: {
              buy: 1,
              sell: 0,
              hold: 0,
              review: 0,
              candidates_reviewed: 0,
              orders: 1,
              fills: 1,
            },
            total_modeled_costs: { commission: 10, slippage_cost: 2, total: 12 },
          }),
        ],
        returned_days: 1,
      }),
    );

    render(<DecisionJournalPanel portfolioId={3} />);
    const day = await expandDay("2026-09-02");
    const order = within(day).getByTestId("shadow-journal-order-101");
    expect(order).toHaveTextContent(/#10/);
    expect(order).toHaveTextContent(/#101/);
    expect(within(day).getByTestId("shadow-journal-fill-201")).toHaveTextContent(/4 @/);
    expect(within(day).queryByTestId("shadow-journal-pending-101")).not.toBeInTheDocument();
  });

  it("shows missing-reason copy for empty traces", async () => {
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(
      journalPayload({
        days: [
          baseDay({
            detail_available: false,
            message_ru: null,
            decision: {
              id: 1,
              forward_batch_id: 1,
              signal_as_of_date: "2026-09-02",
              iso_week: "2026-W36",
            },
            candidates: [],
            orders: [],
            fills: [],
          }),
        ],
        returned_days: 1,
      }),
    );

    render(<DecisionJournalPanel portfolioId={3} />);
    const day = await expandDay("2026-09-02");
    expect(within(day).getByTestId("shadow-journal-missing-reason")).toHaveTextContent(
      JOURNAL_MISSING_REASON_RU,
    );
  });

  it("hides NAV when missing and does not invent DD anomaly from magnitude alone", async () => {
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(
      journalPayload({
        days: [
          baseDay({
            nav: null,
            candidates: [{ ticker: "SBER", decision_action: "HOLD" }],
          }),
          baseDay({
            date: "2026-09-05",
            nav: {
              as_of_date: "2026-09-05",
              cash: 1,
              market_value: 1,
              nav: 2,
              gross_exposure: 0.5,
              drawdown: 0.99,
              peak_nav: 100,
              position_count: 1,
            },
            candidates: [{ ticker: "SBER", decision_action: "HOLD" }],
          }),
        ],
        returned_days: 2,
      }),
    );

    render(<DecisionJournalPanel portfolioId={3} />);
    const missing = await screen.findByTestId("shadow-journal-day-2026-09-02");
    expect(within(missing).getByTestId("shadow-journal-day-nav-missing")).toBeInTheDocument();

    const largeDd = screen.getByTestId("shadow-journal-day-2026-09-05");
    expect(within(largeDd).getByTestId("shadow-journal-day-nav")).toBeInTheDocument();
    expect(within(largeDd).queryByTestId("shadow-journal-dd-warning")).not.toBeInTheDocument();
  });

  it("shows DD warning and LIVE vs counterfactual only when metadata fields exist", async () => {
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(
      journalPayload({
        days: [
          {
            ...baseDay({
              candidates: [{ ticker: "SBER", decision_action: "BUY", reason_codes: ["TOP_ENTRY_BAND"] }],
            }),
            history_kind: "LIVE",
            valuation_freshness: "FRESH",
            drawdown_quality: "LIMITED",
          } as ShadowJournalDay,
          {
            ...baseDay({
              date: "2026-09-06",
              candidates: [{ ticker: "GAZP", decision_action: "HOLD" }],
            }),
            history_kind: "COUNTERFACTUAL_REPLAY",
            valuation_freshness: "STALE",
          } as ShadowJournalDay,
        ],
        returned_days: 2,
      }),
    );

    render(<DecisionJournalPanel portfolioId={3} />);
    const liveDay = await screen.findByTestId("shadow-journal-day-2026-09-02");
    expect(within(liveDay).getByTestId("shadow-journal-history-kind")).toHaveTextContent(/LIVE/i);
    expect(within(liveDay).getByTestId("shadow-journal-valuation-freshness")).toHaveTextContent(
      /свежая/i,
    );
    expect(within(liveDay).getByTestId("shadow-journal-dd-warning")).toBeInTheDocument();

    const replayDay = screen.getByTestId("shadow-journal-day-2026-09-06");
    expect(within(replayDay).getByTestId("shadow-journal-history-kind")).toHaveTextContent(
      /реконструкция/i,
    );

    await expandDay("2026-09-02");
    expect(within(liveDay).getByTestId("shadow-journal-block-a-provenance")).toHaveTextContent(/LIVE/i);
    expect(within(liveDay).getByTestId("shadow-journal-dd-warning-body")).toHaveTextContent(
      /метаданных/i,
    );
  });

  it("ignores outdated journal responses on rapid portfolio/filter change", async () => {
    let resolveSlow!: (v: ShadowJournalResponse) => void;
    const slow = new Promise<ShadowJournalResponse>((resolve) => {
      resolveSlow = resolve;
    });

    vi.mocked(shadowApi.getShadowJournal).mockImplementation((id, query) => {
      if (String(id) === "3" && !query?.ticker) return slow;
      return Promise.resolve(
        journalPayload({
          portfolio_id: Number(id),
          ticker: query?.ticker ?? null,
          days: [
            baseDay({
              date: "2026-09-20",
              candidates: [{ ticker: query?.ticker ?? "OK", decision_action: "HOLD" }],
            }),
          ],
          returned_days: 1,
        }),
      );
    });

    const { rerender } = render(<DecisionJournalPanel portfolioId={3} />);
    expect(await screen.findByTestId("shadow-journal-loading")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("shadow-journal-ticker"), { target: { value: "GAZP" } });
    fireEvent.click(screen.getByTestId("shadow-journal-apply"));

    expect(await screen.findByTestId("shadow-journal-day-2026-09-20")).toBeInTheDocument();
    expect(screen.getByTestId("shadow-journal-day-tickers")).toHaveTextContent("GAZP");

    // Late slow response for the first request must not overwrite filtered result.
    resolveSlow(journalPayload({ portfolio_id: 3 }));
    await waitFor(() => {
      expect(screen.queryByTestId("shadow-journal-day-2026-09-02")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("shadow-journal-day-2026-09-20")).toBeInTheDocument();

    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(
      journalPayload({
        portfolio_id: 9,
        days: [baseDay({ date: "2026-09-30", candidates: [{ ticker: "VTBR", decision_action: "HOLD" }] })],
        returned_days: 1,
      }),
    );
    rerender(<DecisionJournalPanel key="9" portfolioId={9} />);
    expect(await screen.findByTestId("shadow-journal-portfolio-id")).toHaveTextContent("9");
    expect(await screen.findByTestId("shadow-journal-day-2026-09-30")).toBeInTheDocument();
    expect(screen.queryByTestId("shadow-journal-day-2026-09-20")).not.toBeInTheDocument();
  });

  it("exposes keyboard-accessible CTA button (Enter/Space activate native button)", async () => {
    render(<DecisionJournalPanel portfolioId={3} />);
    const day = await screen.findByTestId("shadow-journal-day-2026-09-02");
    const toggle = within(day).getByTestId("shadow-journal-day-toggle");
    expect(toggle.tagName).toBe("BUTTON");
    expect(toggle).toHaveAttribute("type", "button");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls");
    // Native <button> is activated by Enter/Space in browsers; jsdom exercises the handler via click.
    fireEvent.keyDown(toggle, { key: "Enter", code: "Enter" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(day).getByTestId("shadow-journal-day-expanded")).toBeInTheDocument();
    fireEvent.keyDown(toggle, { key: " ", code: "Space" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("formats money/percent and opens candidate drill-down with ROTATE copy", async () => {
    render(<DecisionJournalPanel portfolioId={3} />);
    const day = await expandDay("2026-09-02");
    expect(within(day).getByTestId("shadow-journal-day-nav")).toHaveTextContent(/1[\s\u00a0]?000[\s\u00a0]?000/);
    fireEvent.click(within(day).getByTestId("shadow-journal-drill-GAZP"));
    expect(await screen.findByTestId("shadow-journal-candidate-history")).toBeInTheDocument();
    expect(shadowApi.getShadowCandidateHistory).toHaveBeenCalledWith(
      3,
      "GAZP",
      100,
      expect.any(AbortSignal),
    );
    expect(screen.getByTestId("shadow-journal-event-reason-2026-09-09")).toHaveTextContent(
      /Ротация на ROSN/i,
    );
  });

  it("shows legacy message when detail_available=false and message_ru provided", async () => {
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(
      journalPayload({
        portfolio_id: 4,
        days: [
          baseDay({
            nav: null,
            detail_available: false,
            message_ru: LEGACY_MSG,
            candidates: [],
            orders: [
              {
                id: 1,
                decision_id: 1,
                instrument_id: 1,
                ticker: "SBER",
                side: "BUY",
                quantity: 10,
                target_weight: 0.1,
                target_notional: 50_000,
                status: "FILLED",
                min_execution_date: "2026-09-03",
                execution_date: "2026-09-03",
              },
            ],
            counts: {
              buy: 1,
              sell: 0,
              hold: 0,
              review: 0,
              candidates_reviewed: 0,
              orders: 1,
              fills: 0,
            },
          }),
        ],
        returned_days: 1,
      }),
    );
    render(<DecisionJournalPanel portfolioId={4} />);
    const day = await expandDay("2026-09-02");
    expect(within(day).getByTestId("shadow-journal-legacy-message")).toHaveTextContent(LEGACY_MSG);
  });

  it("applies ticker/action filters to API request", async () => {
    render(<DecisionJournalPanel portfolioId={3} />);
    await screen.findByTestId("shadow-decision-journal");
    fireEvent.change(screen.getByTestId("shadow-journal-ticker"), { target: { value: "gazp" } });
    fireEvent.change(screen.getByTestId("shadow-journal-action"), { target: { value: "REVIEW" } });
    fireEvent.click(screen.getByTestId("shadow-journal-apply"));
    await waitFor(() => {
      expect(shadowApi.getShadowJournal).toHaveBeenLastCalledWith(
        3,
        expect.objectContaining({ ticker: "GAZP", action: "REVIEW", limit: 60 }),
        expect.any(AbortSignal),
      );
    });
  });

  it("maps BUY/SELL/HOLD copy without inventing facts", () => {
    expect(
      journalCandidateHumanReason({
        action: "BUY",
        reason_codes: ["TOP_ENTRY_BAND"],
        net_edge: 0.01,
      }),
    ).toMatch(/Покупка:.*зоне входа/i);
    expect(journalCandidateHumanReason({ action: "SELL", reason_codes: [] })).toBe("Продажа.");
    expect(
      journalCandidateHumanReason({
        action: "HOLD",
        reason_codes: ["WITHIN_POLICY_SELECTION"],
      }),
    ).toMatch(/Удержание позиции/i);
  });

  it("does not invent ROTATE edge or claim REVIEW means HOLD without confirmation", () => {
    expect(journalCandidateHumanReason({ action: "ROTATE", reason_codes: [] })).toBe("Ротация.");
    expect(journalCandidateHumanReason({ action: "ROTATE", reason_codes: [] })).not.toMatch(/edge/i);
    expect(
      journalCandidateHumanReason({
        action: "ROTATE",
        reason_codes: ["NET_EDGE_POSITIVE"],
        replacement_ticker: "ROSN",
      }),
    ).toMatch(/Ротация на ROSN:.*edge/i);
    expect(journalCandidateHumanReason({ action: "REVIEW", reason_codes: [] })).toBe("Ревизия.");
    expect(journalCandidateHumanReason({ action: "REVIEW", reason_codes: [] })).not.toMatch(
      /удержан/i,
    );
    expect(
      journalCandidateHumanReason({
        action: "REVIEW",
        reason_codes: ["REVIEW_TRIGGER"],
      }),
    ).toMatch(/^Ревизия:/);
    expect(
      journalCandidateHumanReason({
        action: "REVIEW_HOLD",
        reason_codes: ["EXIT_BAND_INSUFFICIENT_EDGE"],
      }),
    ).toMatch(/позиция удержана/i);
  });

  it("treats FILLED/CANCELLED/REJECTED without same-day fills as non-pending", async () => {
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(
      journalPayload({
        days: [
          baseDay({
            date: "2026-09-10",
            candidates: [{ ticker: "SBER", decision_action: "BUY", reason_codes: ["TOP_ENTRY_BAND"] }],
            orders: [
              {
                id: 701,
                decision_id: 10,
                instrument_id: 1,
                ticker: "SBER",
                side: "BUY",
                quantity: 3,
                target_weight: 0.03,
                target_notional: 15_000,
                status: "FILLED",
                min_execution_date: "2026-09-11",
                execution_date: "2026-09-11",
              },
              {
                id: 702,
                decision_id: 10,
                instrument_id: 2,
                ticker: "LKOH",
                side: "SELL",
                quantity: 1,
                target_weight: 0,
                target_notional: 0,
                status: "CANCELLED",
                min_execution_date: "2026-09-11",
                execution_date: null,
              },
              {
                id: 703,
                decision_id: 10,
                instrument_id: 3,
                ticker: "GAZP",
                side: "BUY",
                quantity: 2,
                target_weight: 0.02,
                target_notional: 10_000,
                status: "REJECTED",
                min_execution_date: "2026-09-11",
                execution_date: null,
              },
              {
                id: 704,
                decision_id: 10,
                instrument_id: 1,
                ticker: "ROSN",
                side: "BUY",
                quantity: 1,
                target_weight: 0.01,
                target_notional: 5_000,
                status: "PENDING",
                min_execution_date: "2026-09-11",
                execution_date: null,
              },
            ],
            fills: [],
            counts: {
              buy: 3,
              sell: 1,
              hold: 0,
              review: 0,
              candidates_reviewed: 1,
              orders: 4,
              fills: 0,
            },
          }),
        ],
        returned_days: 1,
      }),
    );

    render(<DecisionJournalPanel portfolioId={3} />);
    const day = await expandDay("2026-09-10");
    expect(within(day).queryByTestId("shadow-journal-pending-701")).not.toBeInTheDocument();
    expect(within(day).queryByTestId("shadow-journal-pending-702")).not.toBeInTheDocument();
    expect(within(day).queryByTestId("shadow-journal-pending-703")).not.toBeInTheDocument();
    expect(within(day).getByTestId("shadow-journal-order-outcome-701")).toHaveTextContent(/FILLED/);
    expect(within(day).getByTestId("shadow-journal-order-outcome-702")).toHaveTextContent(/CANCELLED/);
    expect(within(day).getByTestId("shadow-journal-order-outcome-703")).toHaveTextContent(/REJECTED/);
    expect(within(day).getByTestId("shadow-journal-pending-704")).toHaveTextContent(/Pending/i);
  });
});
