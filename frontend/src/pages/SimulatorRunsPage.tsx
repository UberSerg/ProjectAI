import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import { listSimulatorRuns, type SimulationRunSummary } from "../api/simulator";
import { PageHeader, PageState, StatusBadge } from "../components/Ui";
import { costLabel, policyShort, segmentLabel, segmentTone } from "../features/simulator/helpers";
import { formatDateRange, formatMoney, formatPercent, shortHash } from "../utils/format";
import { labels } from "../utils/labels";

function SegmentBadge({ segment }: { segment?: string | null }) {
  const tone = segmentTone(segment);
  return <span className={`sim-segment-badge sim-segment-${tone}`}>{segmentLabel(segment)}</span>;
}

export function SimulatorRunsPage() {
  const [runs, setRuns] = useState<SimulationRunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listSimulatorRuns(50, controller.signal)
      .then(setRuns)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, []);

  if (error) return <PageState kind="error">{error}</PageState>;
  if (!runs) return <PageState kind="loading" title="Загрузка симуляций…" />;
  if (!runs.length) {
    return (
      <section>
        <PageHeader
          title={labels.nav.simulations}
          description="Исторические прогоны Historical Simulator V0"
          helpPageId="simulator"
        />
        <PageState kind="empty">Пока нет сохранённых прогонов симулятора.</PageState>
      </section>
    );
  }

  return (
    <section>
      <PageHeader
        title={labels.nav.simulations}
        description="Исторические прогоны Historical Simulator V0 (research, не брокерский P&L)"
        helpPageId="simulator"
        actions={
          <Link to="/shadow" className="secondary button-link">
            {labels.nav.liveExperiment}
          </Link>
        }
      />

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Сегмент</th>
              <th>Период</th>
              <th>Политика</th>
              <th>Candidate</th>
              <th>Издержки</th>
              <th className="numeric">Нач. NAV</th>
              <th className="numeric">Кон. NAV</th>
              <th className="numeric">Доходность</th>
              <th className="numeric">Max DD</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const m = run.metrics ?? {};
              return (
                <tr key={run.id} className="clickable">
                  <td>
                    <Link to={`/simulator/${run.id}`} className="sim-run-link">
                      <SegmentBadge segment={run.segment} />
                    </Link>
                  </td>
                  <td>
                    <Link to={`/simulator/${run.id}`}>{formatDateRange(run.date_from, run.date_to)}</Link>
                  </td>
                  <td>{policyShort(run.spec?.policy_name)}</td>
                  <td>
                    <code title={run.candidate_config_hash ?? undefined}>
                      {shortHash(run.candidate_config_hash)}
                    </code>
                  </td>
                  <td>{costLabel(run.spec?.commission_bps)}</td>
                  <td className="numeric">{formatMoney(m.initial_nav ?? run.spec?.initial_capital)}</td>
                  <td className="numeric">{formatMoney(m.final_nav)}</td>
                  <td className="numeric">
                    <span className={signedClass(m.total_price_return)}>
                      {formatPercent(m.total_price_return)}
                    </span>
                  </td>
                  <td className="numeric">{formatPercent(m.max_drawdown)}</td>
                  <td>
                    <StatusBadge status={run.engineering_status ?? run.status} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function signedClass(value?: number | null): string {
  if (value == null || Number.isNaN(value) || value === 0) return "";
  return value < 0 ? "value-negative" : "value-positive";
}
