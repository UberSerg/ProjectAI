import { useCallback, useEffect, useRef, useState } from "react";
import type { Candle } from "../../api/market";
import { clampRange, type DateBounds, isoFromTimestamp, parseIsoDate } from "./range";

interface Props {
  overview: Candle[];
  available: DateBounds;
  range: DateBounds;
  onChange: (next: DateBounds) => void;
}

function ratioToDate(ratio: number, available: DateBounds): string {
  const from = parseIsoDate(available.from);
  const to = parseIsoDate(available.to);
  if (!from || !to) return available.from;
  const t = from.getTime() + Math.min(1, Math.max(0, ratio)) * (to.getTime() - from.getTime());
  const d = new Date(t);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function dateToRatio(iso: string, available: DateBounds): number {
  const from = parseIsoDate(available.from);
  const to = parseIsoDate(available.to);
  const value = parseIsoDate(iso);
  if (!from || !to || !value) return 0;
  const span = to.getTime() - from.getTime() || 1;
  return Math.min(1, Math.max(0, (value.getTime() - from.getTime()) / span));
}

/** Mini overview with draggable from/to handles (native SVG, no zoom conflict). */
export function RangeNavigator({ overview, available, range, onChange }: Props) {
  const ref = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(720);
  const dragging = useRef<"from" | "to" | "window" | null>(null);
  const dragOrigin = useRef<{ startX: number; fromR: number; toR: number } | null>(null);

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

  const height = 64;
  const padX = 8;
  const padY = 8;
  const innerW = Math.max(20, width - padX * 2);
  const innerH = height - padY * 2;
  const closes = overview.map((c) => c.close);
  const min = closes.length ? Math.min(...closes) : 0;
  const max = closes.length ? Math.max(...closes) : 1;
  const span = max - min || 1;

  const points =
    overview.length < 2
      ? ""
      : overview
          .map((candle, index) => {
            const x = padX + (index / (overview.length - 1)) * innerW;
            const y = padY + (1 - (candle.close - min) / span) * innerH;
            return `${x},${y}`;
          })
          .join(" ");

  const fromR = dateToRatio(range.from, available);
  const toR = dateToRatio(range.to, available);
  const xFrom = padX + fromR * innerW;
  const xTo = padX + toR * innerW;

  const applyClientX = useCallback(
    (clientX: number, mode: "from" | "to" | "window") => {
      if (!ref.current) return;
      const rect = ref.current.getBoundingClientRect();
      const x = clientX - rect.left;
      const ratio = Math.min(1, Math.max(0, (x - padX) / innerW));
      if (mode === "from") {
        const nextFrom = ratioToDate(Math.min(ratio, toR - 0.002), available);
        onChange(clampRange({ from: nextFrom, to: range.to }, available));
      } else if (mode === "to") {
        const nextTo = ratioToDate(Math.max(ratio, fromR + 0.002), available);
        onChange(clampRange({ from: range.from, to: nextTo }, available));
      } else if (dragOrigin.current) {
        const delta = ratio - (dragOrigin.current.startX - padX) / innerW;
        const widthR = dragOrigin.current.toR - dragOrigin.current.fromR;
        let nextFromR = dragOrigin.current.fromR + delta;
        let nextToR = dragOrigin.current.toR + delta;
        if (nextFromR < 0) {
          nextFromR = 0;
          nextToR = widthR;
        }
        if (nextToR > 1) {
          nextToR = 1;
          nextFromR = 1 - widthR;
        }
        onChange(
          clampRange(
            {
              from: ratioToDate(nextFromR, available),
              to: ratioToDate(nextToR, available),
            },
            available,
          ),
        );
      }
    },
    [available, fromR, innerW, onChange, range.from, range.to, toR],
  );

  useEffect(() => {
    function onMove(event: MouseEvent | TouchEvent) {
      if (!dragging.current) return;
      const clientX = "touches" in event ? event.touches[0]?.clientX : event.clientX;
      if (clientX == null) return;
      event.preventDefault();
      applyClientX(clientX, dragging.current);
    }
    function onUp() {
      dragging.current = null;
      dragOrigin.current = null;
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("touchmove", onMove, { passive: false });
    window.addEventListener("touchend", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onUp);
    };
  }, [applyClientX]);

  if (overview.length < 2) {
    return <p className="muted range-nav-caption">Навигатор периода недоступен — мало точек истории.</p>;
  }

  const dimLeftW = Math.max(0, xFrom - padX);
  const dimRightX = xTo;
  const dimRightW = Math.max(0, padX + innerW - xTo);

  return (
    <div className="range-navigator">
      <div className="range-nav-header">
        <span className="range-nav-title">Выбор периода на полной истории</span>
        <span className="range-nav-selected" aria-live="polite">
          Выбрано: {range.from} → {range.to}
        </span>
      </div>
      <svg
        ref={ref}
        className="range-navigator-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Навигатор: перетащите ручки или окно, чтобы выбрать видимый период"
      >
        <rect x={0} y={0} width={width} height={height} className="range-nav-bg" rx={8} />
        <polyline fill="none" className="range-nav-line" points={points} />
        {dimLeftW > 0 ? (
          <rect x={padX} y={padY} width={dimLeftW} height={innerH} className="range-nav-dim" />
        ) : null}
        {dimRightW > 0 ? (
          <rect x={dimRightX} y={padY} width={dimRightW} height={innerH} className="range-nav-dim" />
        ) : null}
        <rect
          x={xFrom}
          y={padY}
          width={Math.max(2, xTo - xFrom)}
          height={innerH}
          className="range-nav-window"
          onMouseDown={(event) => {
            dragging.current = "window";
            dragOrigin.current = { startX: event.clientX - (ref.current?.getBoundingClientRect().left ?? 0), fromR, toR };
          }}
          onTouchStart={(event) => {
            const touch = event.touches[0];
            if (!touch || !ref.current) return;
            dragging.current = "window";
            dragOrigin.current = {
              startX: touch.clientX - ref.current.getBoundingClientRect().left,
              fromR,
              toR,
            };
          }}
        />
        <Handle x={xFrom} height={height} onStart={() => { dragging.current = "from"; }} />
        <Handle x={xTo} height={height} onStart={() => { dragging.current = "to"; }} />
      </svg>
      <p className="muted range-nav-caption">
        Полная история: {isoFromTimestamp(overview[0]?.timestamp) ?? available.from} →{" "}
        {isoFromTimestamp(overview[overview.length - 1]?.timestamp) ?? available.to}. Тяните ручки или синее
        окно.
      </p>
    </div>
  );
}

function Handle({ x, height, onStart }: { x: number; height: number; onStart: () => void }) {
  return (
    <g
      className="range-nav-handle"
      onMouseDown={(event) => {
        event.stopPropagation();
        onStart();
      }}
      onTouchStart={(event) => {
        event.stopPropagation();
        onStart();
      }}
      style={{ cursor: "ew-resize" }}
    >
      <line x1={x} x2={x} y1={4} y2={height - 4} />
      <rect x={x - 6} y={height / 2 - 14} width={12} height={28} rx={4} />
    </g>
  );
}
