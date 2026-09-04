import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type TouchEvent } from "react";
import type { NavPoint } from "../../api/simulator";
import { formatDate, formatPercent } from "../../utils/format";

interface Props {
  items: NavPoint[];
  dateFrom: string;
  dateTo: string;
  peakDate?: string | null;
  troughDate?: string | null;
  recoveryDate?: string | null;
  selectedDate?: string | null;
  onSelectDate?: (date: string) => void;
  height?: number;
}

/** Drawdown series from nav.drawdown (SVG). */
export function DrawdownChart({
  items,
  dateFrom,
  dateTo,
  peakDate,
  troughDate,
  recoveryDate,
  selectedDate,
  onSelectDate,
  height = 160,
}: Props) {
  const ref = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(720);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const series = useMemo(
    () => items.filter((p) => p.date >= dateFrom && p.date <= dateTo),
    [items, dateFrom, dateTo],
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

  const pad = { top: 12, right: 12, bottom: 24, left: 56 };
  const innerW = Math.max(40, width - pad.left - pad.right);
  const innerH = Math.max(40, height - pad.top - pad.bottom);

  const values = series.map((p) => p.drawdown);
  const min = values.length ? Math.min(...values, 0) : -0.01;
  const max = 0;
  const span = max - min || 0.01;

  const xAt = useCallback(
    (index: number) => pad.left + (series.length <= 1 ? 0 : (index / (series.length - 1)) * innerW),
    [series.length, innerW, pad.left],
  );
  const yAt = useCallback(
    (value: number) => pad.top + (1 - (value - min) / span) * innerH,
    [innerH, min, pad.top, span],
  );

  const areaPoints = useMemo(() => {
    if (!series.length) return "";
    const top = series.map((p, i) => `${xAt(i)},${yAt(p.drawdown)}`).join(" ");
    const lastX = xAt(series.length - 1);
    const firstX = xAt(0);
    return `${firstX},${yAt(0)} ${top} ${lastX},${yAt(0)}`;
  }, [series, xAt, yAt]);

  const linePoints = series.map((p, i) => `${xAt(i)},${yAt(p.drawdown)}`).join(" ");

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

  if (series.length < 2) {
    return <p className="muted">Недостаточно точек для просадки</p>;
  }

  function mark(date: string | null | undefined, label: string, className: string) {
    if (!date) return null;
    const idx = series.findIndex((p) => p.date === date);
    if (idx < 0) return null;
    return (
      <g key={label}>
        <line
          x1={xAt(idx)}
          x2={xAt(idx)}
          y1={pad.top}
          y2={height - pad.bottom}
          className={className}
        />
        <text x={xAt(idx)} y={pad.top + 10} className="chart-axis" textAnchor="middle">
          {label}
        </text>
      </g>
    );
  }

  return (
    <div className="sim-chart">
      <svg
        ref={ref}
        className="sim-chart-svg sim-drawdown-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="График просадки портфеля"
        onMouseMove={onMove}
        onMouseLeave={() => setHoverIndex(null)}
        onClick={(e) => {
          const index = indexFromClientX(e.clientX);
          if (index != null && series[index] && onSelectDate) onSelectDate(series[index].date);
        }}
        onTouchStart={onMove}
        onTouchMove={onMove}
      >
        <polygon className="sim-dd-area" points={areaPoints} />
        <polyline className="chart-line chart-line-dd" fill="none" points={linePoints} />
        <line x1={pad.left} x2={width - pad.right} y1={yAt(0)} y2={yAt(0)} className="chart-grid" />
        <text x={4} y={yAt(min) + 4} className="chart-axis">
          {formatPercent(min)}
        </text>
        {mark(peakDate, "пик", "sim-dd-mark peak")}
        {mark(troughDate, "дно", "sim-dd-mark trough")}
        {mark(recoveryDate, "восст.", "sim-dd-mark recovery")}
        {activeIndex != null ? (
          <line
            x1={xAt(activeIndex)}
            x2={xAt(activeIndex)}
            y1={pad.top}
            y2={height - pad.bottom}
            className="chart-crosshair"
          />
        ) : null}
        <text x={pad.left} y={height - 6} className="chart-axis">
          {formatDate(series[0].date)}
        </text>
        <text x={width - pad.right} y={height - 6} className="chart-axis" textAnchor="end">
          {formatDate(series[series.length - 1].date)}
        </text>
      </svg>
      {tip ? (
        <div className="ohlc-tooltip" style={{ left: 12 }}>
          <strong>{formatDate(tip.date)}</strong>
          <div>Просадка {formatPercent(tip.drawdown)}</div>
        </div>
      ) : null}
    </div>
  );
}
