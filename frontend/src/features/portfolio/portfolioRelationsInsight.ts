/**
 * Deterministic presentation insight for Portfolio Relations UX V2.
 * UX-only thresholds — not Candidate Policy / Risk Gate rules.
 */

import type { PortfolioRelationCell, PortfolioRelationsMatrix } from "../../api/relations";

export const STRONG_POSITIVE = 0.7;
export const MODERATE_POSITIVE = 0.4;
export const MEANINGFUL_NEGATIVE = -0.4;

export type AvailablePair = {
  symbol_a: string;
  symbol_b: string;
  pearson: number;
  sample_count?: number | null;
  as_of_date?: string | null;
  status: string;
};

export type RelationsInsight = {
  kind:
    | "INSUFFICIENT_DATA"
    | "SINGLE_INSTRUMENT"
    | "STRONG_CLUSTER"
    | "STRONG_PAIR_ONLY"
    | "NO_STRONG_CLUSTER"
    | "NEGATIVE_PRESENT";
  title_ru: string;
  body_ru: string;
  bullets_ru: string[];
  cluster: string[];
  weakly_linked: string[];
  unsupported: string[];
  available_pairs: AvailablePair[];
  pair_availability_ru: string | null;
};

function otherOf(pair: AvailablePair, symbol: string): string | null {
  if (pair.symbol_a === symbol) return pair.symbol_b;
  if (pair.symbol_b === symbol) return pair.symbol_a;
  return null;
}

export function extractAvailablePairs(cells: PortfolioRelationCell[]): AvailablePair[] {
  const out: AvailablePair[] = [];
  for (const c of cells) {
    if (c.symbol_a === c.symbol_b) continue;
    if (c.status !== "OK") continue;
    if (c.pearson == null || Number.isNaN(c.pearson)) continue;
    out.push({
      symbol_a: c.symbol_a,
      symbol_b: c.symbol_b,
      pearson: c.pearson,
      sample_count: c.sample_count,
      as_of_date: c.as_of_date,
      status: c.status,
    });
  }
  out.sort((a, b) => {
    const ka = a.symbol_a < a.symbol_b ? `${a.symbol_a}|${a.symbol_b}` : `${a.symbol_b}|${a.symbol_a}`;
    const kb = b.symbol_a < b.symbol_b ? `${b.symbol_a}|${b.symbol_b}` : `${b.symbol_b}|${b.symbol_a}`;
    return ka.localeCompare(kb);
  });
  return out;
}

function connectedComponents(nodes: string[], edges: AvailablePair[]): string[][] {
  const adj = new Map<string, Set<string>>();
  for (const n of nodes) adj.set(n, new Set());
  for (const e of edges) {
    adj.get(e.symbol_a)?.add(e.symbol_b);
    adj.get(e.symbol_b)?.add(e.symbol_a);
  }
  const seen = new Set<string>();
  const comps: string[][] = [];
  const ordered = [...nodes].sort((a, b) => a.localeCompare(b));
  for (const start of ordered) {
    if (seen.has(start)) continue;
    const stack = [start];
    const comp: string[] = [];
    seen.add(start);
    while (stack.length) {
      const cur = stack.pop()!;
      comp.push(cur);
      for (const nxt of [...(adj.get(cur) ?? [])].sort((a, b) => a.localeCompare(b))) {
        if (!seen.has(nxt)) {
          seen.add(nxt);
          stack.push(nxt);
        }
      }
    }
    comps.push(comp.sort((a, b) => a.localeCompare(b)));
  }
  return comps.sort((a, b) => b.length - a.length || a.join(",").localeCompare(b.join(",")));
}

function joinNames(symbols: string[]): string {
  if (symbols.length === 0) return "";
  if (symbols.length === 1) return symbols[0];
  if (symbols.length === 2) return `${symbols[0]} и ${symbols[1]}`;
  return `${symbols.slice(0, -1).join(", ")} и ${symbols[symbols.length - 1]}`;
}

function maxCorrWithCluster(
  symbol: string,
  cluster: string[],
  pairs: AvailablePair[],
): number | null {
  let max: number | null = null;
  for (const p of pairs) {
    const other = otherOf(p, symbol);
    if (other == null || !cluster.includes(other)) continue;
    if (max == null || p.pearson > max) max = p.pearson;
  }
  return max;
}

