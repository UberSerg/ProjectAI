import { describe, expect, it } from "vitest";
import { formatRub } from "./format";

/** Intl may emit NBSP (\u00a0) or narrow NBSP (\u202f) as group separators. */
function normalizeSpaces(s: string): string {
  return s.replace(/[\u00a0\u202f]/g, " ");
}

describe("formatRub", () => {
  it("formats whole rubles without fraction padding", () => {
    expect(normalizeSpaces(formatRub(500000))).toBe("500 000 ₽");
    expect(normalizeSpaces(formatRub(3340))).toBe("3 340 ₽");
  });

  it("keeps significant kopecks", () => {
    expect(normalizeSpaces(formatRub(3340.5))).toBe("3 340,50 ₽");
    expect(normalizeSpaces(formatRub(3.34))).toBe("3,34 ₽");
  });

  it("does not invent thousands from 3.34", () => {
    expect(normalizeSpaces(formatRub(3.34))).not.toMatch(/3\s*340/);
    expect(normalizeSpaces(formatRub(3.34))).toBe("3,34 ₽");
  });

  it("renders null as dash", () => {
    expect(formatRub(null)).toBe("—");
    expect(formatRub(undefined)).toBe("—");
    expect(formatRub(Number.NaN)).toBe("—");
  });
});
