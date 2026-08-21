import { useEffect, useState } from "react";
import { errorMessage } from "../api/client";
import { getWorkflow, getWorkflows, type Workflow } from "../api/workflows";
import { formatDate, PageState, StatusBadge } from "../components/Ui";

export function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[] | null>(null);
  const [selected, setSelected] = useState<Workflow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getWorkflows(controller.signal)
      .then(setWorkflows)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
      });
    return () => controller.abort();
  }, []);

  async function selectWorkflow(workflow: Workflow) {
    setSelected(workflow);
    setDetailError(null);
    try {
      setSelected(await getWorkflow(workflow.id));
    } catch (reason) {
      setDetailError(errorMessage(reason));
    }
  }

  return (
    <section>
      <h1>Workflows</h1>
      <p className="subtitle">Execution history and step-level diagnostics</p>
      {error ? <PageState kind="error">Unable to load workflows: {error}</PageState> : null}
      {!error && workflows === null ? <PageState kind="loading">Loading workflows…</PageState> : null}
      {workflows?.length === 0 ? <PageState kind="empty">No workflows have run yet.</PageState> : null}
      {workflows && workflows.length > 0 ? (
        <div className="split-view">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Type</th><th>Status</th><th>Started</th><th>Finished</th></tr></thead>
              <tbody>{workflows.map((workflow) => <tr key={workflow.id} className={`clickable ${selected?.id === workflow.id ? "selected" : ""}`} onClick={() => void selectWorkflow(workflow)}><td><strong>{workflow.name}</strong><small className="cell-subtitle mono">{workflow.id}</small></td><td>{workflow.workflow_type}</td><td><StatusBadge status={workflow.status} /></td><td>{formatDate(workflow.started_at)}</td><td>{formatDate(workflow.finished_at)}</td></tr>)}</tbody>
            </table>
          </div>
          <aside className="panel workflow-detail">
            {!selected ? <p className="muted">Select a workflow to inspect its steps.</p> : (
              <>
                <div className="page-header"><div><h2>{selected.name}</h2><span className="mono">{selected.id}</span></div><StatusBadge status={selected.status} /></div>
                {detailError ? <div className="banner error">Latest detail unavailable: {detailError}</div> : null}
                {selected.error ? <pre className="error-box">{selected.error}</pre> : null}
                <h3>Steps</h3>
                {selected.steps.length ? selected.steps.map((step, index) => <div className="workflow-step" key={step.id ?? `${step.name}-${index}`}><StatusBadge status={step.status} /><div><strong>{step.name}</strong><small>{formatDate(step.started_at)} — {formatDate(step.finished_at)}</small>{step.error ? <pre className="error-box">{step.error}</pre> : null}</div></div>) : <p className="muted">No step details.</p>}
              </>
            )}
          </aside>
        </div>
      ) : null}
    </section>
  );
}