export function buildRelationsInsight(data: PortfolioRelationsMatrix): RelationsInsight {
  const supported = data.instruments
    .filter((i) => i.status === "READY")
    .map((i) => i.symbol)
    .sort((a, b) => a.localeCompare(b));
  const unsupported = data.instruments
    .filter((i) => i.status !== "READY")
    .map((i) => i.symbol)
    .sort((a, b) => a.localeCompare(b));

  const available = extractAvailablePairs(data.cells);
  const pairAvail =
    data.summary.pair_count > 0
      ? `Данные доступны для ${data.summary.available_pair_count} из ${data.summary.pair_count} возможных пар`
      : null;

  const baseUnsupportedBullet =
    unsupported.length > 0
      ? unsupported.length === 1
        ? `Для ${unsupported[0]} данных пока недостаточно — инструмент не участвует в этом выводе.`
        : `Для ${unsupported.length} из ${data.symbols.length} позиций (${joinNames(unsupported)}) данных пока недостаточно — они не участвуют в этом выводе.`
      : null;

  if (supported.length === 0) {
    return {
      kind: "INSUFFICIENT_DATA",
      title_ru: "Недостаточно данных",
      body_ru: "Недостаточно данных, чтобы оценить структуру связей портфеля.",
      bullets_ru: [baseUnsupportedBullet].filter(Boolean) as string[],
      cluster: [],
      weakly_linked: [],
      unsupported,
      available_pairs: available,
      pair_availability_ru: pairAvail,
    };
  }

  if (supported.length === 1) {
    return {
      kind: "SINGLE_INSTRUMENT",
      title_ru: "Одна позиция с данными",
      body_ru: `Связи между позициями можно оценить только для пар. Сейчас с данными доступен только ${supported[0]}.`,
      bullets_ru: [baseUnsupportedBullet].filter(Boolean) as string[],
      cluster: [],
      weakly_linked: supported,
      unsupported,
      available_pairs: available,
      pair_availability_ru: pairAvail,
    };
  }

  if (available.length === 0) {
    return {
      kind: "INSUFFICIENT_DATA",
      title_ru: "Недостаточно данных",
      body_ru: "Недостаточно данных, чтобы оценить структуру связей портфеля.",
      bullets_ru: [baseUnsupportedBullet].filter(Boolean) as string[],
      cluster: [],
      weakly_linked: supported,
      unsupported,
      available_pairs: available,
      pair_availability_ru: pairAvail,
    };
  }

  const strong = available.filter((p) => p.pearson >= STRONG_POSITIVE);
  const moderate = available.filter(
    (p) => p.pearson >= MODERATE_POSITIVE && p.pearson < STRONG_POSITIVE,
  );
  const negative = available.filter((p) => p.pearson <= MEANINGFUL_NEGATIVE);

  // Components only among nodes that appear in strong edges
  const strongNodes = Array.from(
    new Set(strong.flatMap((p) => [p.symbol_a, p.symbol_b])),
  ).sort((a, b) => a.localeCompare(b));
  const comps = connectedComponents(strongNodes, strong);
  const largest = comps[0] ?? [];

  const bullets: string[] = [];

  if (largest.length >= 3) {
    const weakly = supported
      .filter((s) => !largest.includes(s))
      .filter((s) => {
        const m = maxCorrWithCluster(s, largest, available);
        return m != null && m < STRONG_POSITIVE;
      });

    for (const w of weakly) {
      const m = maxCorrWithCluster(w, largest, available);
      if (m != null && m < MODERATE_POSITIVE) {
        bullets.push(
          `${w} исторически связан с этой группой заметно слабее (корреляция доходностей до ${m.toFixed(2)}).`,
        );
      } else if (m != null) {
        bullets.push(
          `${w} связан с группой умеренно (до ${m.toFixed(2)}), но не входит в тесный кластер.`,
        );
      }
    }

    if (baseUnsupportedBullet) bullets.push(baseUnsupportedBullet);
    if (negative.length) {
      const n = negative[0];
      bullets.push(
        `Есть и отрицательные связи (например ${n.symbol_a} × ${n.symbol_b}: ${n.pearson.toFixed(2)}) — чаще двигались в разные стороны.`,
      );
    }

    return {
      kind: "STRONG_CLUSTER",
      title_ru: "В портфеле есть группа тесно связанных позиций",
      body_ru: `${joinNames(largest)} исторически часто двигались в одном направлении за рассматриваемый период. Такая группа даёт меньше независимой диверсификации, чем набор слабо связанных позиций.`,
      bullets_ru: bullets,
      cluster: largest,
      weakly_linked: weakly,
      unsupported,
      available_pairs: available,
      pair_availability_ru: pairAvail,
    };
  }

  if (largest.length === 2 && strong.length > 0) {
    const [a, b] = largest;
    const edge = strong.find(
      (p) =>
        (p.symbol_a === a && p.symbol_b === b) || (p.symbol_a === b && p.symbol_b === a),
    );
    const rest = supported.filter((s) => s !== a && s !== b);
    for (const w of rest) {
      const m = maxCorrWithCluster(w, largest, available);
      if (m != null && m < STRONG_POSITIVE) {
        bullets.push(`${w} связан с этой парой слабее.`);
      }
    }
    if (baseUnsupportedBullet) bullets.push(baseUnsupportedBullet);

    return {
      kind: "STRONG_PAIR_ONLY",
      title_ru: "Есть тесная пара, но не большая группа",
      body_ru: `Наиболее тесная связь: ${a} и ${b}${edge ? ` (${edge.pearson.toFixed(2)})` : ""}. Отдельной большой группы тесно связанных позиций не видно.`,
      bullets_ru: bullets,
      cluster: largest,
      weakly_linked: rest,
      unsupported,
      available_pairs: available,
      pair_availability_ru: pairAvail,
    };
  }

  // No strong cluster
  if (moderate.length > 0) {
    bullets.push(
      `Есть умеренные связи (например ${moderate[0].symbol_a} × ${moderate[0].symbol_b}: ${moderate[0].pearson.toFixed(2)}), но порог «тесной» группы (≥ ${STRONG_POSITIVE.toFixed(2)}) не достигнут.`,
    );
  } else {
    bullets.push("Сильных положительных связей (≥ 0.70) между доступными парами нет.");
  }
  if (negative.length) {
    bullets.push(
      `Отрицательные связи: ${negative.map((n) => `${n.symbol_a}×${n.symbol_b} ${n.pearson.toFixed(2)}`).join(", ")}.`,
    );
  }
  if (baseUnsupportedBullet) bullets.push(baseUnsupportedBullet);

  return {
    kind: negative.length && !moderate.length && !strong.length ? "NEGATIVE_PRESENT" : "NO_STRONG_CLUSTER",
    title_ru: "Выраженной группы тесно связанных позиций не обнаружено",
    body_ru:
      "По доступным парам нет кластера инструментов, которые стабильно двигались вместе на уровне сильной корреляции доходностей.",
    bullets_ru: bullets,
    cluster: [],
    weakly_linked: supported,
    unsupported,
    available_pairs: available,
    pair_availability_ru: pairAvail,
  };
}

