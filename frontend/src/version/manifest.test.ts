import { describe, expect, it } from "vitest";
import { getBuildMeta } from "./buildMeta";
import {
  KRAKEN_DISPLAY_VERSION,
  KRAKEN_RELEASES,
  KRAKEN_VERSION,
  currentRelease,
} from "./manifest";

describe("Kraken version source", () => {
  it("reads semver 1.0.0 and display Kraken V1.0", () => {
    expect(KRAKEN_VERSION).toBe("1.0.0");
    expect(KRAKEN_DISPLAY_VERSION).toBe("Kraken V1.0");
  });

  it("current release matches VERSION", () => {
    const rel = currentRelease();
    expect(rel.version).toBe("1.0.0");
    expect(rel.displayVersion).toBe("Kraken V1.0");
    expect(rel.title).toBe("First Release");
  });

  it("history is ready for future versions without inventing them", () => {
    expect(KRAKEN_RELEASES.length).toBeGreaterThanOrEqual(1);
    expect(KRAKEN_RELEASES.every((r) => /^\d+\.\d+\.\d+$/.test(r.version))).toBe(true);
  });

  it("owner build meta uses injected sha when present", () => {
    const meta = getBuildMeta("1.0.0");
    expect(meta.gitTag).toBe("v1.0.0");
    expect(meta.version).toBe("1.0.0");
  });
});
