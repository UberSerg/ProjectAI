import type { ShadowDailyOperations } from "../../api/shadow";
import {
  automationWarningText,
  isMidSessionActivation,
  latestActivationIso,
  mapNextSessionStage,
  mskTradingDateFromClock,
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
        { activated_at: "2026-09-04T14:15:29.275066+00:00" },
        { activated_at: "2026-09-07T13:38:24.403001+00:00" },
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