export type GraphEdge = AvailablePair & {
  strength: "strong" | "moderate" | "weak" | "negative";
  showLabel: boolean;
};

export type GraphModel = {
  nodes: string[];
  edges: GraphEdge[];
};

export function buildGraphModel(data: PortfolioRelationsMatrix): GraphModel {
  const nodes = data.instruments
    .filter((i) => i.status === "READY")
    .map((i) => i.symbol)
    .sort((a, b) => a.localeCompare(b));
  const pairs = extractAvailablePairs(data.cells).filter(
    (p) => nodes.includes(p.symbol_a) && nodes.includes(p.symbol_b),
  );

  const edges: GraphEdge[] = pairs.map((p) => {
    let strength: GraphEdge["strength"] = "weak";
    if (p.pearson <= MEANINGFUL_NEGATIVE) strength = "negative";
    else if (p.pearson >= STRONG_POSITIVE) strength = "strong";
    else if (p.pearson >= MODERATE_POSITIVE) strength = "moderate";
    return {
      ...p,
      strength,
      showLabel: Math.abs(p.pearson) >= MODERATE_POSITIVE,
    };
  });

  edges.sort((a, b) => Math.abs(b.pearson) - Math.abs(a.pearson));
  return { nodes, edges };
}

/** Deterministic circular layout; optional cluster nodes grouped in an arc. */
export function layoutNodes(
  nodes: string[],
  cluster: string[],
  width: number,
  height: number,
): Map<string, { x: number; y: number }> {
  const cx = width / 2;
  const cy = height / 2;
  const r = Math.min(width, height) * 0.34;
  const ordered = [...nodes].sort((a, b) => {
    const ac = cluster.includes(a) ? 0 : 1;
    const bc = cluster.includes(b) ? 0 : 1;
    if (ac !== bc) return ac - bc;
    return a.localeCompare(b);
  });
  const n = ordered.length || 1;
  const map = new Map<string, { x: number; y: number }>();
  ordered.forEach((sym, i) => {
    // Start from top, clockwise — stable
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / n;
    map.set(sym, { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
  });
  return map;
}
