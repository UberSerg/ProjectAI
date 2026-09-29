import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as shadowApi from "../../api/shadow";
import type {
  ShadowCandidateHistoryResponse,
  ShadowJournalResponse,
} from "../../api/shadow";
import { DecisionJournalPanel } from "./DecisionJournalPanel";

vi.mock("../../api/shadow");

const LEGACY_MSG = "Подробный decision trace для этой исторической версии не сохранялся.";

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
      {
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
        candidates: [
          {
            ticker: "SBER",
            rank: 2,
            decision_action: "ENTER",
            reason_codes: ["TOP_ENTRY_BAND"],
            net_edge: 0.04,
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
        total_modeled_costs: { commission: 0, slippage_cost: 0, total: 0 },
      },
      {
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
      },
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

describe("DecisionJournalPanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(journalPayload());
    vi.mocked(shadowApi.getShadowCandidateHistory).mockResolvedValue(historyPayload());
  });

  it("loads journal days grouped by date", async () => {
    render(<DecisionJournalPanel portfolioId={3} portfolioLabel="Рейтинговый портфель" />);
    expect(await screen.findByTestId("shadow-decision-journal")).toBeInTheDocument();
    expect(screen.getByTestId("shadow-journal-portfolio-id")).toHaveTextContent("3");
    expect(screen.getByTestId("shadow-journal-day-2026-09-02")).toBeInTheDocument();
    expect(screen.getByTestId("shadow-journal-day-2026-09-03")).toBeInTheDocument();
    expect(shadowApi.getShadowJournal).toHaveBeenCalledWith(
      3,
      expect.objectContaining({ limit: 60 }),
      expect.any(AbortSignal),
    );
  });

  it("expands day with counts, BUY/SELL table from real fills, and REVIEW_HOLD copy", async () => {
    render(<DecisionJournalPanel portfolioId={3} />);
    const day = await screen.findByTestId("shadow-journal-day-2026-09-02");
    fireEvent.click(within(day).getByTestId("shadow-journal-day-date"));
    expect(within(day).getByTestId("shadow-journal-counts")).toHaveTextContent(/BUY 1/);
    expect(within(day).getByTestId("shadow-journal-counts")).toHaveTextContent(/REVIEW 1/);
    expect(within(day).getByTestId("shadow-journal-human-reason-GAZP")).toHaveTextContent(
      /Ревизия: позиция удержана/i,
    );
    expect(within(day).getByTestId("shadow-journal-human-reason-GAZP")).toHaveTextContent(
      /нет достаточного чистого edge/i,
    );

    const fillDay = screen.getByTestId("shadow-journal-day-2026-09-03");
    fireEvent.click(within(fillDay).getByTestId("shadow-journal-day-date"));
    const tx = within(fillDay).getByTestId("shadow-journal-transactions");
    expect(tx).toHaveTextContent("SBER");
    expect(tx).toHaveTextContent("Покупка");
    expect(within(fillDay).getByTestId("shadow-journal-fill-201")).toBeInTheDocument();
  });

  it("opens candidate drill-down timeline with ROTATE copy", async () => {
    render(<DecisionJournalPanel portfolioId={3} />);
    const day = await screen.findByTestId("shadow-journal-day-2026-09-02");
    fireEvent.click(within(day).getByTestId("shadow-journal-day-date"));
    fireEvent.click(within(day).getByTestId("shadow-journal-drill-GAZP"));
    expect(await screen.findByTestId("shadow-journal-candidate-history")).toBeInTheDocument();
    expect(shadowApi.getShadowCandidateHistory).toHaveBeenCalledWith(
      3,
      "GAZP",
      100,
      expect.any(AbortSignal),
    );
    expect(screen.getByTestId("shadow-journal-timeline")).toBeInTheDocument();
    expect(screen.getByTestId("shadow-journal-event-reason-2026-09-09")).toHaveTextContent(
      /Ротация на ROSN/i,
    );
    expect(screen.getByTestId("shadow-journal-event-reason-2026-09-09")).toHaveTextContent(
      /положительный/i,
    );
  });

  it("shows legacy message when detail_available=false", async () => {
    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(
      journalPayload({
        portfolio_id: 4,
        days: [
          {
            date: "2026-09-02",
            signal_as_of_date: "2026-09-02",
            decision: {
              id: 1,
              forward_batch_id: 1,
              signal_as_of_date: "2026-09-02",
              iso_week: "2026-W36",
            },
            decision_ids: [1],
            risk_mode: "normal",
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
            fills: [],
            counts: {
              buy: 1,
              sell: 0,
              hold: 0,
              review: 0,
              candidates_reviewed: 0,
              orders: 1,
              fills: 0,
            },
            total_modeled_costs: { commission: 0, slippage_cost: 0, total: 0 },
          },
        ],
        returned_days: 1,
      }),
    );
    render(<DecisionJournalPanel portfolioId={4} />);
    const day = await screen.findByTestId("shadow-journal-day-2026-09-02");
    fireEvent.click(within(day).getByTestId("shadow-journal-day-date"));
    expect(within(day).getByTestId("shadow-journal-legacy-message")).toHaveTextContent(LEGACY_MSG);
  });

  it("clears stale journal on portfolio switch", async () => {
    const { rerender } = render(<DecisionJournalPanel key="3" portfolioId={3} />);
    expect(await screen.findByTestId("shadow-journal-portfolio-id")).toHaveTextContent("3");
    expect(screen.getByTestId("shadow-journal-day-2026-09-02")).toBeInTheDocument();

    vi.mocked(shadowApi.getShadowJournal).mockResolvedValue(
      journalPayload({
        portfolio_id: 4,
        days: [
          {
            date: "2026-09-10",
            signal_as_of_date: "2026-09-10",
            decision: null,
            decision_ids: [],
            detail_available: false,
            message_ru: LEGACY_MSG,
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
          },
        ],
        returned_days: 1,
      }),
    );

    rerender(<DecisionJournalPanel key="4" portfolioId={4} />);
    await waitFor(() => {
      expect(screen.getByTestId("shadow-journal-portfolio-id")).toHaveTextContent("4");
    });
    expect(await screen.findByTestId("shadow-journal-day-2026-09-10")).toBeInTheDocument();
    expect(screen.queryByTestId("shadow-journal-day-2026-09-02")).not.toBeInTheDocument();
    expect(shadowApi.getShadowJournal).toHaveBeenCalledWith(
      4,
      expect.any(Object),
      expect.any(AbortSignal),
    );
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

  it("smoke-renders under dark and light theme tokens", async () => {
    const root = document.documentElement;
    root.dataset.theme = "dark";
    const { unmount } = render(<DecisionJournalPanel portfolioId={3} />);
    expect(await screen.findByTestId("shadow-decision-journal")).toBeInTheDocument();
    unmount();
    root.dataset.theme = "light";
    render(<DecisionJournalPanel portfolioId={3} />);
    expect(await screen.findByTestId("shadow-decision-journal")).toBeInTheDocument();
    root.removeAttribute("data-theme");
  });

  it("smoke-renders in a narrow viewport layout class", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 480 });
    render(<DecisionJournalPanel portfolioId={3} />);
    const panel = await screen.findByTestId("shadow-decision-journal");
    expect(panel.querySelector(".shadow-journal-filters")).toBeTruthy();
    expect(panel).toBeInTheDocument();
  });
});
