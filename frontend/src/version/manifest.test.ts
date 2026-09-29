import { describe, expect, it } from "vitest";
import { getBuildMeta } from "./buildMeta";
import {
  KRAKEN_DISPLAY_VERSION,
  KRAKEN_PRODUCT_VERSION,
  KRAKEN_RELEASES,
  KRAKEN_VERSION,
  currentRelease,
} from "./manifest";
import { formatReleaseDate, isCompleteReleaseNotes } from "./releaseHistory";

describe("Kraken version source", () => {
  it("keeps technical VERSION 1.0.0 and shows product Kraken 1.02", () => {
    expect(KRAKEN_VERSION).toBe("1.0.0");
    expect(KRAKEN_PRODUCT_VERSION).toBe("1.02");
    expect(KRAKEN_DISPLAY_VERSION).toBe("Kraken 1.02");
  });

  it("current release is product 1.02 with mandatory date", () => {
    const rel = currentRelease();
    expect(rel.version).toBe("1.02");
    expect(rel.displayVersion).toBe("Kraken 1.02");
    expect(rel.date).toBe("2026-09-29");
    expect(formatReleaseDate(rel.date)).toBe("29.09.2026");
    expect(isCompleteReleaseNotes(rel)).toBe(true);
    expect(rel.whatsNew.some((line) => line.includes("Daily Decision"))).toBe(true);
    expect(rel.whatsNew.some((line) => line.includes("FeeEngine") || line.includes("FeeProfile"))).toBe(
      true,
    );
    expect(rel.whatsNew.some((line) => line.includes("Shadow Realism V3"))).toBe(true);
  });

  it("keeps restored V1.01 history under 1.02", () => {
    const v101 = KRAKEN_RELEASES.find((r) => r.version === "1.0.1");
    expect(v101).toBeDefined();
    expect(v101!.displayVersion).toBe("Kraken V1.01");
    expect(v101!.date).toBe("2026-09-28");
    expect(formatReleaseDate(v101!.date)).toBe("28.09.2026");
    expect(v101!.whatsNew.some((line) => line.includes("Multi-Portfolio V2"))).toBe(true);
    expect(isCompleteReleaseNotes(v101!)).toBe(true);
    expect(KRAKEN_RELEASES.map((r) => r.version)).toEqual(["1.02", "1.0.1", "1.0.0"]);
  });

  it("V1.0 history entry remains a complete official snapshot", () => {
    const v1 = KRAKEN_RELEASES.find((r) => r.version === "1.0.0");
    expect(v1).toBeDefined();
    expect(v1!.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(v1!.whatsNew.length).toBeGreaterThan(0);
    expect(v1!.summary.length).toBeGreaterThan(0);
    expect(v1!.releaseCommitSha).toMatch(/^[0-9a-f]{40}$/);
    expect(isCompleteReleaseNotes(v1!)).toBe(true);
  });

  it("owner build meta still uses technical VERSION", () => {
    const meta = getBuildMeta("1.0.0");
    expect(meta.gitTag).toBe("v1.0.0");
    expect(meta.version).toBe("1.0.0");
  });
});
