/** Helpers for official Kraken release history (immutable per-version snapshots). */

import type { KrakenReleaseNotes } from "./manifest";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Format canonical YYYY-MM-DD for UI, e.g. 27.09.2026 */
export function formatReleaseDate(isoDate: string): string {
  if (!DATE_RE.test(isoDate)) {
    return isoDate;
  }
  const [y, m, d] = isoDate.split("-");
  return `${d}.${m}.${y}`;
}

export function isCompleteReleaseNotes(release: KrakenReleaseNotes): boolean {
  return (
    Boolean(release.version?.trim()) &&
    Boolean(release.displayVersion?.trim()) &&
    DATE_RE.test(release.date) &&
    Boolean(release.summary?.trim()) &&
    Array.isArray(release.whatsNew) &&
    release.whatsNew.length > 0
  );
}

/** Pure lookup — never falls back to another release's notes. */
export function findReleaseByVersion(
  releases: readonly KrakenReleaseNotes[],
  version: string,
): KrakenReleaseNotes | undefined {
  return releases.find((r) => r.version === version);
}

/**
 * Fixture factory for tests: two independent releases must keep separate notes.
 * Not an official product release.
 */
export function makeTestRelease(
  partial: Pick<KrakenReleaseNotes, "version" | "displayVersion" | "date" | "summary" | "whatsNew"> &
    Partial<KrakenReleaseNotes>,
): KrakenReleaseNotes {
  return {
    title: partial.title ?? `Test ${partial.version}`,
    gitTag: partial.gitTag ?? `v${partial.version}`,
    highlights: partial.highlights ?? [],
    technicalNotes: partial.technicalNotes,
    releaseCommitSha: partial.releaseCommitSha ?? null,
    ...partial,
  };
}
