import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type TouchEvent } from "react";
import type { BenchmarkPoint, NavPoint } from "../../api/simulator";
import { formatDate, formatMoney } from "../../utils/format";

export interface EquitySeriesPoint {
  date: string;
  nav: number;
  benchNav: number | null;
  isRebalance: boolean;
}

interface Props {
  items: NavPoint[];
  benchmarkSeries: BenchmarkPoint[];
  rebalanceDates?: string[];
  dateFrom: string;
  dateTo: string;
  selectedDate?: string | null;
  onSelectDate?: (date: string) => void;
  height?: number;
}

function buildAlignedSeries(
  items: NavPoint[],
  benchmarkSeries: BenchmarkPoint[],
  rebalanceDates: string[],
  dateFrom: string,
  dateTo: string,
): EquitySeriesPoint[] {
  const filtered = items.filter((p) => p.date >= dateFrom && p.date <= dateTo);
  if (!filtered.length) return [];

  const benchByDate = new Map(benchmarkSeries.map((b) => [b.date, b.close]));
  const firstNav = filtered[0].nav;
  const firstBenchClose =
    filtered.map((p) => benchByDate.get(p.date)).find((c) => c != null && c > 0) ?? null;
  const reb = new Set(rebalanceDates);

  return filtered.map((p) => {
    const close = benchByDate.get(p.date);
    let benchNav: number | null = null;
    if (firstBenchClose != null && close != null && firstBenchClose > 0) {
      benchNav = firstNav * (close / firstBenchClose);
    }
    return {
      date: p.date,
      nav: p.nav,
      benchNav,
      isRebalance: reb.has(p.date),
    };
  });
}

/** Dual-line equity: Kraken NAV vs IMOEX normalized to initial NAV (SVG, no chart lib). */
export function NavEquityChart({
  items,
  benchmarkSeries,
  rebalanceDates = [],
  dateFrom,
  dateTo,
  selectedDate,
  onSelectDate,
  height = 300,
}: Props) {
  const ref = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(720);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const series = useMemo(
    () => buildAlignedSeries(items, benchmarkSeries, rebalanceDates, dateFrom, dateTo),
    [items, benchmarkSeries, rebalanceDates, dateFrom, dateTo],
  );

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 40) setWidth(Math.floor(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const pad = { top: 16, right: 12, bottom: 28, left: 64 };
  const innerW = Math.max(40, width - pad.left - pad.right);
  const innerH = Math.max(40, height - pad.top - pad.bottom);

  const values = series.flatMap((p) => [p.nav, ...(p.benchNav != null ? [p.benchNav] : [])]);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 1;
  const span = max - min || 1;

  const xAt = useCallback(
    (index: number) => pad.left + (series.length <= 1 ? 0 : (index / (series.length - 1)) * innerW),
    [series.length, innerW, pad.left],
  );
  const yAt = useCallback(
    (value: number) => pad.top + (1 - (value - min) / span) * innerH,
    [innerH, min, pad.top, span],
  );

  const navPoints = series.map((p, i) => `${xAt(i)},${yAt(p.nav)}`).join(" ");
  const benchPoints = series
    .map((p, i) => (p.benchNav == null ? null : `${xAt(i)},${yAt(p.benchNav)}`))
    .filter(Boolean)
    .join(" ");

  const selectedIndex = selectedDate ? series.findIndex((p) => p.date === selectedDate) : -1;
  const activeIndex = hoverIndex ?? (selectedIndex >= 0 ? selectedIndex : null);
  const tip = activeIndex != null ? series[activeIndex] : null;

  function indexFromClientX(clientX: number) {
    if (!series.length || !ref.current) return null;
    const rect = ref.current.getBoundingClientRect();
    const x = clientX - rect.left;
    const rel = (x - pad.left) / innerW;
    return Math.min(series.length - 1, Math.max(0, Math.round(rel * (series.length - 1))));
  }

  function onMove(event: MouseEvent<SVGSVGElement> | TouchEvent<SVGSVGElement>) {
    const clientX = "touches" in event ? event.touches[0]?.clientX : event.clientX;
    if (clientX == null) return;
    const index = indexFromClientX(clientX);
    if (index != null) setHoverIndex(index);
  }

  function onClick(event: MouseEvent<SVGSVGElement>) {
    const index = indexFromClientX(event.clientX);
    if (index != null && series[index] && onSelectDate) onSelectDate(series[index].date);
  }

  if (series.length < 2) {
    return <p className="muted">Недостаточно точек для графика NAV</p>;
  }

  return (
    <div className="sim-chart">
      <div className="sim-chart-legend">
        <span className="sim-legend-item sim-legend-nav">Kraken NAV</span>
        <span className="sim-legend-item sim-legend-bench">IMOEX (норм. к начальному NAV)</span>
      </div>
      <svg
        ref={ref}
        className="sim-chart-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="График NAV симуляции и IMOEX"
        onMouseMove={onMove}
        onMouseLeave={() => setHoverIndex(null)}
        onClick={onClick}
        onTouchStart={onMove}
        onTouchMove={onMove}
      >
        <line x1={pad.left} x2={width - pad.right} y1={yAt(min)} y2={yAt(min)} className="chart-grid" />
        <line x1={pad.left} x2={width - pad.right} y1={yAt(max)} y2={yAt(max)} className="chart-grid" />
        <text x={4} y={yAt(max) + 4} className="chart-axis">
          {formatMoney(max)}
        </text>
        <text x={4} y={yAt(min) + 4} className="chart-axis">
          {formatMoney(min)}
        </text>
        {benchPoints ? <polyline className="chart-line chart-line-bench" fill="none" points={benchPoints} /> : null}
        <polyline className="chart-line chart-line-nav" fill="none" points={navPoints} />
        {series.map((p, i) =>
          p.isRebalance ? (
            <circle key={`reb-${p.date}`} cx={xAt(i)} cy={yAt(p.nav)} r={2.5} className="sim-rebalance-dot" />
          ) : null,
        )}
        {activeIndex != null ? (
          <>
            <line
              x1={xAt(activeIndex)}
              x2={xAt(activeIndex)}
              y1={pad.top}
              y2={height - pad.bottom}
              className="chart-crosshair"
            />
            <circle cx={xAt(activeIndex)} cy={yAt(series[activeIndex].nav)} r={4} className="chart-dot" />
          </>
        ) : null}
        <text x={pad.left} y={height - 8} className="chart-axis">
          {formatDate(series[0].date)}
        </text>
        <text x={width - pad.right} y={height - 8} className="chart-axis" textAnchor="end">
          {formatDate(series[series.length - 1].date)}
        </text>
      </svg>
      {tip ? (
        <div
          className="ohlc-tooltip"
          style={{
            left: Math.min(Math.max(8, (activeIndex != null ? xAt(activeIndex) : 0) - 70), Math.max(8, width - 180)),
          }}
        >
          <strong>{formatDate(tip.date)}</strong>
          <div>NAV {formatMoney(tip.nav)}</div>
          <div>IMOEX {tip.benchNav != null ? formatMoney(tip.benchNav) : "—"}</div>
          {tip.isRebalance ? <div className="muted">Ребаланс</div> : null}
          <div className="muted">Клик — инспектор даты</div>
        </div>
      ) : null}
    </div>
  );
}
