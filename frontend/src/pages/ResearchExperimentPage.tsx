import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { getResearchRun, type ResearchRunSummary } from "../api/researchLab";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { MetricHelp } from "../help";
import {
  bpsLabel,
  experimentName,
  policyHumanName,
  riskHumanName,
} from "../features/researchLab/labels";
import { formatDateRange, formatPercent, shortHash } from "../utils/format";
import { labels } from "../utils/labels";

export function ResearchExperimentPage() {
  const { runId } = useParams();
  const [run, setRun] = useState<ResearchRunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    getResearchRun(runId, controller.signal)
      .then(setRun)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, [runId]);

  if (error) return <PageState kind="error">{error}</PageState>;
  if (!run) return <PageState kind="loading" title="Загрузка эксперимента…" />;

  const m = run.metrics ?? {};
  const research = run.research;

  return (
    <section>
      <PageHeader
        title={experimentName(run)}
        description="Исторический исследовательский результат"
        helpPageId="research_lab"
        actions={
          <>
            <Link to="/research" className="secondary button-link">
              ← {labels.nav.lab}
            </Link>
            <Link to={`/simulator/${run.id}`} className="primary button-link">
              Открыть симуляцию
            </Link>
            <Link to="/shadow" className="secondary button-link">
              {labels.nav.liveExperiment}
            </Link>
          </>
        }
      />

      <p className="muted">
        {labels.nav.lab} → {experimentName(run)} → Симуляция
      </p>

      <div className="info-panel">
        <h3>
          Research context <MetricHelp metricId="research_experiment" />
        </h3>
        <ul>
          <li>Контекст: историческое исследование</li>
          <li>
            Сегмент: {run.segment === "FINAL_HOLDOUT" ? "FINAL HOLDOUT" : "Development OOS"}{" "}
            <MetricHelp metricId={run.segment === "FINAL_HOLDOUT" ? "observed_holdout" : "development_oos"} />
          </li>
          <li>
            Модель: {run.spec?.candidate_name}/{run.spec?.candidate_version}{" "}
            <MetricHelp metricId="candidate_model" />
          </li>
          <li>
            Стратегия: {policyHumanName(run.spec?.policy_name)}{" "}
            <MetricHelp metricId="portfolio_policy" />
          </li>
          <li>
            Risk: {riskHumanName(run.spec?.risk_name)} <MetricHelp metricId="risk_policy" />
          </li>
          <li>
            Издержки: {bpsLabel(run.spec?.commission_bps)} <MetricHelp metricId="simulation_cost" />
          </li>
          <li>Период: {formatDateRange(run.date_from, run.date_to)}</li>
          {research?.note ? <li>Заметка: {research.note}</li> : null}
          {research?.observed_holdout ? (
            <li>
              <span className="badge badge-warning">Уже наблюдавшийся holdout</span> — можно
              анализировать, но нельзя использовать как свежую проверку настройки.{" "}
              <MetricHelp metricId="observed_holdout" />
            </li>
          ) : null}
        </ul>
        <p className="field-hint">
          Shadow Portfolio работает только вперёд и не пересчитывает прошлое.{" "}
          <Link to="/shadow">Перейти в живой эксперимент</Link>
        </p>
      </div>

      <div className="metric-grid">
        <MetricCard
          label="Доходность"
          value={formatPercent(m.total_price_return)}
          helpId="sim_cagr"
        />
        <MetricCard
          label="Максимальная просадка"
          value={formatPercent(m.max_drawdown)}
          helpId="sim_max_drawdown"
        />
        <MetricCard
          label="Оборот"
          value={m.turnover_ratio != null ? `${Number(m.turnover_ratio).toFixed(1)}×` : "—"}
          helpId="sim_turnover"
        />
        <MetricCard label="Статус" value={<StatusBadge status={run.status} />} />
      </div>

      <details>
        <summary>Технические детали</summary>
        <pre className="tech-block">
          {JSON.stringify(
            {
              config_hash: run.spec?.config_hash,
              candidate_config_hash: run.candidate_config_hash,
              dataset_values_hash: run.dataset_values_hash,
              prediction_hash: run.prediction_hash,
              policy: run.spec?.policy_name,
              risk: run.spec?.risk_name,
              commission_bps: run.spec?.commission_bps,
              period: { from: run.date_from, to: run.date_to },
              created_from: research?.created_from,
              short_config: shortHash(run.spec?.config_hash),
            },
            null,
            2,
          )}
        </pre>
        <p className="field-hint">
          Config hash <MetricHelp metricId="config_hash" /> — математическая идентичность без name/note.
        </p>
      </details>
    </section>
  );
}
