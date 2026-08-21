import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import { getMarketSummary, type MarketSummary } from "../api/market";
import { getSystemHealth, type HealthResponse } from "../api/system";
import { getWorkflows, type Workflow } from "../api/workflows";
import { MetricCard, PageHeader, PageState, ServiceDot, StatusBadge } from "../components/Ui";
import { formatDate, formatDuration, formatNumber } from "../utils/format";
import { labels } from "../utils/labels";

interface DashboardData {
  health: HealthResponse;
  market: MarketSummary;
  workflows: Workflow[];
}

function healthTitle(status?: string): string {
  const s = (status ?? "").toLowerCase();
  if (s === "ok" || s === "healthy") return "Система работает нормально";
  if (s === "degraded" || s === "warning") return "Система работает с ограничениями";
  if (s === "error" || s === "failed") return "Обнаружены проблемы";
  return "Состояние системы неизвестно";
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      getSystemHealth(controller.signal),
      getMarketSummary(controller.signal),
      getWorkflows(controller.signal),
    ])
      .then(([health, market, workflows]) => setData({ health, market, workflows }))
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }

  useEffect(() => load(), []);

  if (loading) return <PageState kind="loading" title="Загрузка обзора…" />;
  if (error || !data) {
    return (
      <PageState kind="error" title="Не удалось получить данные" action={<button type="button" onClick={() => load()}>{labels.actions.retry}</button>}>
        {error}
      </PageState>
    );
  }

  const recent = [...data.workflows]
    .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""))
    .slice(0, 8);

  const serviceOrder = ["core_db", "memory_db", "redis", "worker"];

  return (
    <section>
      <PageHeader title={labels.nav.overview} description="Состояние платформы и рыночных данных" />

      <div className="hero-status">
        <div>
          <h2>ProjectAI</h2>
          <p className="subtitle">{healthTitle(data.health.status)}</p>
        </div>
        <StatusBadge status={data.health.status} />
      </div>

      <h2>Рыночные данные</h2>
      <div className="card-grid">
        <MetricCard label="Инструментов" value={formatNumber(data.market.instruments_count)} />
        <MetricCard label="Свечей" value={formatNumber(data.market.records_count)} />
        <MetricCard label="Рядов ЦБ" value={formatNumber(data.market.series_count ?? 0)} />
        <MetricCard
          label="Последние данные"
          value={formatDate(data.market.last_successful_update ?? null)}
          hint="по последней успешной загрузке"
        />
      </div>

      <div className="dashboard-grid">
        <article className="panel">
          <h2>Качество данных</h2>
          <div className="key-value">
            <span>Ошибки</span>
            <strong>{formatNumber(data.market.dq_errors)}</strong>
          </div>
          <div className="key-value">
            <span>Предупреждения</span>
            <strong>{formatNumber(data.market.dq_warnings)}</strong>
          </div>
          {data.market.dq_errors === 0 && data.market.dq_warnings === 0 ? (
            <p className="muted">Критичных проблем не зафиксировано.</p>
          ) : null}
        </article>

        <article className="panel">
          <h2>Состояние сервисов</h2>
          <div className="service-list">
            {serviceOrder.map((key) => (
              <div className="service-item" key={key}>
                <span>{labels.service(key)}</span>
                <ServiceDot status={data.health.services[key] ?? "unknown"} />
              </div>
            ))}
          </div>
        </article>
      </div>

      <article className="panel">
        <div className="page-header" style={{ marginBottom: "0.5rem" }}>
          <h2>Последние процессы</h2>
          <Link to="/workflows">Все процессы</Link>
        </div>
        {recent.length === 0 ? (
          <p className="muted">Процессов пока нет.</p>
        ) : (
          <div className="workflow-list">
            {recent.map((wf) => (
              <Link className="workflow-row" key={wf.id} to={`/workflows?focus=${wf.id}`}>
                <strong>{labels.workflowType(wf.workflow_type) || wf.name}</strong>
                <StatusBadge status={wf.status} />
                <span className="muted">{formatDuration(wf.duration_seconds)}</span>
              </Link>
            ))}
          </div>
        )}
      </article>
    </section>
  );
}
