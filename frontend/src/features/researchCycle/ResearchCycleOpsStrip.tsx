import { Link } from "react-router-dom";
import type { ResearchCycleOperationalStatus } from "../../api/researchCycle";
import { MetricHelp } from "../../help";
import { formatDate, formatDateTime } from "../../utils/format";
import {
  formatAutomaticSchedule,
  formatOutcomeMaturity,
  researchCycleHealthLabel,
  researchCycleStatusDisplay,
} from "./helpers";

/** Compact operational strip for Shadow Live page — no redesign of the page. */
export function ResearchCycleOpsStrip({
  status,
  error,
}: {
  status: ResearchCycleOperationalStatus | null;
  error?: string | null;
}) {
  if (error) {
    return (
      <div className="shadow-ops-strip panel">
        <p className="muted">Операционный контур недоступен: {error}</p>
      </div>
    );
  }
  if (!status) {
    return (
      <div className="shadow-ops-strip panel">
        <p className="muted">Загрузка операционного контура…</p>
      </div>
    );
  }

  const cycle = status.latest_cycle;
  const wm = status.watermarks;
  const shadowDates = (wm.shadow_portfolios ?? [])
    .map((p) => p.last_processed_market_date)
    .filter(Boolean) as string[];
  const shadowProcessed = shadowDates.sort().at(-1) ?? null;

  return (
    <div className="shadow-ops-strip panel">
      <div className="shadow-ops-strip-grid">
        <div>
          <span className="muted">Последний цикл</span>
          <strong>
            {cycle
              ? `${researchCycleStatusDisplay(cycle.status)} · ${formatDateTime(cycle.finished_at ?? cycle.started_at)}`
              : "ещё не запускался"}
          </strong>
        </div>
        <div>
          <span className="muted">
            Состояние контура <MetricHelp metricId="daily_cycle_health" />
          </span>
          <strong>{researchCycleHealthLabel(status.health, status.health_human)}</strong>
        </div>
        <div>
          <span className="muted">Последние рыночные данные</span>
          <strong>{formatDate(wm.raw_market_latest_date)}</strong>
        </div>
        <div>
          <span className="muted">Последний Forward</span>
          <strong>
            {wm.forward_latest_batch_id != null ? `#${wm.forward_latest_batch_id}` : "—"}
            {wm.forward_latest_as_of ? ` · ${formatDate(wm.forward_latest_as_of)}` : ""}
          </strong>
        </div>
        <div>
          <span className="muted">Shadow processed</span>
          <strong>{formatDate(shadowProcessed)}</strong>
        </div>
        <div>
          <span className="muted">
            Automatic schedule <MetricHelp metricId="research_cycle" />
          </span>
          <strong>
            {formatAutomaticSchedule(status.automatic_schedule, status.schedule)}
          </strong>
        </div>
        <div>
          <span className="muted">
            First 20d outcome maturity <MetricHelp metricId="forward_outcome_pending" />
          </span>
          <strong>{formatOutcomeMaturity(status.outcome_maturity)}</strong>
        </div>
      </div>
      <p className="muted shadow-ops-strip-link">
        Подробности цикла — на странице{" "}
        <Link to="/workflows">Процессы</Link>.
      </p>
    </div>
  );
}
