import type { ShadowDailyOperations, ShadowPortfolioSummary } from "../../api/shadow";
import {
  automationWarningText,
  isMidSessionActivation,
  isRealismV2Portfolio,
  isRealismV3Portfolio,
  journalCandidateHumanReason,
  journalDecisionActionLabel,
  latestActivationIso,
  mapNextSessionStage,
  mskTradingDateFromClock,
  partitionShadowPortfolios,
  todaySessionHeadline,
} from "./helpers";
import { describe, expect, it } from "vitest";

describe("shadow session helpers", () => {
  it("maps next-session prep codes to product stages", () => {
    expect(mapNextSessionStage("WAITING_FOR_MARKET_COMPLETE")).toBe("WAITING_EOD");
    expect(mapNextSessionStage("WAITING_FOR_ANALYTICS")).toBe("PROCESSING");
    expect(mapNextSessionStage("CYCLE_RUNNING")).toBe("PROCESSING");
    expect(mapNextSessionStage("READY_FOR_NEXT_SESSION")).toBe("READY");
    expect(mapNextSessionStage("READY_NO_REBALANCE")).toBe("READY");
    expect(mapNextSessionStage("BLOCKED_CONSISTENCY")).toBe("BLOCKED");
    expect(mapNextSessionStage("AUTOMATION_DISABLED")).toBe("BLOCKED");
  });

  it("builds mid-session today headline with required copy", () => {
    const ops: ShadowDailyOperations = {
      mid_session_activation: true,
      current_session_status: "MID_SESSION_ACTIVATION_WAIT_NEXT_OPEN",
      today_summary: {
        code: "MID_SESSION_ACTIVATION_WAIT_NEXT_OPEN",
        message_ru: "backend message",
      },
    };
    expect(isMidSessionActivation(ops)).toBe(true);
    const today = todaySessionHeadline(ops);
    expect(today.title).toMatch(/Первая сделка — на следующем открытии/);
    expect(today.midSession).toBe(true);
  });

  it("prefers latest activation for mid-session display", () => {
    const ops: ShadowDailyOperations = {
      portfolios: [
        { id: 1, name: "V1", activated_at: "2026-09-04T14:15:29.275066+00:00" },
        { id: 5, name: "V2", activated_at: "2026-09-07T13:38:24.403001+00:00" },
      ],
    };
    expect(latestActivationIso(ops)).toBe("2026-09-07T13:38:24.403001+00:00");
  });

  it("derives MSK trading date from UTC clock", () => {
    expect(mskTradingDateFromClock("2026-09-07T14:50:00+00:00")).toBe("2026-09-07");
  });

  it("reads automation warning from ops", () => {
    expect(
      automationWarningText({
        automation: {
          warning: "Автоматизация выключена — catch-up не запустится без RESEARCH_LIVE_MODE.",
        },
      }),
    ).toMatch(/RESEARCH_LIVE_MODE/);
  });
});

describe("shadow decision journal labels", () => {
  it("labels REVIEW_HOLD and ROTATE in Russian", () => {
    expect(journalDecisionActionLabel("REVIEW_HOLD")).toBe("Ревизия: удержать");
    expect(journalDecisionActionLabel("ROTATE")).toBe("Ротация");
  });

  it("builds human REVIEW_HOLD / ROTATE reasons from structured facts", () => {
    expect(
      journalCandidateHumanReason({
        action: "REVIEW_HOLD",
        reason_codes: ["EXIT_BAND_INSUFFICIENT_EDGE"],
        replacement_ticker: "SBER",
        net_edge: -0.01,
      }),
    ).toMatch(/Ревизия: позиция удержана/);
    expect(
      journalCandidateHumanReason({
        action: "ROTATE",
        reason_codes: ["NET_EDGE_POSITIVE"],
        replacement_ticker: "ROSN",
      }),
    ).toMatch(/Ротация на ROSN/);
  });
});

describe("shadow experiment partition V3", () => {
  it("prefers V3 primary and treats V2 as legacy", () => {
    const portfolios = [
      { id: "1", name: "SHADOW_HYSTERESIS_V1", experiment_group: "SHADOW_FORWARD_V0", lot_aware: false },
      {
        id: "3",
        name: "SHADOW_HYSTERESIS_V2",
        experiment_group: "SHADOW_PORTFOLIO_REALISM_V2",
        lot_aware: true,
        execution_version: "LOT_AWARE_V2",
      },
      {
        id: "5",
        name: "SHADOW_HYSTERESIS_V3",
        experiment_group: "SHADOW_PORTFOLIO_REALISM_V3",
        lot_aware: true,
        execution_version: "LOT_AWARE_SELL_ECONOMICS_V3",
      },
    ] as ShadowPortfolioSummary[];
    expect(isRealismV3Portfolio(portfolios[2])).toBe(true);
    expect(isRealismV2Portfolio(portfolios[2])).toBe(false);
    expect(isRealismV2Portfolio(portfolios[1])).toBe(true);
    const part = partitionShadowPortfolios(portfolios);
    expect(part.hasV3).toBe(true);
    expect(part.hasV2).toBe(true);
    expect(part.primary.map((p) => p.id)).toEqual(["5"]);
    expect(part.legacy.map((p) => p.id)).toEqual(["3", "1"]);
  });
});
