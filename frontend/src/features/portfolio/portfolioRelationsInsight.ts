/**
 * Deterministic presentation insight for Portfolio Relations UX V2.
 *
 * PRESENTATION-ONLY thresholds below are for UI copy / graph styling.
 * They must NOT affect Candidate, Risk Gate, Allocation, or persisted Relations.
 */

import type { PortfolioRelationCell, PortfolioRelationsMatrix } from "../../api/relations";

/** UX presentation band only — not an investment / research policy threshold. */
export const PRESENTATION_STRONG_POSITIVE = 0.7;
/** UX presentation band only — not an investment / research policy threshold. */
export const PRESENTATION_MODERATE_POSITIVE = 0.4;
/** UX presentation band only — not an investment / research policy threshold. */
export const PRESENTATION_MEANINGFUL_NEGATIVE = -0.4;

/** @deprecated Prefer PRESENTATION_* — aliases for existing imports. */
export const STRONG_POSITIVE = PRESENTATION_STRONG_POSITIVE;
export const MODERATE_POSITIVE = PRESENTATION_MODERATE_POSITIVE;
export const MEANINGFUL_NEGATIVE = PRESENTATION_MEANINGFUL_NEGATIVE;

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

function pairKey(a: string, b: string): string {
  return a <= b ? `${a}|${b}` : `${b}|${a}`;
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
  out.sort((a, b) =>
    pairKey(a.symbol_a, a.symbol_b).localeCompare(pairKey(b.symbol_a, b.symbol_b)),
  );
  return out;
}

function corrLookup(pairs: AvailablePair[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const p of pairs) map.set(pairKey(p.symbol_a, p.symbol_b), p.pearson);
  return map;
}

/**
 * Strong clique: every pairwise correlation among members is available
 * and >= PRESENTATION_STRONG_POSITIVE.
 * A path of strong edges (connected component) alone is NOT a tight group.
 */
export function isStrongClique(nodes: string[], pairs: AvailablePair[]): boolean {
  if (nodes.length < 2) return false;
  const lookup = corrLookup(pairs);
  const ordered = [...nodes].sort((a, b) => a.localeCompare(b));
  for (let i = 0; i < ordered.length; i += 1) {
    for (let j = i + 1; j < ordered.length; j += 1) {
      const v = lookup.get(pairKey(ordered[i], ordered[j]));
      if (v == null || v < PRESENTATION_STRONG_POSITIVE) return false;
    }
  }
  return true;
}

/** Deterministic largest strong clique (Candidate n ≤ 12). */
export function findLargestStrongClique(nodes: string[], pairs: AvailablePair[]): string[] {
  const candidates = [...new Set(nodes)].sort((a, b) => a.localeCompare(b));
  if (candidates.length < 3) {
    if (candidates.length === 2 && isStrongClique(candidates, pairs)) return candidates;
    return [];
  }
  for (let size = candidates.length; size >= 3; size -= 1) {
    for (const combo of combinations(candidates, size)) {
      if (isStrongClique(combo, pairs)) return combo;
    }
  }
  return [];
}

