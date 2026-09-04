import { useCallback, useEffect, useState } from "react";
import { errorMessage } from "../../api/client";
import {
  getResearchCycleLatest,
  type ResearchCycleLatestResponse,
  type ResearchCycleRun,
  type ResearchCycleStep,
} from "../../api/researchCycle";
import { PageState } from "../../components/Ui";
import { MetricHelp } from "../../help";
import { formatDate, formatDateTime, formatDuration } from "../../utils/format";
import {
  researchCycleHealthLabel,
  researchCycleStatusDisplay,
  researchCycleStatusTone,
  researchCycleStepLabel,
  shadowSummaryFromWatermarks,
} from "./helpers";

function stepMark(status?: string | null): { cls: string; symbol: string } {
  const s = (status ?? "").toUpperCase();
  if (s === "SUCCESS" || s === "SUCCEEDED" || s === "NO_CHANGES" || s === "SKIPPED_NOT_DUE") {
    return { cls: "", symbol: "✓" };
  }
  if (s === "WARNING" || s === "PARTIALLY_MATURED") return { cls: "warn", symbol: "⚠" };
  if (s === "ERROR" || s === "FAILED" || s === "INVALID") return { cls: "err", symbol: "✕" };
  if (s === "RUNNING" || s === "WAITING_FOR_MARKET" || s === "PENDING_OUTCOME") {
    return { cls: "run", symbol: "●" };
  }
  if (s === "PENDING" || s === "") return { cls: "", symbol: "○" };
  return { cls: "", symbol: "○" };
}

function StepStatusBadge({ status }: { status?: string | null }) {
  const tone = researchCycleStatusTone(status);
  return <span className={`badge badge-${tone}`}>{researchCycleStatusDisplay(status)}</span>;
}

function effectiveStepStatus(step: ResearchCycleStep, run: ResearchCycleRun | null): string {
  const stepResults = (run?.meta?.step_results ?? {}) as Record<string, { status?: string }>;
  return stepResults[step.name]?.status ?? step.status;
}

