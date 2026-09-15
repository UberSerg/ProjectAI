import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { errorMessage } from "../../api/client";
import {
  getPortfolioRelationsMatrix,
  type PortfolioRelationCell,
  type PortfolioRelationsMatrix,
} from "../../api/relations";
import { EmptyState } from "../../components/Ui";
import { MetricHelp } from "../../help";
import { PortfolioRelationsGraph } from "./PortfolioRelationsGraph";
import {
  buildGraphModel,
  buildRelationsInsight,
  type RelationsInsight,
} from "./portfolioRelationsInsight";

function fmtCorr(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "N/A";
  return v.toFixed(2);
}

function cellStyle(pearson: number | null): CSSProperties {
  if (pearson == null) {
    return {
      background: "repeating-linear-gradient(135deg, #ececec 0 6px, #f5f5f5 6px 12px)",
      color: "#7a7a7a",
    };
  }
  const t = Math.max(-1, Math.min(1, pearson));
  if (t >= 0) {
    const a = 0.12 + t * 0.55;
    return { background: `rgba(176, 74, 46, ${a})`, color: t > 0.55 ? "#fff" : "#2a2a2a" };
  }
  const a = 0.12 + Math.abs(t) * 0.5;
  return { background: `rgba(58, 90, 128, ${a})`, color: Math.abs(t) > 0.55 ? "#fff" : "#2a2a2a" };
}

function cellKey(a: string, b: string): string {
  return a <= b ? `${a}|${b}` : `${b}|${a}`;
}

function buildLookup(cells: PortfolioRelationCell[]): Map<string, PortfolioRelationCell> {
  const map = new Map<string, PortfolioRelationCell>();
  for (const c of cells) {
    map.set(cellKey(c.symbol_a, c.symbol_b), c);
  }
  return map;
}

function readableAvailability(status: string | undefined): string {
  switch (status) {
    case "OK":
      return "есть данные";
    case "UNSUPPORTED_PAIR":
    case "INPUT_MISSING":
      return "нет данных";
    case "SNAPSHOT_MISSING":
      return "снимок ещё не рассчитан";
    case "INSUFFICIENT_DATA":
      return "недостаточно наблюдений";
    default:
      return status ? "недоступно" : "нет данных";
  }
}

function tooltipText(cell: PortfolioRelationCell | undefined, metricLabel: string): string {
  if (!cell) return "Нет данных";
  const lines = [
    `${cell.symbol_a} × ${cell.symbol_b}`,
    `${metricLabel}: ${fmtCorr(cell.pearson)}`,
  ];
  if (cell.sample_count != null) lines.push(`Наблюдений: ${cell.sample_count}`);
  if (cell.as_of_date) lines.push(`As-of: ${cell.as_of_date}`);
  lines.push(`Доступность: ${readableAvailability(cell.status)}`);
  if (cell.reason_ru && cell.pearson == null) lines.push(cell.reason_ru);
  return lines.join("\n");
}

