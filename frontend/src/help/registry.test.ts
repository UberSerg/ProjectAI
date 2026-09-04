import { describe, expect, it } from "vitest";
import { getMetricHelp, getPageHelp } from "./registry";
import { clampRange, presetRange } from "../features/quotes/range";

describe("help registry", () => {
  it("defines confidence as coverage×agreement×quality, not probability", () => {
    const entry = getMetricHelp("confidence");
    expect(entry).toBeTruthy();
    expect(entry?.summary.toLowerCase()).toContain("coverage");
    expect(entry?.summary.toLowerCase()).toContain("не вероятность");
    expect(entry?.details).toMatch(/coverage/i);
  });

  it("defines RSI14 and return_20d", () => {
    expect(getMetricHelp("rsi14")?.title).toBe("RSI14");
    expect(getMetricHelp("return_20d")?.title).toContain("20");
  });

  it("defines relations term and page help for existing pages", () => {
    expect(getMetricHelp("relations_term")?.title).toMatch(/Связи/);
    for (const id of [
      "overview",
      "market",
      "instrument",
      "analytics",
      "relations",
      "technical",
      "workflows",
      "system",
      "simulator",
      "simulator_run",
      "shadow",
    ]) {
      expect(getPageHelp(id)?.title).toBeTruthy();
    }
  });

  it("defines simulator help metrics", () => {
    expect(getMetricHelp("sim_excess")?.summary.toLowerCase()).toContain("процентн");
    expect(getMetricHelp("sim_oos")?.summary.toLowerCase()).toMatch(/mixed|oos|research/);
    expect(getMetricHelp("sim_survivorship")?.title).toMatch(/Survivorship/);
    expect(getMetricHelp("decision_why")?.summary.toLowerCase()).toMatch(/llm|фактов/);
    expect(getMetricHelp("decision_pred_20d")?.title).toMatch(/20d|Predicted/i);
    expect(getMetricHelp("decision_rank")?.details.toLowerCase()).toMatch(/лучшая компания/);
    expect(getMetricHelp("shadow_portfolio")?.summary.toLowerCase()).toMatch(/проспектив/);
    expect(getMetricHelp("prospective_experiment")?.details.toLowerCase()).toMatch(/симулятор|open/);
  });
});

describe("quote range helpers", () => {
  const available = { from: "2015-01-15", to: "2026-08-20" };

  it("clamps manual range to instrument availability", () => {
    expect(clampRange({ from: "2010-01-01", to: "2030-01-01" }, available)).toEqual(available);
  });

  it("builds presets relative to last available date", () => {
    expect(presetRange("MAX", available)).toEqual(available);
    expect(presetRange("1Y", available).to).toBe("2026-08-20");
    expect(presetRange("1Y", available).from).toBe("2025-08-20");
    expect(presetRange("YTD", available).from).toBe("2026-01-01");
  });

  it("short history later-listed instruments collapse long presets to available window", () => {
    const short = { from: "2024-06-01", to: "2024-09-01" };
    expect(presetRange("5Y", short)).toEqual(short);
    expect(presetRange("MAX", short)).toEqual(short);
  });
});
