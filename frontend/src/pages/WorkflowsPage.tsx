import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { getWorkflows, type Workflow } from "../api/workflows";
import { PageHeader, PageState, StatusBadge } from "../components/Ui";
import { ResearchCycleCard } from "../features/researchCycle/ResearchCycleCard";
import { isWorkflowActive, usePolling } from "../hooks/usePolling";
import { formatDateTime, formatDuration } from "../utils/format";
import { labels } from "../utils/labels";

function stepMark(status?: string | null): { cls: string; symbol: string } {
  const s = (status ?? "").toUpperCase();
  if (s === "SUCCESS" || s === "SUCCEEDED") return { cls: "", symbol: "✓" };
  if (s === "WARNING") return { cls: "warn", symbol: "⚠" };
  if (s === "ERROR" || s === "FAILED") return { cls: "err", symbol: "✕" };
  if (s === "RUNNING") return { cls: "run", symbol: "●" };
  if (s === "PENDING" || s === "") return { cls: "", symbol: "○" };
  return { cls: "", symbol: "○" };
}

export function WorkflowsPage() {
  const [params, setParams] = useSearchParams();
  const focus = params.get("focus");
  const [items, setItems] = useState<Workflow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(focus);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const list = await getWorkflows(signal);
    setItems(list);
    setSelectedId((current) => {
      if (focus) return focus;
      if (current && list.some((item) => String(item.id) === String(current))) return current;
      return list[0] ? String(list[0].id) : null;
    });
  }, [focus]);

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

  const hasActive = items.some((item) => isWorkflowActive(item.status));
  usePolling(() => refresh(), 2000, hasActive && !loading && !error);

  const selected = useMemo(
    () => items.find((item) => String(item.id) === String(selectedId)) ?? null,
    [items, selectedId],
  );

  function selectWorkflow(id: string) {
    setSelectedId(id);
    setParams({ focus: id }, { replace: true });
  }

  return (
    <section>
      <PageHeader title={labels.nav.workflows} description="Фоновые задачи загрузки и проверки качества" helpPageId="workflows" />

      <ResearchCycleCard />

      {loading ? <PageState kind="loading" title="Загрузка процессов…" /> : null}
      {!loading && error ? <PageState kind="error">{error}</PageState> : null}

      {!loading && !error && items.length === 0 ? (
        <PageState kind="empty" title="Процессов пока нет" />
      ) : null}

      {!loading && !error && items.length > 0 ? (
        <div className="dashboard-grid">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Процесс</th>
                  <th>Статус</th>
                  <th>Начало</th>
                  <th>Завершение</th>
                  <th>Длительность</th>
                </tr>
              </thead>
              <tbody>
                {items.map((wf) => (
                  <tr
                    key={wf.id}
                    className={`clickable${String(selectedId) === String(wf.id) ? " selected" : ""}`}
                    tabIndex={0}
                    aria-selected={String(selectedId) === String(wf.id)}
                    onClick={() => selectWorkflow(String(wf.id))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        selectWorkflow(String(wf.id));
                      }
                    }}
                  >
                    <td>
                      <strong>{labels.workflowType(wf.workflow_type) || wf.name}</strong>
                    </td>
                    <td>
                      <StatusBadge status={wf.status} />
                    </td>
                    <td>{formatDateTime(wf.started_at)}</td>
                    <td>{formatDateTime(wf.finished_at)}</td>
                    <td>{formatDuration(wf.duration_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <article className="panel" key={selected ? String(selected.id) : "empty"}>
            {selected ? (
              <>
                <h2>{labels.workflowType(selected.workflow_type) || selected.name}</h2>
                <p className="muted mono">{selected.workflow_type}</p>
                <div className="key-value">
                  <span>Статус</span>
                  <StatusBadge status={selected.status} />
                </div>
                <div className="key-value">
                  <span>Начало</span>
                  <strong>{formatDateTime(selected.started_at)}</strong>
                </div>
                <div className="key-value">
                  <span>Завершение</span>
                  <strong>{formatDateTime(selected.finished_at)}</strong>
                </div>
                <div className="key-value">
                  <span>Длительность</span>
                  <strong>{formatDuration(selected.duration_seconds)}</strong>
                </div>
                {selected.error ? <p className="page-state error">{selected.error}</p> : null}

                <h2 style={{ marginTop: "1rem" }}>Шаги</h2>
                <ul className="timeline">
                  {selected.steps.map((step) => {
                    const mark = stepMark(step.status);
                    return (
                      <li className="timeline-item" key={`${selected.id}-${step.name}`}>
                        <span className={`timeline-mark ${mark.cls}`}>{mark.symbol}</span>
                        <div>
                          <strong>{labels.workflowStep(step.name)}</strong>
                          <div className="muted">{labels.status(step.status)}</div>
                          {step.error ? (
                            <div className="page-state error" style={{ marginTop: "0.35rem" }}>
                              {step.error}
                            </div>
                          ) : null}
                        </div>
                        <StatusBadge status={step.status} />
                      </li>
                    );
                  })}
                </ul>

                <details className="details-tech">
                  <summary>Технические детали</summary>
                  <pre className="mono" style={{ whiteSpace: "pre-wrap", fontSize: "0.8rem" }}>
                    {JSON.stringify(selected, null, 2)}
                  </pre>
                </details>
              </>
            ) : (
              <p className="muted">Выберите процесс в таблице.</p>
            )}
          </article>
        </div>
      ) : null}
    </section>
  );
}
