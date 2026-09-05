import { describe, expect, it } from "vitest";
import {
  cashHurdleReturn,
  excessVsCashHurdle,
  parseHurdleParam,
} from "./cashHurdle";
import { sampleMaturityLabel } from "./sampleMaturity";

describe("cashHurdle", () => {
  it("compounds (1+r)^(days/365.25)-1", () => {
    const r = cashHurdleReturn("2020-01-01", "2021-01-01", 0.1);
    expect(r).not.toBeNull();
    expect(r!).toBeGreaterThan(0.09);
    expect(r!).toBeLessThan(0.11);
  });

  it("computes excess vs total return", () => {
    const { excess } = excessVsCashHurdle(0.05, "2020-01-01", "2021-01-01", 0.1);
    expect(excess).not.toBeNull();
    expect(excess!).toBeLessThan(0);
  });

  it("parses hurdle URL param", () => {
    expect(parseHurdleParam("0.10")).toBeCloseTo(0.1);
    expect(parseHurdleParam("0.5")).toBe(0.3);
    expect(parseHurdleParam(null)).toBe(0.1);
  });
});

describe("sampleMaturity", () => {
  it("maps codes and counts to Russian labels", () => {
    expect(sampleMaturityLabel(0)).toMatch(/Слишком рано/);
    expect(sampleMaturityLabel("TOO_EARLY")).toMatch(/Слишком рано/);
    expect(sampleMaturityLabel(3)).toMatch(/Очень мало/);
    expect(sampleMaturityLabel(10)).toMatch(/Предварительные/);
    expect(sampleMaturityLabel(30)).toMatch(/накапливаться/);
    expect(sampleMaturityLabel(60)).toMatch(/содержательная/);
  });
});
