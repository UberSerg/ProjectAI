import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  compareResearchRuns,
  type CompareNavPoint,
  type CompareResponse,
} from "../api/researchLab";
import { PageHeader, PageState } from "../components/Ui";
import { MetricHelp } from "../help";
import { experimentName, policyHumanName, riskHumanName } from "../features/researchLab/labels";
import { formatPercent } from "../utils/format";

function MultiLineChart({
  series,
  valueKey,
  title,
}: {
  series: Array<{ id: number; name: string; points: CompareNavPoint[] }>;
  valueKey: "nav_normalized" | "drawdown";
  title: string;
}) {
  const width = 720;
  const height = 260;
  const pad = 28;
  const colors = ["#2a6f97", "#bc4749", "#6a994e", "#e09f3e", "#5e548e"];

  const all = series.flatMap((s) => s.points.map((p) => p[valueKey]));
  if (!all.length) return <PageState kind="empty">Нет точек для графика.</PageState>;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;

  const pathFor = (points: CompareNavPoint[]) => {
    if (!points.length) return "";
    return points
      .map((p, i) => {
        const x = pad + (i / Math.max(points.length - 1, 1)) * (width - pad * 2);
        const y = height - pad - ((p[valueKey] - min) / span) * (height - pad * 2);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  };

  return (
    <div className="chart-card">
      <h3>{title}</h3>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title} className="compare-chart">
        {series.map((s, idx) => (
          <path key={s.id} d={pathFor(s.points)} fill="none" stroke={colors[idx % colors.length]} strokeWidth={2} />
        ))}
      </svg>
      <div className="chip-row">
        {series.map((s, idx) => (
          <span key={s.id} style={{ color: colors[idx % colors.length] }}>
            {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}

function formatMetric(metricId: string, value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (
    metricId.includes("return") ||
    metricId.includes("cagr") ||
    metricId.includes("drawdown") ||
    metricId.includes("volatility") ||
    metricId.includes("excess") ||
    metricId.includes("imoex") ||
    metricId.includes("exposure") ||
    metricId.includes("cash")
  ) {
    return formatPercent(value);
  }
  if (metricId === "turnover_ratio") return `${Number(value).toFixed(1)}×`;
  if (metricId === "commission_bps") return `${value} bps`;
  if (metricId === "sharpe_rf0") return Number(value).toFixed(2);
  return String(value);
}

export function ResearchComparePage() {
  const [params] = useSearchParams();
  const [data, setData] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runIds = useMemo(
    () =>
      (params.get("runs") ?? "")
        .split(",")
        .map((x) => Number(x.trim()))
        .filter((n) => Number.isFinite(n) && n > 0),
    [params],
  );

  useEffect(() => {
    if (runIds.length < 2) {
      setError("Для сравнения нужно минимум 2 эксперимента в URL (?runs=1,2).");
      return;
    }
    const controller = new AbortController();
    compareResearchRuns(runIds, controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, [runIds]);

  if (error) return <PageState kind="error">{error}</PageState>;
  if (!data) return <PageState kind="loading" title="Сравнение экспериментов…" />;

  const chartSeries = data.runs.map((run) => ({
    id: run.id,
    name: experimentName(run),
    points: data.nav_series[String(run.id)] ?? [],
  }));

  return (
    <section className="research-compare">
      <PageHeader
        title="Сравнение экспериментов"
        description="Исторический исследовательский результат — не доказательство будущей доходности."
        helpPageId="research_compare"
        actions={
          <Link to="/research" className="secondary button-link">
            ← Лаборатория
          </Link>
        }
      />

      <div
        className={`badge ${data.fair_comparison ? "badge-success" : "badge-warning"}`}
        data-testid="fair-badge"
      >
        {data.fair_badge} <MetricHelp metricId="fair_comparison" />
      </div>

      {!data.period_aligned ? (
        <p className="warning-inline">
          Периоды различаются — кривые стартуют с разных дат (нормализация к 100 у каждой серии).
        </p>
      ) : null}

      {data.differences.length ? (
        <div className="card">
          <h3>Что различается</h3>
          <ul>
            {data.differences.map((d) => (
              <li key={d.field}>
                <strong>{d.human}</strong>:{" "}
                {Object.entries(d.values)
                  .map(([id, v]) => `#${id}=${String(v)}`)
                  .join(", ")}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="muted">
          {data.model_comparison
            ? "Условия сопоставимы: период, политика, риск, издержки, капитал и исполнение совпадают; сравниваются разные модели."
            : "Условия сопоставимы: период, политика, риск, издержки, капитал и исполнение совпадают."}
        </p>
      )}

      {data.observed_holdout_warning ? (
        <div className="info-panel" data-testid="holdout-warning">
          <strong>Уже наблюдавшийся HOLDOUT.</strong> {data.observed_holdout_warning}{" "}
          <MetricHelp metricId="observed_holdout" />
        </div>
      ) : null}

      <div className="card">
        <h3>Метрики</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Метрика</th>
                {data.runs.map((r) => (
                  <th key={r.id}>
                    <Link to={`/research/${r.id}`}>{experimentName(r)}</Link>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.metrics_table.map((row) => (
                <tr key={row.metric_id}>
                  <td>
                    {row.human_label} <MetricHelp metricId={row.help_id} />
                  </td>
                  {data.runs.map((r) => (
                    <td key={r.id} className="numeric">
                      {formatMetric(row.metric_id, row.values[String(r.id)] ?? (row.values as Record<number, number | null>)[r.id])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <MultiLineChart series={chartSeries} valueKey="nav_normalized" title="NAV (нормализовано к 100)" />
      <MultiLineChart series={chartSeries} valueKey="drawdown" title="Просадка" />

      <div className="card">
        <h3>
          Семейство издержек <MetricHelp metricId="comparison_family" />
        </h3>
        <p>{data.cost_family.message}</p>
        {data.cost_family.present && data.cost_family.matrix?.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Стратегия / Risk</th>
                  <th>0 bps</th>
                  <th>5 bps</th>
                  <th>10 bps</th>
                  <th>20 bps</th>
                </tr>
              </thead>
              <tbody>
                {data.cost_family.matrix.map((row, idx) => (
                  <tr key={idx}>
                    <td>
                      {policyHumanName(row.policy_name)} · {riskHumanName(row.risk_name)}
                    </td>
                    {[0, 5, 10, 20].map((bps) => {
                      const cell = row.cells[String(bps)];
                      return (
                        <td key={bps} className="numeric">
                          {cell ? formatPercent(cell.total_price_return) : "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      <div className="card">
        <h3>Наблюдения (детерминированные)</h3>
        <ul>
          {data.interpretation.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}