function InsightCard({ insight }: { insight: RelationsInsight }) {
  return (
    <article className="card portfolio-rel-insight" data-testid="portfolio-relations-insight">
      <h3 style={{ marginTop: 0 }}>{insight.title_ru}</h3>
      <p style={{ marginBottom: insight.bullets_ru.length ? "0.65rem" : 0 }}>{insight.body_ru}</p>
      {insight.bullets_ru.length ? (
        <ul className="plain-list" style={{ marginBottom: 0 }}>
          {insight.bullets_ru.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      ) : null}
      {insight.pair_availability_ru ? (
        <p className="muted" style={{ marginTop: "0.75rem", marginBottom: 0, fontSize: "0.88rem" }}>
          {insight.pair_availability_ru}
        </p>
      ) : null}
    </article>
  );
}

function TriangularHeatmap({
  symbols,
  lookup,
  metricLabel,
  windowLabel,
}: {
  symbols: string[];
  lookup: Map<string, PortfolioRelationCell>;
  metricLabel: string;
  windowLabel: string;
}) {
  const [hover, setHover] = useState<PortfolioRelationCell | null>(null);
  // Columns = symbols[1..]; rows = symbols[0..n-2] — upper triangle only
  const cols = symbols.slice(1);

  return (
    <div className="portfolio-corr-wrap">
      <p className="muted" style={{ marginTop: 0 }}>
        Верхний треугольник: каждая пара один раз. Около 0 — слабая линейная связь; высокий
        положительный — чаще в одном направлении; отрицательный — чаще в разные стороны. Не
        причинная зависимость. {windowLabel}.
      </p>
      <div className="portfolio-rel-heat-legend" aria-hidden="true">
        <span>
          <i className="portfolio-rel-swatch strong" /> сильная +
        </span>
        <span>
          <i className="portfolio-rel-swatch moderate" /> умеренная
        </span>
        <span>
          <i className="portfolio-rel-swatch weak" /> слабая / около 0
        </span>
        <span>
          <i className="portfolio-rel-swatch negative" /> отрицательная
        </span>
        <span>
          <i className="portfolio-rel-swatch na" /> N/A — нет данных (≠ 0)
        </span>
      </div>
      <div className="table-wrap portfolio-corr-scroll">
        <table className="portfolio-corr-heatmap" aria-label="Матрица корреляции доходностей">
          <thead>
            <tr>
              <th scope="col" />
              {cols.map((s) => (
                <th key={s} scope="col" title={s}>
                  {s.length > 12 ? `${s.slice(0, 11)}…` : s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {symbols.slice(0, -1).map((row, rowIdx) => (
              <tr key={row}>
                <th scope="row" title={row}>
                  {row.length > 12 ? `${row.slice(0, 11)}…` : row}
                </th>
                {cols.map((col, colIdx) => {
                  // Only cells where col is "after" row in symbols order
                  if (colIdx < rowIdx) {
                    return <td key={`${row}-${col}`} className="portfolio-corr-empty" />;
                  }
                  const cell = lookup.get(cellKey(row, col));
                  const pearson = cell?.pearson ?? null;
                  return (
                    <td
                      key={`${row}-${col}`}
                      style={cellStyle(pearson)}
                      title={tooltipText(cell, metricLabel)}
                      tabIndex={0}
                      onMouseEnter={() => cell && setHover(cell)}
                      onMouseLeave={() => setHover(null)}
                      onFocus={() => cell && setHover(cell)}
                      onBlur={() => setHover(null)}
                      data-status={cell?.status ?? "SNAPSHOT_MISSING"}
                    >
                      {fmtCorr(pearson)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hover ? (
        <p className="muted portfolio-corr-hover" style={{ marginBottom: 0, whiteSpace: "pre-line" }}>
          {tooltipText(hover, metricLabel)}
        </p>
      ) : (
        <p className="muted" style={{ marginBottom: 0 }}>
          Наведите или сфокусируйте клетку: значение, наблюдения, as-of. N/A ≠ 0.
        </p>
      )}
    </div>
  );
}

export function PortfolioRelationsBlock({ symbols }: { symbols: string[] }) {
  const [data, setData] = useState<PortfolioRelationsMatrix | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const symbolKey = symbols.join(",");

  useEffect(() => {
    if (!symbols.length) {
      setData(null);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    getPortfolioRelationsMatrix({ symbols, window: 60 }, ctrl.signal)
      .then((m) => {
        setData(m);
        setLoading(false);
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setError(errorMessage(err));
        setLoading(false);
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- symbolKey encodes symbols
  }, [symbolKey]);

  const insight = useMemo(() => (data ? buildRelationsInsight(data) : null), [data]);
  const graphModel = useMemo(() => (data ? buildGraphModel(data) : null), [data]);
  const lookup = useMemo(() => buildLookup(data?.cells ?? []), [data]);

  if (!symbols.length) {
    return (
      <section style={{ marginTop: "1.25rem" }} data-testid="portfolio-relations-block">
        <EmptyState
          title="Нет инструментов для связей"
          reason="В Candidate нет позиций (кроме Cash) — оценить связи нельзя."
        />
      </section>
    );
  }

  if (loading) {
    return (
      <section style={{ marginTop: "1.25rem" }} data-testid="portfolio-relations-block">
        <h2>
          Связи внутри портфеля <MetricHelp metricId="portfolio_relations_correlation" />
        </h2>
        <p className="muted">Загружаем связи позиций Candidate…</p>
      </section>
    );
  }

  if (error) {
    return (
      <section style={{ marginTop: "1.25rem" }} data-testid="portfolio-relations-block">
        <h2>
          Связи внутри портфеля <MetricHelp metricId="portfolio_relations_correlation" />
        </h2>
        <EmptyState title="Не удалось загрузить связи" reason={error} />
      </section>
    );
  }

  if (!data || !insight || !graphModel) return null;

  const metricLabel = data.metric.label_ru || "Корреляция доходностей";
  const windowLabel = data.metric.window_label_ru || `окно ${data.metric.window_observations}`;
  const empty = insight.kind === "INSUFFICIENT_DATA" && insight.available_pairs.length === 0;

  return (
    <section style={{ marginTop: "1.25rem" }} data-testid="portfolio-relations-block">
      <h2>
        Связи внутри портфеля <MetricHelp metricId="portfolio_relations_correlation" />
      </h2>
      <p className="muted" style={{ maxWidth: "40rem", marginTop: 0 }}>
        Показывает, какие позиции исторически двигались вместе. Чем сильнее положительная связь,
        тем меньше независимой диверсификации даёт пара.
      </p>

      <InsightCard insight={insight} />

      {!empty ? (
        <div className="card" style={{ marginTop: "1rem" }} data-testid="portfolio-relations-visual">
          <h3 style={{ marginTop: 0 }}>Схема связей</h3>
          <PortfolioRelationsGraph model={graphModel} cluster={insight.cluster} />
        </div>
      ) : (
        <EmptyState
          title="Корреляции недоступны"
          reason={
            data.error?.message_ru ||
            insight.body_ru ||
            "Для текущего Candidate нет рассчитанных pairwise Relations."
          }
        />
      )}

      {insight.unsupported.length ? (
        <aside
          className="card portfolio-rel-missing"
          style={{ marginTop: "1rem" }}
          data-testid="portfolio-relations-missing"
        >
          <h3 style={{ marginTop: 0 }}>
            Нет данных для {insight.unsupported.length} из {data.symbols.length} позиций
          </h3>
          <p className="muted" style={{ marginTop: 0 }}>
            Для этих инструментов корреляция пока не рассчитана. Они не участвуют в выводах выше.
          </p>
          <ul className="portfolio-rel-missing-list">
            {insight.unsupported.map((s) => (
              <li key={s}>
                <code>{s}</code>
              </li>
            ))}
          </ul>
        </aside>
      ) : null}

      <details
        className="card"
        style={{ marginTop: "1rem" }}
        data-testid="portfolio-relations-details"
        open={detailsOpen}
        onToggle={(e) => setDetailsOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary>Подробные связи</summary>
        {detailsOpen ? (
          <div style={{ marginTop: "0.75rem" }}>
            <TriangularHeatmap
              symbols={data.symbols}
              lookup={lookup}
              metricLabel={metricLabel}
              windowLabel={windowLabel}
            />
          </div>
        ) : null}
      </details>
    </section>
  );
}
