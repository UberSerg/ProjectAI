import { useId, useMemo, useState } from "react";
import type { GraphModel } from "./portfolioRelationsInsight";
import { layoutNodes } from "./portfolioRelationsInsight";

type Props = {
  model: GraphModel;
  cluster: string[];
};

function edgeStyle(strength: string): {
  stroke: string;
  width: number;
  opacity: number;
  dash?: string;
} {
  switch (strength) {
    case "strong":
      return { stroke: "rgba(176, 74, 46, 0.92)", width: 3.2, opacity: 1 };
    case "moderate":
      return { stroke: "rgba(176, 74, 46, 0.55)", width: 2, opacity: 0.85 };
    case "negative":
      // Sign is not color-only: dashed stroke + numeric label keeps minus sign.
      return { stroke: "rgba(58, 90, 128, 0.85)", width: 2.4, opacity: 0.9, dash: "6 4" };
    default:
      return { stroke: "rgba(92, 107, 122, 0.35)", width: 1, opacity: 0.45 };
  }
}

export function PortfolioRelationsGraph({ model, cluster }: Props) {
  const uid = useId();
  const [focus, setFocus] = useState<string | null>(null);
  const width = 520;
  const height = 320;

  const positions = useMemo(
    () => layoutNodes(model.nodes, cluster, width, height),
    [model.nodes, cluster],
  );

  if (model.nodes.length === 0) {
    return (
      <p className="muted" data-testid="portfolio-relations-graph-empty">
        Нет инструментов с данными для схемы связей.
      </p>
    );
  }

  if (model.nodes.length === 1) {
    const only = model.nodes[0];
    const p = positions.get(only)!;
    return (
      <div className="portfolio-rel-graph-wrap" data-testid="portfolio-relations-graph">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Схема связей портфеля">
          <circle cx={p.x} cy={p.y} r={22} className="portfolio-rel-node" />
          <text x={p.x} y={p.y + 4} textAnchor="middle" className="portfolio-rel-node-label">
            {only}
          </text>
        </svg>
        <p className="muted" style={{ marginBottom: 0 }}>
          Для схемы связей нужна хотя бы одна пара с рассчитанной корреляцией.
        </p>
      </div>
    );
  }

  // Draw weak edges first, strong last (on top)
  const orderedEdges = [...model.edges].sort((a, b) => {
    const rank = { weak: 0, moderate: 1, negative: 2, strong: 3 } as const;
    return rank[a.strength] - rank[b.strength];
  });

  return (
    <div className="portfolio-rel-graph-wrap" data-testid="portfolio-relations-graph">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Схема связей: толщина линии — сила корреляции доходностей"
        className="portfolio-rel-graph"
      >
        <title>Схема исторических связей доходностей</title>
        {orderedEdges.map((e) => {
          const a = positions.get(e.symbol_a);
          const b = positions.get(e.symbol_b);
          if (!a || !b) return null;
          const st = edgeStyle(e.strength);
          const midX = (a.x + b.x) / 2;
          const midY = (a.y + b.y) / 2;
          const edgeId = `${e.symbol_a}-${e.symbol_b}`;
          const dimmed =
            focus != null && focus !== e.symbol_a && focus !== e.symbol_b;
          return (
            <g
              key={edgeId}
              opacity={dimmed ? 0.18 : st.opacity}
              onMouseEnter={() => setFocus(`${e.symbol_a}|${e.symbol_b}`)}
              onMouseLeave={() => setFocus(null)}
            >
              <line
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={st.stroke}
                strokeWidth={st.width}
                strokeLinecap="round"
                strokeDasharray={st.dash}
              />
              {e.showLabel ? (
                <text
                  x={midX}
                  y={midY - 6}
                  textAnchor="middle"
                  className="portfolio-rel-edge-label"
                >
                  {e.pearson.toFixed(2)}
                </text>
              ) : null}
              <title>{`${e.symbol_a} × ${e.symbol_b}: ${e.pearson.toFixed(2)}`}</title>
            </g>
          );
        })}
        {model.nodes.map((sym) => {
          const p = positions.get(sym)!;
          const inCluster = cluster.includes(sym);
          const nodeFocus =
            focus != null &&
            (focus === sym || focus.includes(sym));
          return (
            <g
              key={sym}
              onMouseEnter={() => setFocus(sym)}
              onMouseLeave={() => setFocus(null)}
              onFocus={() => setFocus(sym)}
              onBlur={() => setFocus(null)}
              tabIndex={0}
              role="listitem"
              aria-label={`Позиция ${sym}${inCluster ? ", в тесной группе" : ""}`}
            >
              <circle
                cx={p.x}
                cy={p.y}
                r={inCluster ? 24 : 20}
                className={
                  inCluster ? "portfolio-rel-node portfolio-rel-node-cluster" : "portfolio-rel-node"
                }
                opacity={focus != null && !nodeFocus && !focus.includes(sym) ? 0.35 : 1}
              />
              <text
                x={p.x}
                y={p.y + 4}
                textAnchor="middle"
                className="portfolio-rel-node-label"
              >
                {sym.length > 10 ? `${sym.slice(0, 9)}…` : sym}
              </text>
              <title>{sym}</title>
            </g>
          );
        })}
      </svg>

      <div className="portfolio-rel-legend" aria-hidden="true">
        <span>
          <i className="portfolio-rel-swatch strong" /> сильная + (≥0.70), сплошная
        </span>
        <span>
          <i className="portfolio-rel-swatch moderate" /> умеренная, сплошная
        </span>
        <span>
          <i className="portfolio-rel-swatch weak" /> слабая (приглушена)
        </span>
        <span>
          <i className="portfolio-rel-swatch negative dashed" /> отрицательная, пунктир
        </span>
      </div>
      <p className="muted portfolio-rel-graph-note">
        Нет линии ≠ корреляция 0: линия рисуется только если пара рассчитана. Слабые связи
        приглушены, чтобы схема оставалась читаемой. Знак связи: сплошная = неотрицательная /
        положительная зона, пунктир = отрицательная (подпись сохраняет знак, напр. −0.55).
        <span className="sr-only"> Идентификатор схемы {uid}</span>
      </p>
    </div>
  );
}
