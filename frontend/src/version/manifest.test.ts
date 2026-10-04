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
  it("keeps technical VERSION 1.0.0 and shows product Kraken 1.04", () => {
    expect(KRAKEN_VERSION).toBe("1.0.0");
    expect(KRAKEN_PRODUCT_VERSION).toBe("1.04");
    expect(KRAKEN_DISPLAY_VERSION).toBe("Kraken 1.04");
  });

  it("current release is product 1.04 with mandatory date", () => {
    const rel = currentRelease();
    expect(rel.version).toBe("1.04");
    expect(rel.displayVersion).toBe("Kraken 1.04");
    expect(rel.date).toBe("2026-10-04");
    expect(formatReleaseDate(rel.date)).toBe("04.10.2026");
    expect(isCompleteReleaseNotes(rel)).toBe(true);
    expect(rel.title).toContain("каноническая кампания");
    expect(rel.whatsNew.some((line) => line.includes("не улучшил OOS-сигнал относительно BASE"))).toBe(
      true,
    );
    expect(rel.whatsNew.some((line) => /42.?988/.test(line))).toBe(true);
    expect(rel.gitTag).toBeFalsy();
  });

  it("keeps cumulative history 1.04 → 1.03 → 1.02 → 1.01 → V1.0 without inventing tags", () => {
    expect(KRAKEN_RELEASES.map((r) => r.version)).toEqual([
      "1.04",
      "1.03",
      "1.02",
      "1.01",
      "1.0.0",
    ]);

    const v103 = KRAKEN_RELEASES.find((r) => r.version === "1.03");
    expect(v103).toBeDefined();
    expect(v103!.displayVersion).toBe("Kraken 1.03");
    expect(v103!.date).toBe("2026-09-30");
    expect(formatReleaseDate(v103!.date)).toBe("30.09.2026");
    expect(v103!.gitTag).toBeFalsy();
    expect(v103!.whatsNew.some((line) => line.includes("Personal Decision Memory"))).toBe(true);
    expect(isCompleteReleaseNotes(v103!)).toBe(true);

    const v102 = KRAKEN_RELEASES.find((r) => r.version === "1.02");
    expect(v102).toBeDefined();
    expect(v102!.displayVersion).toBe("Kraken 1.02");
    expect(v102!.date).toBe("2026-09-29");
    expect(formatReleaseDate(v102!.date)).toBe("29.09.2026");
    expect(v102!.gitTag).toBeFalsy();
    expect(v102!.whatsNew.some((line) => line.includes("Shadow Realism V3"))).toBe(true);
    expect(isCompleteReleaseNotes(v102!)).toBe(true);

    const v101 = KRAKEN_RELEASES.find((r) => r.version === "1.01");
    expect(v101).toBeDefined();
    expect(v101!.displayVersion).toBe("Kraken 1.01");
    expect(v101!.date).toBe("2026-09-28");
    expect(formatReleaseDate(v101!.date)).toBe("28.09.2026");
    expect(v101!.gitTag).toBeFalsy();
    expect(v101!.whatsNew.some((line) => line.includes("Multi-Portfolio V2"))).toBe(true);
    expect(isCompleteReleaseNotes(v101!)).toBe(true);
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
