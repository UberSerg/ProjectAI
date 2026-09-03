import { useCallback, useEffect, useRef, useState, type MouseEvent, type TouchEvent } from "react";
import type { Candle } from "../../api/market";
import { formatDate, formatNumber, formatPrice } from "../../utils/format";

interface Props {
  candles: Candle[];
  height?: number;
}

interface HoverState {
  index: number;
  x: number;
  y: number;
}

/** Dominant close chart with OHLC hover tooltip (SVG, no external chart lib). */
export function PriceChart({ candles, height = 320 }: Props) {
  const ref = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(720);
  const [hover, setHover] = useState<HoverState | null>(null);

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

  const pad = { top: 16, right: 12, bottom: 28, left: 56 };
  const innerW = Math.max(40, width - pad.left - pad.right);
  const innerH = Math.max(40, height - pad.top - pad.bottom);

  const closes = candles.map((c) => c.close);
  const min = closes.length ? Math.min(...closes) : 0;
  const max = closes.length ? Math.max(...closes) : 1;
  const span = max - min || 1;

  const xAt = useCallback(
    (index: number) => pad.left + (candles.length <= 1 ? 0 : (index / (candles.length - 1)) * innerW),
    [candles.length, innerW, pad.left],
  );
  const yAt = useCallback(
    (value: number) => pad.top + (1 - (value - min) / span) * innerH,
    [innerH, min, pad.top, span],
  );

  const points = candles
    .map((candle, index) => `${xAt(index)},${yAt(candle.close)}`)
    .join(" ");

  function onMove(event: MouseEvent<SVGSVGElement> | TouchEvent<SVGSVGElement>) {
    if (!candles.length || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const clientX = "touches" in event ? event.touches[0]?.clientX : event.clientX;
    if (clientX == null) return;
    const x = clientX - rect.left;
    const rel = (x - pad.left) / innerW;
    const index = Math.min(candles.length - 1, Math.max(0, Math.round(rel * (candles.length - 1))));
    setHover({ index, x: xAt(index), y: yAt(candles[index].close) });
  }

  if (candles.length < 2) {
    return <p className="muted">Недостаточно точек для графика</p>;
  }

  const tip = hover ? candles[hover.index] : null;

  return (
    <div className="price-chart">
      <svg
        ref={ref}
        className="price-chart-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="График цены закрытия RAW"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        onTouchStart={onMove}
        onTouchMove={onMove}
      >
        <line x1={pad.left} x2={width - pad.right} y1={yAt(min)} y2={yAt(min)} className="chart-grid" />
        <line x1={pad.left} x2={width - pad.right} y1={yAt(max)} y2={yAt(max)} className="chart-grid" />
        <text x={4} y={yAt(max) + 4} className="chart-axis">
          {formatPrice(max)}
        </text>
        <text x={4} y={yAt(min) + 4} className="chart-axis">
          {formatPrice(min)}
        </text>
        <polyline className="chart-line" fill="none" points={points} />
        {hover ? (
          <>
            <line x1={hover.x} x2={hover.x} y1={pad.top} y2={height - pad.bottom} className="chart-crosshair" />
            <circle cx={hover.x} cy={hover.y} r={4} className="chart-dot" />
          </>
        ) : null}
        <text x={pad.left} y={height - 8} className="chart-axis">
          {formatDate(candles[0].timestamp)}
        </text>
        <text x={width - pad.right} y={height - 8} className="chart-axis" textAnchor="end">
          {formatDate(candles[candles.length - 1].timestamp)}
        </text>
      </svg>
      {tip ? (
        <div
          className="ohlc-tooltip"
          style={{
            left: Math.min(Math.max(8, (hover?.x ?? 0) - 70), Math.max(8, width - 160)),
          }}
        >
          <strong>{formatDate(tip.timestamp)}</strong>
          <div>O {formatPrice(tip.open)}</div>
          <div>H {formatPrice(tip.high)}</div>
          <div>L {formatPrice(tip.low)}</div>
          <div>C {formatPrice(tip.close)}</div>
          <div>V {formatNumber(tip.volume)}</div>
          <div className="muted">RAW</div>
        </div>
      ) : null}
    </div>
  );
}
