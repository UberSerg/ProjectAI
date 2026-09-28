import { describe, expect, it } from "vitest";
import {
  findReleaseByVersion,
  formatReleaseDate,
  isCompleteReleaseNotes,
  makeTestRelease,
} from "./releaseHistory";

describe("releaseHistory helpers", () => {
  it("formats canonical date for UI", () => {
    expect(formatReleaseDate("2026-09-27")).toBe("27.09.2026");
  });

  it("requires date and human notes for completeness", () => {
    const ok = makeTestRelease({
      version: "9.9.9",
      displayVersion: "Kraken V9.9",
      date: "2026-01-02",
      summary: "Test summary",
      whatsNew: ["A — why it matters"],
    });
    expect(isCompleteReleaseNotes(ok)).toBe(true);

    const noDate = makeTestRelease({
      version: "9.9.8",
      displayVersion: "Kraken V9.9",
      date: "",
      summary: "x",
      whatsNew: ["y"],
    });
    expect(isCompleteReleaseNotes(noDate)).toBe(false);
  });

  it("keeps independent notes per version (no silent inheritance)", () => {
    const older = makeTestRelease({
      version: "1.0.0",
      displayVersion: "Kraken V1.0",
      date: "2026-09-27",
      summary: "V1.0 summary only",
      whatsNew: ["V1.0 change — for V1.0 users"],
    });
    const newer = makeTestRelease({
      version: "9.1.0",
      displayVersion: "Kraken V9.1",
      date: "2026-12-01",
      summary: "V9.1 summary only",
      whatsNew: ["V9.1 change — for V9.1 users"],
      technicalNotes: ["internal owner note"],
    });
    const catalog = [newer, older];
    const lookedUp = findReleaseByVersion(catalog, "1.0.0");
    expect(lookedUp?.summary).toBe("V1.0 summary only");
    expect(lookedUp?.whatsNew).toEqual(["V1.0 change — for V1.0 users"]);
    expect(lookedUp?.whatsNew).not.toEqual(newer.whatsNew);
    expect(lookedUp?.technicalNotes).toBeUndefined();
    expect(newer.technicalNotes?.[0]).toContain("owner");
  });
});