function combinations(items: string[], k: number): string[][] {
  const out: string[][] = [];
  const n = items.length;
  const idx = Array.from({ length: k }, (_, i) => i);
  const push = () => out.push(idx.map((i) => items[i]));
  push();
  while (true) {
    let i = k - 1;
    while (i >= 0 && idx[i] === n - k + i) i -= 1;
    if (i < 0) break;
    idx[i] += 1;
    for (let j = i + 1; j < k; j += 1) idx[j] = idx[j - 1] + 1;
    push();
  }
  return out;
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

  const strong = available.filter((p) => p.pearson >= PRESENTATION_STRONG_POSITIVE);
  const moderate = available.filter(
    (p) =>
      p.pearson >= PRESENTATION_MODERATE_POSITIVE && p.pearson < PRESENTATION_STRONG_POSITIVE,
  );
  const negative = available.filter((p) => p.pearson <= PRESENTATION_MEANINGFUL_NEGATIVE);

  const cliqueNodes = Array.from(
    new Set(available.flatMap((p) => [p.symbol_a, p.symbol_b])),
  ).sort((a, b) => a.localeCompare(b));
  const largestClique = findLargestStrongClique(cliqueNodes, available);

  const bullets: string[] = [];

  if (largestClique.length >= 3) {
    const weakly = supported
      .filter((s) => !largestClique.includes(s))
      .filter((s) => {
        const m = maxCorrWithCluster(s, largestClique, available);
        return m != null && m < PRESENTATION_STRONG_POSITIVE;
      });

    for (const w of weakly) {
      const m = maxCorrWithCluster(w, largestClique, available);
      if (m != null && m < PRESENTATION_MODERATE_POSITIVE) {
        bullets.push(
          `${w} исторически связан с этой группой заметно слабее (корреляция доходностей до ${m.toFixed(2)}).`,
        );
      } else if (m != null) {
        bullets.push(
          `${w} связан с группой умеренно (до ${m.toFixed(2)}), но не входит в тесную группу.`,
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
      body_ru: `${joinNames(largestClique)} исторически часто двигались в одном направлении за рассматриваемый период (каждая пара в группе — сильная положительная корреляция доходностей). Такая группа даёт меньше независимой диверсификации, чем набор слабо связанных позиций.`,
      bullets_ru: bullets,
      cluster: largestClique,
      weakly_linked: weakly,
      unsupported,
      available_pairs: available,
      pair_availability_ru: pairAvail,
    };
  }

  if (strong.length > 0) {
    const edge = [...strong].sort(
      (a, b) =>
        b.pearson - a.pearson ||
        pairKey(a.symbol_a, a.symbol_b).localeCompare(pairKey(b.symbol_a, b.symbol_b)),
    )[0];
    const pairNodes = [edge.symbol_a, edge.symbol_b].sort((a, b) => a.localeCompare(b));
    const rest = supported.filter((s) => !pairNodes.includes(s));
    for (const w of rest) {
      const m = maxCorrWithCluster(w, pairNodes, available);
      if (m != null && m < PRESENTATION_STRONG_POSITIVE) {
        bullets.push(`${w} связан с этой парой слабее.`);
      }
    }
    if (strong.length >= 2) {
      bullets.push(
        "Есть несколько сильных связей, но не все пары внутри набора тесно коррелируют друг с другом — это не считается «тесной группой».",
      );
    }
    if (baseUnsupportedBullet) bullets.push(baseUnsupportedBullet);

    return {
      kind: "STRONG_PAIR_ONLY",
      title_ru: "Есть тесная пара, но не большая группа",
      body_ru: `Наиболее тесная связь: ${pairNodes[0]} и ${pairNodes[1]} (${edge.pearson.toFixed(2)}). Отдельной группы, где каждая пара связана сильно, не видно.`,
      bullets_ru: bullets,
      cluster: pairNodes,
      weakly_linked: rest,
      unsupported,
      available_pairs: available,
      pair_availability_ru: pairAvail,
    };
  }

  if (moderate.length > 0) {
    bullets.push(
      `Есть умеренные связи (например ${moderate[0].symbol_a} × ${moderate[0].symbol_b}: ${moderate[0].pearson.toFixed(2)}), но порог «тесной» группы (≥ ${PRESENTATION_STRONG_POSITIVE.toFixed(2)}) не достигнут.`,
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
    kind:
      negative.length && !moderate.length && !strong.length
        ? "NEGATIVE_PRESENT"
        : "NO_STRONG_CLUSTER",
    title_ru: "Выраженной группы тесно связанных позиций не обнаружено",
    body_ru:
      "По доступным парам нет набора инструментов, где каждая пара имеет сильную положительную корреляцию доходностей.",
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
    if (p.pearson <= PRESENTATION_MEANINGFUL_NEGATIVE) strength = "negative";
    else if (p.pearson >= PRESENTATION_STRONG_POSITIVE) strength = "strong";
    else if (p.pearson >= PRESENTATION_MODERATE_POSITIVE) strength = "moderate";
    return {
      ...p,
      strength,
      showLabel: Math.abs(p.pearson) >= PRESENTATION_MODERATE_POSITIVE,
    };
  });

  edges.sort((a, b) => Math.abs(b.pearson) - Math.abs(a.pearson));
  return { nodes, edges };
}

/** Deterministic circular layout; optional clique nodes grouped in an arc. */
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
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / n;
    map.set(sym, { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
  });
  return map;
}
