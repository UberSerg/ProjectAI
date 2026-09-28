import { useState } from "react";
import type { KrakenReleaseNotes } from "./manifest";
import { formatReleaseDate } from "./releaseHistory";

export interface ReleaseHistoryPanelProps {
  releases: readonly KrakenReleaseNotes[];
  currentVersion: string;
  /** When true, show OWNER technical notes under each expanded entry. */
  showTechnicalNotes?: boolean;
  /** Optional initially expanded version (defaults to current). */
  initiallyExpandedVersion?: string;
}

export function ReleaseHistoryPanel({
  releases,
  currentVersion,
  showTechnicalNotes = false,
  initiallyExpandedVersion,
}: ReleaseHistoryPanelProps) {
  const initial = initiallyExpandedVersion ?? currentVersion;
  const [expanded, setExpanded] = useState<string | null>(
    releases.some((r) => r.version === initial) ? initial : (releases[0]?.version ?? null),
  );

  return (
    <section className="panel" data-testid="about-history">
      <h2>История версий</h2>
      <p className="muted about-history-hint">
        Откройте прошлый релиз, чтобы увидеть, что входило в Kraken на момент его выпуска.
      </p>
      <ol className="about-history-list">
        {releases.map((r) => {
          const isOpen = expanded === r.version;
          const isCurrent = r.version === currentVersion;
          const panelId = `release-history-${r.version.replace(/\./g, "-")}`;
          return (
            <li
              key={r.version}
              data-testid={`history-item-${r.version}`}
              data-current={isCurrent ? "true" : "false"}
              data-expanded={isOpen ? "true" : "false"}
            >
              <button
                type="button"
                className="about-history-toggle"
                data-testid={`history-toggle-${r.version}`}
                aria-expanded={isOpen}
                aria-controls={panelId}
                onClick={() => setExpanded(isOpen ? null : r.version)}
              >
                <span className="about-history-title">
                  <strong>{r.displayVersion}</strong>
                  <span className="muted">
                    {" "}
                    · <span data-testid={`history-date-${r.version}`}>{formatReleaseDate(r.date)}</span>
                    {" · "}
                    {r.title}
                    {isCurrent ? " · текущая" : ""}
                  </span>
                </span>
                <span className="about-history-chevron" aria-hidden>
                  {isOpen ? "▾" : "▸"}
                </span>
              </button>
              {isOpen ? (
                <div
                  id={panelId}
                  className="about-history-details"
                  data-testid={`history-details-${r.version}`}
                >
                  <p data-testid={`history-summary-${r.version}`}>{r.summary}</p>
                  {r.highlights.length > 0 ? (
                    <ul className="about-highlights" data-testid={`history-highlights-${r.version}`}>
                      {r.highlights.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  ) : null}
                  <h3>Что вошло в {r.displayVersion}</h3>
                  <ul data-testid={`history-whats-new-${r.version}`}>
                    {r.whatsNew.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                  {showTechnicalNotes && r.technicalNotes && r.technicalNotes.length > 0 ? (
                    <div data-testid={`history-technical-${r.version}`}>
                      <h3>Technical Notes (OWNER)</h3>
                      <ul>
                        {r.technicalNotes.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <p className="muted about-history-meta">
                    SemVer {r.version}
                    {" · "}
                    tag {r.gitTag}
                    {r.releaseCommitSha ? ` · ${r.releaseCommitSha.slice(0, 12)}` : ""}
                    {" · "}
                    дата {formatReleaseDate(r.date)}
                  </p>
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
