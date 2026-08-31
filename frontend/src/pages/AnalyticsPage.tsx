import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getAnalyticsOverview,
  getFeatureRuns,
  type AnalyticsOverview,
  type FeatureRun,
} from "../api/analytics";
import { errorMessage } from "../api/client";
import { getWorkflows, type Workflow } from "../api/workflows";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { FeatureBackfillModal } from "../features/analytics/FeatureBackfillModal";
import { useAnalyticsActions } from "../features/analytics/useAnalyticsActions";
import { isWorkflowActive, usePolling } from "../hooks/usePolling";
import { formatDate, formatDateRange, formatDateTime, formatDuration, formatNumber } from "../utils/format";
import { labels } from "../utils/labels";

export function AnalyticsPage() {
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [runs, setRuns] = useState<FeatureRun[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backfillOpen, setBackfillOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const { runUpdate, runBackfill } = useAnalyticsActions();

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const [ov, fr, wf] = await Promise.all([
      getAnalyticsOverview(signal),
      getFeatureRuns(15, signal),
      getWorkflows(signal),
    ]);
    setOverview(ov);
    setRuns(fr.items);
    setWorkflows(wf);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    refresh(controller.signal)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [refresh]);

  const hasActiveFeatureWorkflow = useMemo(
    () =>
      workflows.some(
        (wf) =>
          (wf.workflow_type === "FeatureBackfill" || wf.workflow_type === "FeatureUpdate") &&
          isWorkflowActive(wf.status),
      ),
    [workflows],
  );

  usePolling(() => refresh(), 2000, hasActiveFeatureWorkflow && !loading && !error);

  async function handleBackfill(dateFrom: string, dateTo: string) {
    setBusy(true);
    try {
      await runBackfill(dateFrom, dateTo || undefined);
      setBackfillOpen(false);
    } finally {
      setBusy(false);
    }
  }

  if (error && !overview) return <PageState kind="error">{error}</PageState>;
  if (!overview) return <PageState kind="loading" title="Загрузка аналитики…" />;

  const fs = overview.active_feature_set;

  return (
    <section>
      <PageHeader
        title={labels.nav.analytics}
        description="Версионируемые производные признаки из рыночных данных"
        actions={
          <>
            <button type="button" className="secondary" disabled={busy} onClick={() => void runUpdate()}>
              {labels.actions.updateFeatures}
            </button>
            <button type="button" disabled={busy} onClick={() => setBackfillOpen(true)}>
              {labels.actions.backfillFeatures}
            </button>
          </>
        }
      />

      <div className="dashboard-grid">
        <MetricCard
          label="Активный набор"
          value={fs ? `${fs.code} v${fs.version}` : "—"}
          hint={fs?.description ?? undefined}
        />
        <MetricCard
          label="Покрытие инструментов"
          value={`${overview.instruments_with_features} / ${overview.instruments_active}`}
        />
        <MetricCard
          label="Последняя дата данных"
          value={formatDate(overview.latest_calculated_date)}
        />
        <MetricCard label="Строк признаков" value={formatNumber(overview.instrument_feature_rows)} />
        <MetricCard label="Валидные" value={formatNumber(overview.quality.valid)} />
        <MetricCard label="С предупреждениями" value={formatNumber(overview.quality.warnings)} />
        <MetricCard label="Невалидные" value={formatNumber(overview.quality.invalid)} />
        <MetricCard
          label="Последний расчёт"
          value={
            overview.last_feature_run?.finished_at
              ? formatDateTime(overview.last_feature_run.finished_at)
              : "—"
          }
        />
      </div>

      <article className="panel" style={{ marginTop: "1rem" }}>
        <h2>Последние расчёты признаков</h2>
        {runs.length === 0 ? (
          <PageState kind="empty" title="Расчётов пока нет" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Тип</th>
                  <th>Период</th>
                  <th>Набор</th>
                  <th>Статус</th>
                  <th>Инструментов</th>
                  <th>Строк</th>
                  <th>Предупреждений</th>
                  <th>Начат</th>
                  <th>Длительность</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const started = run.started_at ? new Date(run.started_at).getTime() : null;
                  const finished = run.finished_at ? new Date(run.finished_at).getTime() : null;
                  const duration =
                    started && finished ? Math.round((finished - started) / 1000) : undefined;
                  return (
                    <tr key={run.id}>
                      <td>{run.run_type}</td>
                      <td>{formatDateRange(run.date_from, run.date_to)}</td>
                      <td className="mono">
                        {run.feature_set_code ?? "—"} v{run.feature_set_version ?? "?"}
                      </td>
                      <td>
                        <StatusBadge status={run.status} />
                      </td>
                      <td>{run.instruments_total}</td>
                      <td>{run.instrument_rows_calculated + run.series_rows_calculated}</td>
                      <td>{run.rows_invalid}</td>
                      <td>{formatDateTime(run.started_at)}</td>
                      <td>{formatDuration(duration)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </article>

      <FeatureBackfillModal
        open={backfillOpen}
        busy={busy}
        onClose={() => setBackfillOpen(false)}
        onSubmit={(from, to) => void handleBackfill(from, to)}
      />
    </section>
  );
}
