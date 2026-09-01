import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  getTechnicalOverview,
  getTechnicalRuns,
  getTechnicalSignals,
  type TechnicalOverview,
  type TechnicalRun,
  type TechnicalSignal,
} from "../api/technical";
import { errorMessage } from "../api/client";
import { getWorkflows, type Workflow } from "../api/workflows";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { TechnicalBackfillModal } from "../features/technical/TechnicalBackfillModal";
import { useTechnicalActions } from "../features/technical/useTechnicalActions";
import { isWorkflowActive, usePolling } from "../hooks/usePolling";
import { formatDate, formatDateTime, formatNumber, formatPercent, formatZScore } from "../utils/format";
import { labels } from "../utils/labels";

function fmtScore(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

function fmtRsi(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(1);
}

function qualityLabel(row: TechnicalSignal): string {
  if (!row.is_valid) return "невалид";
  if (row.quality_flags && Object.keys(row.quality_flags).length > 0) return "предупреждение";
  return "ок";
}

export function TechnicalPage() {
  const [overview, setOverview] = useState<TechnicalOverview | null>(null);
  const [runs, setRuns] = useState<TechnicalRun[]>([]);
  const [signals, setSignals] = useState<TechnicalSignal[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backfillOpen, setBackfillOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<"all" | "bullish" | "neutral" | "bearish">("all");
  const [minConfidence, setMinConfidence] = useState(0);
  const [validOnly, setValidOnly] = useState(true);
  const { runUpdate, runBackfill } = useTechnicalActions();

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const [ov, rr, wf, sig] = await Promise.all([
        getTechnicalOverview(signal),
        getTechnicalRuns(15, signal),
        getWorkflows(signal),
        getTechnicalSignals(
          {
            direction: stateFilter === "all" ? undefined : stateFilter,
            min_confidence: minConfidence > 0 ? minConfidence : undefined,
            valid_only: validOnly,
            instrument: search.trim() || undefined,
            limit: 100,
          },
          signal,
        ),
      ]);
      setOverview(ov);
      setRuns(rr);
      setWorkflows(wf);
      setSignals(sig);
      setError(null);
    },
    [stateFilter, minConfidence, validOnly, search],
  );

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

  const hasActiveTechnicalWorkflow = useMemo(
    () =>
      workflows.some(
        (wf) =>
          (wf.workflow_type === "TechnicalBackfill" || wf.workflow_type === "TechnicalUpdate") &&
          isWorkflowActive(wf.status),
      ),
    [workflows],
  );

  usePolling(() => refresh(), 2000, hasActiveTechnicalWorkflow && !loading && !error);

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
  if (!overview) return <PageState kind="loading" title="Загрузка технического анализа…" />;

  return (
    <section>
      <PageHeader
        title={labels.nav.technical}
        description="Правила rules_v1: score и confidence по тренду, моментуму, RSI и объёму. Не рекомендация BUY/SELL."
        actions={
          <>
            <button type="button" className="secondary" disabled={busy} onClick={() => void runUpdate()}>
              {labels.actions.updateTechnical}
            </button>
            <button type="button" disabled={busy} onClick={() => setBackfillOpen(true)}>
              {labels.actions.backfillTechnical}
            </button>
          </>
        }
      />

      <div className="dashboard-grid">
        <MetricCard label="Активная модель" value={overview.active_model} />
        <MetricCard label="Feature set" value={overview.technical_feature_set} />
        <MetricCard label="As of" value={formatDate(overview.as_of)} />
        <MetricCard label="Бычье" value={formatNumber(overview.bullish)} />
        <MetricCard label="Нейтральное" value={formatNumber(overview.neutral)} />
        <MetricCard label="Медвежье" value={formatNumber(overview.bearish)} />
        <MetricCard label="Невалидные" value={formatNumber(overview.invalid)} />
        <MetricCard
          label="Последний расчёт"
          value={
            overview.last_run?.finished_at ? formatDateTime(overview.last_run.finished_at) : "—"
          }
        />
      </div>

      <div className="panel" style={{ marginTop: "1.25rem" }}>
        <div className="panel-header">
          <h2>Сигналы</h2>
        </div>
        <div className="filters">
          <label>
            Поиск
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="SBER, LKOH…"
            />
          </label>
          <label>
            Состояние
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value as typeof stateFilter)}
            >
              <option value="all">Все</option>
              <option value="bullish">{labels.direction("bullish")}</option>
              <option value="neutral">{labels.direction("neutral")}</option>
              <option value="bearish">{labels.direction("bearish")}</option>
            </select>
          </label>
          <label>
            Min confidence
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={minConfidence}
              onChange={(e) => setMinConfidence(Number(e.target.value))}
            />
          </label>
          <label>
            <span>Только valid</span>
            <input type="checkbox" checked={validOnly} onChange={(e) => setValidOnly(e.target.checked)} />
          </label>
        </div>

        {signals.length === 0 ? (
          <p className="muted">Сигналов пока нет — запустите обновление или backfill.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Instrument</th>
                  <th>State</th>
                  <th>Score</th>
                  <th title={labels.tooltips.confidence}>Confidence</th>
                  <th>RSI14</th>
                  <th>SMA20 dist</th>
                  <th>EMA20 dist</th>
                  <th>ATR14%</th>
                  <th>Volume Z</th>
                  <th>Quality</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link to={`/market/instruments/${encodeURIComponent(row.instrument_id)}`}>
                        {row.ticker ?? row.instrument_id}
                      </Link>
                    </td>
                    <td>{labels.direction(row.direction)}</td>
                    <td className="numeric">{fmtScore(row.score)}</td>
                    <td className="numeric" title={labels.tooltips.confidence}>
                      {formatPercent(row.confidence)}
                    </td>
                    <td className="numeric">{fmtRsi(row.rsi14)}</td>
                    <td className="numeric">{formatPercent(row.sma20_distance)}</td>
                    <td className="numeric">{formatPercent(row.ema20_distance)}</td>
                    <td className="numeric">{formatPercent(row.atr14_pct)}</td>
                    <td className="numeric">{formatZScore(row.volume_zscore_20d)}</td>
                    <td>{qualityLabel(row)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel" style={{ marginTop: "1.25rem" }}>
        <div className="panel-header">
          <h2>Последние запуски</h2>
        </div>
        {runs.length === 0 ? (
          <p className="muted">Расчётов пока нет</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Тип</th>
                  <th>Статус</th>
                  <th>Период</th>
                  <th>Сигналы</th>
                  <th>Завершён</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>{run.id}</td>
                    <td>{run.run_type}</td>
                    <td>
                      <StatusBadge status={run.status} />
                    </td>
                    <td>
                      {formatDate(run.date_from)}
                      {run.date_to ? ` → ${formatDate(run.date_to)}` : ""}
                    </td>
                    <td>
                      {run.signal_rows} / valid {run.valid_signals}
                    </td>
                    <td>{formatDateTime(run.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <TechnicalBackfillModal
        open={backfillOpen}
        busy={busy}
        onClose={() => setBackfillOpen(false)}
        onSubmit={(from, to) => void handleBackfill(from, to)}
      />
    </section>
  );
}
