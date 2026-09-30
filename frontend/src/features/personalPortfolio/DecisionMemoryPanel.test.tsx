import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import type { DecisionMemoryRecord } from "../../api/decisionMemory";
import * as api from "../../api/decisionMemory";
import { DecisionMemoryPanel } from "./DecisionMemoryPanel";

vi.mock("../../api/decisionMemory", async () => {
  const actual = await vi.importActual<typeof api>("../../api/decisionMemory");
  return {
    ...actual,
    captureDecisionMemory: vi.fn(),
    listDecisionMemory: vi.fn(),
    getDecisionMemory: vi.fn(),
    getPossibleMatches: vi.fn(),
    linkOperation: vi.fn(),
    unlinkOperation: vi.fn(),
    refreshDecisionOutcomes: vi.fn(),
  };
});

const record: DecisionMemoryRecord = {
  id: 7,
  portfolio_id: 1,
  portfolio_name_snapshot: "Мой портфель",
  captured_at: "2026-09-28T09:00:00+00:00",
  decision_as_of: "2026-09-27",
  engine_version: "PERSONAL_DAILY_DECISION_V2",
  new_cash_rub: null,
  status: "READY",
  headline: "Рассмотрите увеличение SBER",
  canonical_hash: "abc",
  hash_verified: true,
  idempotency_key: "key-1",
  candidate_provenance: {},
  broker_fee_provenance: {},
  created_at: "2026-09-28T09:00:00+00:00",
  disclaimer: "Память решений фиксирует рекомендацию.",
  actions_count: 1,
  idempotent_replay: false,
  actions: [
    {
      id: 11,
      decision_record_id: 7,
      original_action_id: "CONSIDER_INCREASE:SBER",
      action: "CONSIDER_INCREASE",
      priority: "HIGH",
      symbol: "SBER",
      instrument_id: 5,
      reason_codes: ["UNDERWEIGHT"],
      target_weight: "0.2",
      current_weight: "0.1",
      lots_delta: "1",
      units_delta: null,
      estimated_notional: "30000",
      limitations: [],
      action_payload: { title: "Рассмотреть покупку SBER", rationale: "Позиция ниже целевого веса." },
      baseline: {
        status: "AVAILABLE",
        price: "300",
        market_date: "2026-09-26",
        price_source: "EOD_CLOSE",
        observed_at: "2026-09-28T09:00:00+00:00",
      },
      links: [],
      outcomes: [
        {
          id: 1,
          decision_action_id: 11,
          horizon_sessions: 5,
          status: "READY",
          target_session_date: "2026-10-03",
          observed_session_date: "2026-10-03",
          baseline_price: "300",
          observed_price: "315",
          return_type: "PRICE_RETURN",
          forward_return: "0.05",
          directional_alignment: "ALIGNED",
          provenance: {},
          refreshed_at: null,
        },
        {
          id: 2,
          decision_action_id: 11,
          horizon_sessions: 20,
          status: "PENDING",
          target_session_date: "2026-10-26",
          observed_session_date: null,
          baseline_price: "300",
          observed_price: null,
          return_type: "PRICE_RETURN",
          forward_return: null,
          directional_alignment: null,
          provenance: {},
          refreshed_at: null,
        },
        {
          id: 3,
          decision_action_id: 11,
          horizon_sessions: 60,
          status: "PENDING",
          target_session_date: "2026-12-20",
          observed_session_date: null,
          baseline_price: "300",
          observed_price: null,
          return_type: "PRICE_RETURN",
          forward_return: null,
          directional_alignment: null,
          provenance: {},
          refreshed_at: null,
        },
      ],
    },
  ],
};

