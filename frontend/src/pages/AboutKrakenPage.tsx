import { Link } from "react-router-dom";
import { useKrakenRole } from "../role/KrakenRoleContext";
import { getBuildMeta } from "../version/buildMeta";
import {
  KRAKEN_DISPLAY_VERSION,
  KRAKEN_RELEASES,
  KRAKEN_VERSION,
  currentRelease,
} from "../version/manifest";
import { formatReleaseDate } from "../version/releaseHistory";
import { ReleaseHistoryPanel } from "../version/ReleaseHistoryPanel";

export function AboutKrakenPage() {
  const { isUser } = useKrakenRole();
  const release = currentRelease();
  const meta = getBuildMeta(KRAKEN_VERSION);

  return (
    <div className="page about-kraken" data-testid="about-kraken-page">
      <header className="page-header">
        <p className="muted">О продукте</p>
        <h1 data-testid="about-display-version">{release.displayVersion}</h1>
        <p className="lead" data-testid="about-release-title">
          {release.title}
        </p>
        <p className="muted" data-testid="about-release-date">
          Дата релиза: {formatReleaseDate(release.date)}
        </p>
      </header>

      <section className="panel" data-testid="about-summary">
        <p>{release.summary}</p>
        <ul className="about-highlights">
          {release.highlights.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section className="panel" data-testid="about-whats-new">
        <h2>Что нового в {release.displayVersion}</h2>
        <ul>
          {release.whatsNew.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p className="muted about-iam-note">
          USER / OWNER — режим интерфейса (presentation). Не production IAM.
        </p>
      </section>

      {!isUser ? (
        <section className="panel" data-testid="about-owner-meta">
          <h2>Сборка (OWNER)</h2>
          <dl className="about-meta-grid">
            <div>
              <dt>Version</dt>
              <dd data-testid="about-semver">{meta.version}</dd>
            </div>
            <div>
              <dt>Git tag</dt>
              <dd data-testid="about-git-tag">{meta.gitTag}</dd>
            </div>
            <div>
              <dt>Commit</dt>
              <dd data-testid="about-git-sha">{meta.gitSha ?? "не задан в сборке"}</dd>
            </div>
            <div>
              <dt>Build time</dt>
              <dd data-testid="about-build-time">{meta.buildTime ?? "не задан в сборке"}</dd>
            </div>
          </dl>
          {release.technicalNotes && release.technicalNotes.length > 0 ? (
            <div data-testid="about-current-technical">
              <h3>Technical Notes текущей версии</h3>
              <ul>
                {release.technicalNotes.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}

      <ReleaseHistoryPanel
        releases={KRAKEN_RELEASES}
        currentVersion={KRAKEN_VERSION}
        showTechnicalNotes={!isUser}
      />

      <p className="muted">
        <Link to="/">← На обзор</Link>
        {" · "}
        <span data-testid="about-product-line">{KRAKEN_DISPLAY_VERSION}</span>
      </p>
    </div>
  );
}
