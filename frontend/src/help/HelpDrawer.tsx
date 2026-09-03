import { useEffect } from "react";
import { getMetricHelp } from "./registry";
import { HelpSection } from "./HelpSection";
import type { HelpEntry, PageHelpContent } from "./types";

type DrawerMode =
  | { kind: "metric"; entry: HelpEntry }
  | { kind: "page"; page: PageHelpContent }
  | null;

export function HelpDrawer({
  mode,
  onClose,
  onOpenMetric,
}: {
  mode: DrawerMode;
  onClose: () => void;
  onOpenMetric: (id: string) => void;
}) {
  useEffect(() => {
    if (!mode) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mode, onClose]);

  if (!mode) return null;

  return (
    <div className="help-drawer-root" role="presentation">
      <button type="button" className="help-drawer-backdrop" aria-label="Закрыть справку" onClick={onClose} />
      <aside className="help-drawer" role="dialog" aria-modal="true" aria-labelledby="help-drawer-title">
        <header className="help-drawer-header">
          <h2 id="help-drawer-title">{mode.kind === "metric" ? mode.entry.title : mode.page.title}</h2>
          <button type="button" className="secondary" onClick={onClose}>
            Закрыть
          </button>
        </header>
        <div className="help-drawer-body">
          {mode.kind === "metric" ? (
            <MetricBody entry={mode.entry} onOpenMetric={onOpenMetric} />
          ) : (
            <PageBody page={mode.page} onOpenMetric={onOpenMetric} />
          )}
        </div>
      </aside>
    </div>
  );
}

function MetricBody({
  entry,
  onOpenMetric,
}: {
  entry: HelpEntry;
  onOpenMetric: (id: string) => void;
}) {
  return (
    <>
      <HelpSection title="Кратко">
        <p>{entry.summary}</p>
      </HelpSection>
      <HelpSection title="Подробнее">
        <p>{entry.details}</p>
      </HelpSection>
      {entry.interpretation ? (
        <HelpSection title="Как интерпретировать">
          <p>{entry.interpretation}</p>
        </HelpSection>
      ) : null}
      {entry.limitations?.length ? (
        <HelpSection title="Ограничения">
          <ul>
            {entry.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </HelpSection>
      ) : null}
      {entry.relatedIds?.length ? (
        <HelpSection title="Связанные понятия">
          <div className="help-related">
            {entry.relatedIds.map((id) => {
              const related = getMetricHelp(id);
              if (!related) return null;
              return (
                <button key={id} type="button" className="secondary" onClick={() => onOpenMetric(id)}>
                  {related.title}
                </button>
              );
            })}
          </div>
        </HelpSection>
      ) : null}
    </>
  );
}

function PageBody({
  page,
  onOpenMetric,
}: {
  page: PageHelpContent;
  onOpenMetric: (id: string) => void;
}) {
  return (
    <>
      <HelpSection title="О странице">
        <p>{page.about}</p>
      </HelpSection>
      <HelpSection title="Что здесь можно понять">
        <ul>
          {page.understand.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </HelpSection>
      {page.metrics.length ? (
        <HelpSection title="Показатели">
          <div className="help-related">
            {page.metrics.map((id) => {
              const related = getMetricHelp(id);
              if (!related) return null;
              return (
                <button key={id} type="button" className="secondary" onClick={() => onOpenMetric(id)}>
                  {related.title}
                </button>
              );
            })}
          </div>
        </HelpSection>
      ) : null}
      <HelpSection title="Как интерпретировать">
        <ul>
          {page.interpret.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </HelpSection>
      <HelpSection title="Ограничения">
        <ul>
          {page.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </HelpSection>
    </>
  );
}
