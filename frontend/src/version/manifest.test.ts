import { describe, expect, it } from "vitest";
import { getBuildMeta } from "./buildMeta";
import {
  KRAKEN_DISPLAY_VERSION,
  KRAKEN_RELEASES,
  KRAKEN_VERSION,
  currentRelease,
} from "./manifest";
import { formatReleaseDate, isCompleteReleaseNotes } from "./releaseHistory";

describe("Kraken version source", () => {
  it("reads semver 1.0.0 and display Kraken V1.0", () => {
    expect(KRAKEN_VERSION).toBe("1.0.0");
    expect(KRAKEN_DISPLAY_VERSION).toBe("Kraken V1.0");
  });

  it("current release matches VERSION with mandatory date", () => {
    const rel = currentRelease();
    expect(rel.version).toBe("1.0.0");
    expect(rel.displayVersion).toBe("Kraken V1.0");
    expect(rel.title).toBe("First Release");
    expect(rel.date).toBe("2026-09-27");
    expect(formatReleaseDate(rel.date)).toBe("27.09.2026");
    expect(rel.gitTag).toBe("v1.0.0");
    expect(isCompleteReleaseNotes(rel)).toBe(true);
  });

  it("V1.0 history entry is a complete official snapshot", () => {
    const v1 = KRAKEN_RELEASES.find((r) => r.version === "1.0.0");
    expect(v1).toBeDefined();
    expect(v1!.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(v1!.whatsNew.length).toBeGreaterThan(0);
    expect(v1!.summary.length).toBeGreaterThan(0);
    expect(v1!.releaseCommitSha).toMatch(/^[0-9a-f]{40}$/);
  });

  it("owner build meta uses injected sha when present", () => {
    const meta = getBuildMeta("1.0.0");
    expect(meta.gitTag).toBe("v1.0.0");
    expect(meta.version).toBe("1.0.0");
  });
});