describe("DecisionMemoryPanel", () => {
  beforeEach(() => {
    vi.mocked(api.captureDecisionMemory).mockReset();
    vi.mocked(api.listDecisionMemory).mockReset();
    vi.mocked(api.getDecisionMemory).mockReset();
    vi.mocked(api.getPossibleMatches).mockReset();
    vi.mocked(api.linkOperation).mockReset();
    vi.mocked(api.unlinkOperation).mockReset();
    vi.mocked(api.refreshDecisionOutcomes).mockReset();
    vi.mocked(api.listDecisionMemory).mockResolvedValue({ portfolio_id: 1, items: [], count: 0 });
    vi.mocked(api.getPossibleMatches).mockResolvedValue({
      decision_action_id: 11,
      action: "CONSIDER_INCREASE",
      window: { from: null, to: null, upper_bound: "NOW" },
      matches: [],
      reason: null,
      disclaimer: "",
    });
  });

  it("renders capture button and does not capture on mount", async () => {
    render(<DecisionMemoryPanel portfolioId={1} />);
    expect(screen.getByRole("button", { name: "Зафиксировать решение" })).toBeInTheDocument();
    await screen.findByTestId("memory-empty");
    expect(api.captureDecisionMemory).not.toHaveBeenCalled();
  });

  it("shows empty history message", async () => {
    render(<DecisionMemoryPanel portfolioId={1} />);
    expect(await screen.findByText("История решений раньше не сохранялась.")).toBeInTheDocument();
  });

  it("calls capture API with current new cash", async () => {
    vi.mocked(api.captureDecisionMemory).mockResolvedValue(record);
    render(<DecisionMemoryPanel portfolioId={1} newCashRub="30000" />);
    await screen.findByTestId("memory-empty");
    fireEvent.click(screen.getByTestId("memory-capture"));
    await waitFor(() => expect(api.captureDecisionMemory).toHaveBeenCalledTimes(1));
    expect(api.captureDecisionMemory).toHaveBeenCalledWith(1, { test: false, newCashRub: "30000" });
  });

  it("shows captured decision in history list", async () => {
    vi.mocked(api.captureDecisionMemory).mockResolvedValue(record);
    render(<DecisionMemoryPanel portfolioId={1} />);
    await screen.findByTestId("memory-empty");
    fireEvent.click(screen.getByTestId("memory-capture"));
    expect(await screen.findByTestId("memory-item-7")).toHaveTextContent("Рассмотрите увеличение SBER");
    expect(screen.queryByTestId("memory-empty")).not.toBeInTheDocument();
  });

  it("opens detail with recommendation / what happened / outcomes blocks", async () => {
    vi.mocked(api.listDecisionMemory).mockResolvedValue({ portfolio_id: 1, items: [record], count: 1 });
    vi.mocked(api.getDecisionMemory).mockResolvedValue(record);
    vi.mocked(api.getPossibleMatches).mockResolvedValue({
      decision_action_id: 11,
      action: "CONSIDER_INCREASE",
      window: { from: null, to: null, upper_bound: "NOW" },
      matches: [
        {
          label: "POSSIBLE_MATCH",
          personal_operation_id: 99,
          operation_type: "BUY",
          occurred_at: "2026-09-29T10:00:00+00:00",
          instrument_id: 5,
          lots: "1",
          units: "10",
          price: "301",
          amount: "3010",
          commission: "1",
          already_linked: false,
        },
      ],
      reason: null,
      disclaimer: "",
    });

    render(<DecisionMemoryPanel portfolioId={1} />);
    fireEvent.click(await screen.findByTestId("memory-open-7"));

    expect(await screen.findByText("Что Kraken рекомендовала")).toBeInTheDocument();
    expect(screen.getByText("Позиция ниже целевого веса.")).toBeInTheDocument();
    expect(screen.getByText("Что произошло")).toBeInTheDocument();
    expect(screen.getByText("Действие пользователя не подтверждено")).toBeInTheDocument();
    expect(await screen.findByText("POSSIBLE_MATCH")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Связать с операцией" })).toBeInTheDocument();
    expect(screen.getByText("Результат после решения")).toBeInTheDocument();
    expect(screen.getByText("Изменение цены; дивиденды не включены")).toBeInTheDocument();
    expect(screen.getByTestId("memory-outcome-5")).toHaveTextContent("PRICE_RETURN +5.00%");
    expect(screen.getByTestId("memory-outcome-20")).toHaveTextContent("Ожидает");
    expect(screen.getByTestId("memory-outcome-60")).toBeInTheDocument();
    expect(api.captureDecisionMemory).not.toHaveBeenCalled();
  });

  it("does not render [object Object]", async () => {
    vi.mocked(api.listDecisionMemory).mockResolvedValue({ portfolio_id: 1, items: [record], count: 1 });
    vi.mocked(api.getDecisionMemory).mockResolvedValue({
      ...record,
      actions: [
        {
          ...record.actions![0],
          action_payload: { title: { nested: true }, rationale: { nested: true } },
          reason_codes: [{ bad: 1 } as unknown as string],
        },
      ],
    });
    const { container } = render(<DecisionMemoryPanel portfolioId={1} />);
    fireEvent.click(await screen.findByTestId("memory-open-7"));
    await screen.findByTestId("memory-block-outcomes");
    expect(container.textContent).not.toContain("[object Object]");
  });

  it("shows a readable error when capture fails", async () => {
    vi.mocked(api.captureDecisionMemory).mockRejectedValue(new ApiError("Портфель не найден.", 404));
    render(<DecisionMemoryPanel portfolioId={1} />);
    await screen.findByTestId("memory-empty");
    fireEvent.click(screen.getByTestId("memory-capture"));
    expect(await screen.findByTestId("memory-error")).toHaveTextContent("Портфель не найден.");
  });

  it("unlinks a confirmed link", async () => {
    const linked: DecisionMemoryRecord = {
      ...record,
      actions: [
        {
          ...record.actions![0],
          links: [
            {
              id: 50,
              decision_action_id: 11,
              portfolio_id: 1,
              personal_operation_id: 99,
              link_source: "USER_CONFIRMED",
              linked_at: "2026-09-29T10:00:00+00:00",
              unlinked_at: null,
              active: true,
            },
          ],
        },
      ],
    };
    vi.mocked(api.listDecisionMemory).mockResolvedValue({ portfolio_id: 1, items: [record], count: 1 });
    vi.mocked(api.getDecisionMemory).mockResolvedValueOnce(linked).mockResolvedValue(record);
    vi.mocked(api.unlinkOperation).mockResolvedValue({ ...linked.actions![0].links[0], active: false });

    render(<DecisionMemoryPanel portfolioId={1} />);
    fireEvent.click(await screen.findByTestId("memory-open-7"));
    fireEvent.click(await screen.findByTestId("memory-unlink-50"));
    await waitFor(() => expect(api.unlinkOperation).toHaveBeenCalledWith(1, 50, { test: false }));
    expect(await screen.findByText("Действие пользователя не подтверждено")).toBeInTheDocument();
  });
});
