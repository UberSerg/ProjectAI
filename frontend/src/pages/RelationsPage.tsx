import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getPairDetail,
  getRelationRuns,
  getRelationSnapshots,
  getRelationsOverview,
  type PairDetail,
  type RelationRun,
  type RelationSnapshot,
  type RelationsOverview,
} from "../api/relations";
import { errorMessage } from "../api/client";
import { getWorkflows, type Workflow } from "../api/workflows";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { RelationsBackfillModal } from "../features/relations/RelationsBackfillModal";
import { useRelationsActions } from "../features/relations/useRelationsActions";
import { MetricHelp } from "../help";
import { isWorkflowActive, usePolling } from "../hooks/usePolling";
import { formatDate, formatDateTime, formatNumber } from "../utils/format";
import { labels } from "../utils/labels";

function fmtCorr(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(3);
}

export function RelationsPage() {
  const [overview, setOverview] = useState<RelationsOverview | null>(null);
  const [runs, setRuns] = useState<RelationRun[]>([]);
  const [snapshots, setSnapshots] = useState<RelationSnapshot[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backfillOpen, setBackfillOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [windowObs, setWindowObs] = useState(60);
  const [sign, setSign] = useState<"all" | "positive" | "negative">("all");
  const [minAbs, setMinAbs] = useState(0.3);
  const [validOnly, setValidOnly] = useState(true);
  const [selected, setSelected] = useState<RelationSnapshot | null>(null);
  const [pairDetail, setPairDetail] = useState<PairDetail | null>(null);
  const [pairLoading, setPairLoading] = useState(false);
  const { runLatest, runBackfill } = useRelationsActions();

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const [ov, rr, wf, sn] = await Promise.all([
        getRelationsOverview(signal),
        getRelationRuns(15, signal),
        getWorkflows(signal),
        getRelationSnapshots(
          {
            window: windowObs,
            min_abs_corr: minAbs,
            sign,
            valid_only: validOnly,
            search: search.trim() || undefined,
            limit: 40,
          },
          signal,
        ),
      ]);
      setOverview(ov);
      setRuns(rr.items);
      setWorkflows(wf);
      setSnapshots(sn.items);
    },
    [windowObs, minAbs, sign, validOnly, search],
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

  const hasActiveRelationsWorkflow = useMemo(
    () =>
      workflows.some(
        (wf) =>
          (wf.workflow_type === "RelationsComputeLatest" || wf.workflow_type === "RelationsBackfill") &&
          isWorkflowActive(wf.status),
      ),
    [workflows],
  );

  usePolling(() => refresh(), 2000, hasActiveRelationsWorkflow && !loading && !error);

  useEffect(() => {
    if (!selected) {
      setPairDetail(null);
      return;
    }
    const controller = new AbortController();
    setPairLoading(true);
    getPairDetail(selected.input_a_id, selected.input_b_id, selected.window_observations, controller.signal)
      .then(setPairDetail)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
      })
      .finally(() => setPairLoading(false));
    return () => controller.abort();
  }, [selected]);

  async function handleBackfill(asOfFrom: string, asOfTo: string, cadence: string) {
    setBusy(true);
    try {
      await runBackfill(asOfFrom, asOfTo || undefined, cadence);
      setBackfillOpen(false);
    } finally {
      setBusy(false);
    }
  }

  if (error && !overview) return <PageState kind="error">{error}</PageState>;
  if (!overview) return <PageState kind="loading" title="Загрузка связей…" />;

  const rs = overview.active_relation_set;

  return (
    <section>
      <PageHeader
        title={labels.nav.relations}
        description="Статистическая структура рынка: корреляции и lead-lag. Не выдача BUY/SELL."
        helpPageId="relations"
        actions={
          <>
            <button type="button" className="secondary" disabled={busy} onClick={() => void runLatest()}>
              {labels.actions.computeRelations}
            </button>
            <button type="button" disabled={busy} onClick={() => setBackfillOpen(true)}>
              {labels.actions.backfillRelations}
            </button>
          </>
        }
      />

      <div className="card-grid">
        <MetricCard
          label="Активный набор"
          value={rs ? `${rs.code} v${rs.version}` : "—"}
          hint={rs?.description ?? undefined}
          helpId="relations_term"
        />
        <MetricCard label="Активные inputs" value={formatNumber(overview.inputs_active)} />
        <MetricCard label="Snapshots" value={formatNumber(overview.snapshots_total)} />
        <MetricCard label="Последний as_of" value={formatDate(overview.latest_as_of_date)} />
        <MetricCard label="Валидные" value={formatNumber(overview.quality.valid)} />
        <MetricCard label="Невалидные" value={formatNumber(overview.quality.invalid)} />
        <MetricCard
          label="Последний расчёт"
          value={
            overview.last_relation_run?.finished_at
              ? formatDateTime(overview.last_relation_run.finished_at)
              : "—"
          }
        />
      </div>

      <div className="panel" style={{ marginTop: "1.25rem" }}>
        <div className="panel-header">
          <h2>Топ связей</h2>
        </div>
        <div className="filters">
          <label>
            Поиск
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="SBER, IMOEX…"
            />
          </label>
          <label>
            Окно
            <select value={windowObs} onChange={(e) => setWindowObs(Number(e.target.value))}>
              <option value={20}>20</option>
              <option value={60}>60</option>
              <option value={120}>120</option>
            </select>
          </label>
          <label>
            Знак
            <select value={sign} onChange={(e) => setSign(e.target.value as typeof sign)}>
              <option value="all">Все</option>
              <option value="positive">Положительные</option>
              <option value="negative">Отрицательные</option>
            </select>
          </label>
          <label>
            |corr| ≥
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={minAbs}
              onChange={(e) => setMinAbs(Number(e.target.value))}
            />
          </label>
          <label>
            <span>Только валидные</span>
            <input type="checkbox" checked={validOnly} onChange={(e) => setValidOnly(e.target.checked)} />
          </label>
        </div>

        {snapshots.length === 0 ? (
          <p className="muted">Связей пока нет — запустите расчёт.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Пара</th>
                  <th>Окно</th>
                  <th>
                    Pearson <MetricHelp metricId="pearson" />
                  </th>
                  <th>
                    Spearman <MetricHelp metricId="spearman" />
                  </th>
                  <th>n</th>
                  <th>
                    Best lag <MetricHelp metricId="best_lag" />
                  </th>
                  <th>as_of</th>
                  <th>Valid</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.map((row) => (
                  <tr
                    key={row.id}
                    className={selected?.id === row.id ? "selected" : undefined}
                    onClick={() => setSelected(row)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>
                      {(row.input_a_display_name || row.input_a_code) ?? "—"} ↔{" "}
                      {(row.input_b_display_name || row.input_b_code) ?? "—"}
                    </td>
                    <td>{row.window_observations}</td>
                    <td>{fmtCorr(row.pearson)}</td>
                    <td>{fmtCorr(row.spearman)}</td>
                    <td>{row.sample_count}</td>
                    <td>
                      {row.best_lag != null
                        ? `${row.best_leader_code ?? "?"} → ${row.best_follower_code ?? "?"} (+${row.best_lag})`
                        : "—"}
                    </td>
                    <td>{formatDate(row.as_of_date)}</td>
                    <td>{row.is_valid ? "да" : "нет"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel" style={{ marginTop: "1.25rem" }}>
        <div className="panel-header">
          <h2>
            Обзор пары <MetricHelp metricId="relations_term" />
          </h2>
        </div>
        {!selected ? (
          <p className="muted">Выберите пару в таблице выше.</p>
        ) : pairLoading ? (
          <p className="muted">Загрузка профиля лагов…</p>
        ) : pairDetail ? (
          <>
            <p>
              <strong>
                {(pairDetail.snapshot.input_a_display_name || pairDetail.snapshot.input_a_code) ?? "A"} ↔{" "}
                {(pairDetail.snapshot.input_b_display_name || pairDetail.snapshot.input_b_code) ?? "B"}
              </strong>
              {" · "}окно {pairDetail.snapshot.window_observations}
              {" · "}as_of {formatDate(pairDetail.snapshot.as_of_date)}
              {" · "}pearson {fmtCorr(pairDetail.snapshot.pearson)}
            </p>
            <p className="muted">{pairDetail.disclaimer}</p>
            {pairDetail.lags.length === 0 ? (
              <p className="muted">Lag metrics отсутствуют.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Leader</th>
                      <th>Follower</th>
                      <th>Lag</th>
                      <th>Pearson</th>
                      <th>Spearman</th>
                      <th>n</th>
                      <th>Coverage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pairDetail.lags.map((lag) => (
                      <tr key={lag.id}>
                        <td>{lag.leader_code ?? lag.leader_input_id}</td>
                        <td>{lag.follower_code ?? lag.follower_input_id}</td>
                        <td>{lag.lag}</td>
                        <td>{fmtCorr(lag.pearson)}</td>
                        <td>{fmtCorr(lag.spearman)}</td>
                        <td>{lag.sample_count}</td>
                        <td>{lag.coverage_ratio != null ? lag.coverage_ratio.toFixed(2) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {pairDetail.snapshot.rolling_corr_mean != null ? (
              <p className="muted" style={{ marginTop: "0.75rem" }}>
                Stability: mean={fmtCorr(pairDetail.snapshot.rolling_corr_mean)}, std=
                {fmtCorr(pairDetail.snapshot.rolling_corr_std)}, sign_consistency=
                {fmtCorr(pairDetail.snapshot.sign_consistency)}
              </p>
            ) : (
              <p className="muted" style={{ marginTop: "0.75rem" }}>
                Stability metrics недоступны для окна 20 (subwindow = window).
              </p>
            )}
          </>
        ) : null}
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
                  <th>as_of</th>
                  <th>Snapshots</th>
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
                      {formatDate(run.as_of_from)}
                      {run.as_of_to ? ` → ${formatDate(run.as_of_to)}` : ""}
                      {run.cadence ? ` (${run.cadence})` : ""}
                    </td>
                    <td>
                      {run.snapshots_written} / valid {run.snapshots_valid}
                    </td>
                    <td>{formatDateTime(run.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <RelationsBackfillModal
        open={backfillOpen}
        busy={busy}
        onClose={() => setBackfillOpen(false)}
        onSubmit={(from, to, cadence) => void handleBackfill(from, to, cadence)}
      />
    </section>
  );
}
