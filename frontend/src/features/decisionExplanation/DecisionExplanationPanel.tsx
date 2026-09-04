import { useId, useState } from "react";

import { MetricHelp } from "../../help/MetricHelp";
import { buildDecisionExplanation } from "./buildExplanation";
import type { DecisionExplanationContext } from "./types";

interface Props {
  context: DecisionExplanationContext;
  title?: string;
  onClose?: () => void;
}

export function DecisionExplanationPanel({
  context,
  title = "Почему была сделка?",
  onClose,
}: Props) {
  const baseId = useId();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [techOpen, setTechOpen] = useState(false);
  const explanation = buildDecisionExplanation(context);

  return (
    <div className="sim-fill-reason panel decision-explanation">
      <div className="sim-fill-reason-head">
        <h3>
          {title} <MetricHelp metricId="decision_why" />
        </h3>
        {onClose ? (
          <button type="button" className="secondary" onClick={onClose}>
            Закрыть
          </button>
        ) : null}
      </div>

      <p className="decision-explanation-summary">{explanation.summary}</p>
      {explanation.usedFallback ? (
        <p className="muted decision-explanation-fallback">
          Нет специализированного текста для кода «{explanation.reasonCode}» — показан общий
          фактический шаблон.
        </p>
      ) : null}

      <div className="decision-explanation-section">
        <button
          type="button"
          className="decision-explanation-toggle"
          aria-expanded={detailsOpen}
          aria-controls={`${baseId}-details`}
          id={`${baseId}-details-btn`}
          onClick={() => setDetailsOpen((v) => !v)}
        >
          Подробнее {detailsOpen ? "▴" : "▾"}
        </button>
        {detailsOpen ? (
          <div
            id={`${baseId}-details`}
            role="region"
            aria-labelledby={`${baseId}-details-btn`}
            className="decision-explanation-body"
          >
            <p>{explanation.detailed}</p>
            {explanation.timeline.length ? (
              <ol className="decision-explanation-timeline">
                {explanation.timeline.map((item) => (
                  <li key={`${item.dateLabel}-${item.label}`}>
                    <span className="decision-explanation-timeline-date">{item.dateLabel}</span>
                    <span>{item.label}</span>
                  </li>
                ))}
              </ol>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="decision-explanation-section">
        <button
          type="button"
          className="decision-explanation-toggle"
          aria-expanded={techOpen}
          aria-controls={`${baseId}-tech`}
          id={`${baseId}-tech-btn`}
          onClick={() => setTechOpen((v) => !v)}
        >
          Технические детали {techOpen ? "▴" : "▾"}
        </button>
        {techOpen ? (
          <div
            id={`${baseId}-tech`}
            role="region"
            aria-labelledby={`${baseId}-tech-btn`}
            className="decision-explanation-body"
          >
            <p className="muted">
              Сырая provenance без LLM. Объяснение выше — детерминированный рендер этих фактов.
            </p>
            <dl className="sim-dl">
              {explanation.technical.map((field) => (
                <div key={field.label}>
                  <dt>{field.label}</dt>
                  <dd>{field.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ) : null}
      </div>
    </div>
  );
}