export function ResearchCycleCard() {
  const [data, setData] = useState<ResearchCycleLatestResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const latest = await getResearchCycleLatest(signal);
    setData(latest);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    refresh(controller.signal)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [refresh]);

  if (loading) {
    return (
      <article className="panel research-cycle-card">
        <PageState kind="loading" title="Загрузка исследовательского цикла…" />
      </article>
    );
  }

  if (error) {
    return (
      <article className="panel research-cycle-card">
        <h2 className="research-cycle-title">
          Ежедневный исследовательский цикл <MetricHelp metricId="research_cycle" />
        </h2>
        <PageState kind="error">{error}</PageState>
      </article>
    );
  }

  const operational = data?.operational;
  const run = data?.run ?? null;
  const brief = operational?.latest_cycle ?? null;
  const wm = operational?.watermarks;
  const before = brief?.market_watermark_before ?? null;
  const after = brief?.market_watermark_after ?? wm?.raw_market_latest_date ?? null;
  const duration =
    brief?.duration_seconds ??
    (typeof run?.meta?.duration_seconds === "number" ? run.meta.duration_seconds : null);
  const forwardBatch =
    brief?.latest_forward_batch_id ?? wm?.forward_latest_batch_id ?? null;
  const outcomeStatus = wm?.forward_outcome_latest_status;
  const shadowSummary = shadowSummaryFromWatermarks(wm?.shadow_portfolios);
  const hasRun = Boolean(run || brief);

  return (
    <article className="panel research-cycle-card">
      <header className="research-cycle-head">
        <div>
          <h2 className="research-cycle-title">
            Ежедневный исследовательский цикл <MetricHelp metricId="research_cycle" />
          </h2>
          <p className="muted">
            Операционный контур: рынок → признаки → Forward → Shadow → outcomes
          </p>
        </div>
        <span className={`badge badge-${researchCycleStatusTone(operational?.health)}`}>
          {researchCycleHealthLabel(operational?.health, operational?.health_human)}
          <MetricHelp metricId="daily_cycle_health" />
        </span>
      </header>

      {!hasRun ? (
        <PageState kind="empty" title="Цикл ещё не запускался">
          Статус контура доступен; история прогонов появится после первого запуска.
        </PageState>
      ) : null}

      <div className="research-cycle-grid">
        <div className="key-value">
          <span>Состояние контура</span>
          <strong>
            {researchCycleHealthLabel(operational?.health, operational?.health_human)}
          </strong>
        </div>
        <div className="key-value">
          <span>Последний прогон</span>
          <strong>
            {brief || run ? (
              <StepStatusBadge status={brief?.status ?? run?.status} />
            ) : (
              "—"
            )}
          </strong>
        </div>
        <div className="key-value">
          <span>Начало</span>
          <strong>{formatDateTime(brief?.started_at ?? run?.started_at)}</strong>
        </div>
        <div className="key-value">
          <span>Завершение</span>
          <strong>{formatDateTime(brief?.finished_at ?? run?.finished_at)}</strong>
        </div>
        <div className="key-value">
          <span>Длительность</span>
          <strong>{formatDuration(duration)}</strong>
        </div>
        <div className="key-value">
          <span>Market watermark</span>
          <strong>
            {formatDate(before)} → {formatDate(after)}
          </strong>
        </div>
        <div className="key-value">
          <span>Последний Forward batch</span>
          <strong>
            {forwardBatch != null ? `#${forwardBatch}` : "—"}
            {wm?.forward_latest_as_of ? (
              <span className="muted"> · as_of {formatDate(wm.forward_latest_as_of)}</span>
            ) : null}
          </strong>
        </div>
        <div className="key-value">
          <span>Shadow</span>
          <strong>{shadowSummary}</strong>
        </div>
        <div className="key-value">
          <span>
            Outcome evaluation <MetricHelp metricId="forward_outcome_pending" />
          </span>
          <strong>
            {outcomeStatus ? researchCycleStatusDisplay(outcomeStatus) : "—"}
            {wm?.forward_outcome_latest_evaluated_at ? (
              <span className="muted">
                {" "}
                · {formatDateTime(wm.forward_outcome_latest_evaluated_at)}
              </span>
            ) : null}
          </strong>
        </div>
      </div>

      {(brief?.error || run?.error) && (
        <p className="page-state error">{brief?.error ?? run?.error}</p>
      )}

      {run?.steps?.length ? (
        <details className="research-cycle-steps">
          <summary>Шаги цикла ({run.steps.length})</summary>
          <ul className="timeline">
            {run.steps.map((step) => {
              const status = effectiveStepStatus(step, run);
              const mark = stepMark(status);
              return (
                <li className="timeline-item" key={`${run.id}-${step.name}`}>
                  <span className={`timeline-mark ${mark.cls}`}>{mark.symbol}</span>
                  <div>
                    <strong>{researchCycleStepLabel(step.name)}</strong>
                    <div className="muted">{researchCycleStatusDisplay(status)}</div>
                    {step.error ? (
                      <div className="page-state error" style={{ marginTop: "0.35rem" }}>
                        {step.error}
                      </div>
                    ) : null}
                  </div>
                  <StepStatusBadge status={status} />
                </li>
              );
            })}
          </ul>
        </details>
      ) : null}

      <details className="details-tech">
        <summary>Технические детали</summary>
        <pre className="mono" style={{ whiteSpace: "pre-wrap", fontSize: "0.8rem" }}>
          {JSON.stringify(
            {
              health: operational?.health,
              health_human: operational?.health_human,
              automatic_schedule: operational?.automatic_schedule,
              schedule: operational?.schedule,
              outcome_maturity: operational?.outcome_maturity,
              latest_cycle: brief,
              run: run
                ? {
                    id: run.id,
                    status: run.status,
                    workflow_type: run.workflow_type,
                    error: run.error,
                    meta: run.meta,
                    steps: run.steps,
                  }
                : null,
              watermarks: wm,
            },
            null,
            2,
          )}
        </pre>
        <p className="muted" style={{ marginTop: "0.5rem" }}>
          Технические коды: health=<code>{operational?.health ?? "—"}</code>, run=
          <code>{brief?.status ?? run?.status ?? "—"}</code>, outcome=
          <code>{outcomeStatus ?? "—"}</code>
        </p>
      </details>
    </article>
  );
}
