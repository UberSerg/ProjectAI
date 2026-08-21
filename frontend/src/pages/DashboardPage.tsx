import { useEffect, useState } from "react";
import { errorMessage } from "../api/client";
import {
  getBatches,
  getDataQualityIssues,
  getInstruments,
  getMarketSummary,
  type MarketSummary,
} from "../api/market";
import { getSystemHealth, type HealthResponse } from "../api/system";
import { getWorkflows, type Workflow } from "../api/workflows";
import { formatDate, formatNumber, PageState, StatusBadge } from "../components/Ui";

interface DashboardData {
  health: HealthResponse;
  market: MarketSummary;
  workflows: Workflow[];
}

async function loadMarketSummary(signal: AbortSignal): Promise<MarketSummary> {
  try {
    return await getMarketSummary(signal);
  } catch {
    const [instruments, batches, issues] = await Promise.all([
      getInstruments({ page: 1, page_size: 10_000 }, signal),
      getBatches(undefined, signal),
      getDataQualityIssues(undefined, signal),
    ]);
    return {
      instruments_count: instruments.total,
      active_instruments_count: instruments.items.filter((item) => item.is_active).length,
      records_count: instruments.items.reduce((sum, item) => sum + item.records_count, 0),
      batches_count: batches.length,
      dq_warnings: issues.filter((issue) => issue.severity === "warning").length,
      dq_errors: issues.filter((issue) => issue.severity === "error").length,
    };
  }
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getSystemHealth(controller.signal),
      loadMarketSummary(controller.signal),
      getWorkflows(controller.signal),
    ])
      .then(([health, market, workflows]) => setData({ health, market, workflows }))
      .catch((reason: unknown) => setError(errorMessage(reason)))
      .finally(() => setLoading(false));
    return () => {
      controller.abort();
    };
  }, []);

  if (loading) return <PageState kind="loading">Loading dashboard metrics…</PageState>;
  if (error || !data) return <PageState kind="error">Unable to load dashboard: {error}</PageState>;

  const running = data.workflows.filter((workflow) => workflow.status === "running").length;
  const failed = data.workflows.filter((workflow) => workflow.status === "failed").length;
  const lastSuccess = data.workflows
    .filter((workflow) => workflow.status === "succeeded" || workflow.status === "success")
    .sort((a, b) => (b.finished_at ?? "").localeCompare(a.finished_at ?? ""))[0];

  return (
    <section>
      <h1>ProjectAI Dashboard</h1>
      <p className="subtitle">Market data operations overview</p>
      <div className="card-grid">
        <article className="metric-card">
          <span className="metric-label">System health</span>
          <StatusBadge status={data.health.status} />
          <small>{Object.entries(data.health.services).map(([name, status]) => `${name}: ${status}`).join(" · ") || "No service details"}</small>
        </article>
        <article className="metric-card">
          <span className="metric-label">Instruments</span>
          <strong>{formatNumber(data.market.instruments_count)}</strong>
          <small>{formatNumber(data.market.active_instruments_count)} active · {formatNumber(data.market.records_count)} records</small>
        </article>
        <article className="metric-card">
          <span className="metric-label">Data quality</span>
          <strong>{formatNumber(data.market.dq_errors)} errors</strong>
          <small>{formatNumber(data.market.dq_warnings)} warnings</small>
        </article>
        <article className="metric-card">
          <span className="metric-label">Workflows</span>
          <strong>{running} running</strong>
          <small>{failed} failed · last success {formatDate(lastSuccess?.finished_at)}</small>
        </article>
      </div>
    </section>
  );
}
