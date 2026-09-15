import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { errorMessage } from "../../api/client";
import {
  getPortfolioRelationsMatrix,
  type PortfolioRelationCell,
  type PortfolioRelationsMatrix,
} from "../../api/relations";
import { EmptyState, ExplanationCard, MetricCard } from "../../components/Ui";
import { MetricHelp } from "../../help";

function fmtCorr(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "N/A";
  return v.toFixed(2);
}

/** Diverging muted scale: negative = cool slate-blue, positive = warm terracotta. */
function cellStyle(pearson: number | null, status: string): CSSProperties {
  if (status === "DIAGONAL") {
    return { background: "var(--ds-surface-muted, #e8e6e1)", color: "var(--ds-text-muted, #6b6b6b)" };
  }
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

function tooltipText(cell: PortfolioRelationCell | undefined, metricLabel: string): string {
  if (!cell) return "Нет данных";
  if (cell.status === "DIAGONAL") return `${cell.symbol_a}: диагональ = 1.00`;
  const lines = [
    `${cell.symbol_a} × ${cell.symbol_b}`,
    `${metricLabel}: ${fmtCorr(cell.pearson)}`,
  ];
  if (cell.sample_count != null) lines.push(`Наблюдений: ${cell.sample_count}`);
  if (cell.as_of_date) lines.push(`As-of: ${cell.as_of_date}`);
  lines.push(`Статус: ${cell.status}`);
  if (cell.reason_ru) lines.push(cell.reason_ru);
  return lines.join("\n");
}

export function PortfolioRelationsBlock({ symbols }: { symbols: string[] }) {
  const [data, setData] = useState<PortfolioRelationsMatrix | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<PortfolioRelationCell | null>(null);

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

  const lookup = useMemo(() => buildLookup(data?.cells ?? []), [data]);

  if (!symbols.length) {
    return (
      <section style={{ marginTop: "1.25rem" }} data-testid="portfolio-relations-block">
        <EmptyState
          title="Нет инструментов для связей"
          reason="В Candidate нет позиций (кроме Cash) — матрица корреляций пуста."
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
        <p className="muted">Загружаем корреляции доходностей для позиций Candidate…</p>
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

  if (!data) return null;

  const metricLabel = data.metric.label_ru || "Корреляция доходностей";
  const windowLabel = data.metric.window_label_ru || `окно ${data.metric.window_observations}`;
  const unsupported = data.instruments.filter((i) => i.status !== "READY");
  const empty =
    data.summary.available_pair_count === 0 &&
    (data.summary.status === "EMPTY" || data.summary.status === "NO_SYMBOLS");

  return (
    <section style={{ marginTop: "1.25rem" }} data-testid="portfolio-relations-block">
      <h2>
        Связи внутри портфеля <MetricHelp metricId="portfolio_relations_correlation" />
      </h2>
      <p className="muted" style={{ maxWidth: "52rem" }}>
        {data.metric.note_ru ||
          "Чем ближе корреляция к +1, тем чаще активы двигались в одном направлении. Около 0 — слабая историческая связь. Отрицательная — чаще в разные стороны. Историческая корреляция может меняться и не гарантирует будущего поведения."}
      </p>
      <p className="muted" style={{ marginTop: "0.35rem" }}>
        {metricLabel}
        {data.metric.return_label_ru ? ` · ${data.metric.return_label_ru}` : ""} · {windowLabel}
        {data.as_of_date ? ` · as-of ${data.as_of_date}` : ""}
        {data.relation_set
          ? ` · ${data.relation_set.code} v${data.relation_set.version}`
          : ""}
      </p>

      <div className="card-grid" style={{ marginBottom: "1rem" }}>
        <MetricCard
          label="Пар с корреляцией"
          value={`${data.summary.available_pair_count} / ${data.summary.pair_count}`}
          helpId="portfolio_relations_correlation"
        />
        <MetricCard
          label="Сильнейшая +"
          value={
            data.summary.strongest_positive
              ? `${data.summary.strongest_positive.symbol_a}×${data.summary.strongest_positive.symbol_b} ${fmtCorr(data.summary.strongest_positive.pearson)}`
              : "—"
          }
        />
        <MetricCard
          label="Наиболее низкая"
          value={
            data.summary.lowest
              ? `${data.summary.lowest.symbol_a}×${data.summary.lowest.symbol_b} ${fmtCorr(data.summary.lowest.pearson)}`
              : "—"
          }
        />
        <MetricCard
          label="Средняя |corr|"
          value={
            data.summary.average_abs_correlation != null
              ? fmtCorr(data.summary.average_abs_correlation)
              : "—"
          }
        />
      </div>

      <h3 style={{ marginTop: 0 }}>Что это значит</h3>
      <div className="card-grid" style={{ marginBottom: "1rem" }}>
        <ExplanationCard title="Интерпретация" level={1}>
          {data.summary.status_ru ||
            "Нет доступных pairwise корреляций для текущего состава."}
          {data.summary.high_positive_pair_count != null && data.summary.available_pair_count > 0
            ? ` Пар с высокой положительной корреляцией (≥0.70): ${data.summary.high_positive_pair_count}.`
            : ""}
        </ExplanationCard>
        {unsupported.length ? (
          <ExplanationCard title="Ограничения данных" level={2}>
            Для части инструментов история/метрика недоступна (
            {unsupported.map((u) => u.symbol).join(", ")}). Клетки показаны как N/A — это не
            нулевая корреляция. Облигации часто отсутствуют в Relations universe.
          </ExplanationCard>
        ) : null}
      </div>

      {empty ? (
        <EmptyState
          title="Корреляции недоступны"
          reason={
            data.error?.message_ru ||
            data.summary.status_ru ||
            "Для текущего Candidate нет persisted pairwise Relations."
          }
        />
      ) : (
        <div className="card portfolio-corr-wrap">
          <div className="table-wrap portfolio-corr-scroll">
            <table className="portfolio-corr-heatmap" aria-label="Матрица корреляции доходностей">
              <thead>
                <tr>
                  <th scope="col" />
                  {data.symbols.map((s) => (
                    <th key={s} scope="col" title={s}>
                      {s}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.symbols.map((row) => (
                  <tr key={row}>
                    <th scope="row">{row}</th>
                    {data.symbols.map((col) => {
                      const cell = lookup.get(cellKey(row, col));
                      const pearson =
                        row === col
                          ? cell?.pearson ?? (cell?.status === "DIAGONAL" ? 1 : null)
                          : cell?.pearson ?? null;
                      const status = cell?.status ?? "SNAPSHOT_MISSING";
                      return (
                        <td
                          key={`${row}-${col}`}
                          style={cellStyle(pearson, status)}
                          title={tooltipText(cell, metricLabel)}
                          onMouseEnter={() => cell && setHover(cell)}
                          onMouseLeave={() => setHover(null)}
                          data-status={status}
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
              Наведите на клетку: значение, наблюдения, as-of и статус. N/A ≠ 0.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
