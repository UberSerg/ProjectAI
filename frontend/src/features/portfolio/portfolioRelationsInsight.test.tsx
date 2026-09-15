import { describe, expect, it } from "vitest";
import type { PortfolioRelationsMatrix } from "../../api/relations";
import {
  buildGraphModel,
  buildRelationsInsight,
  extractAvailablePairs,
  STRONG_POSITIVE,
} from "./portfolioRelationsInsight";

function baseMatrix(partial: Partial<PortfolioRelationsMatrix>): PortfolioRelationsMatrix {
  return {
    version: "PORTFOLIO_RELATIONS_VISUALIZATION_V1",
    metric: {
      name: "pearson",
      window_observations: 60,
      window_label_ru: "окно 60 торговых дней",
    },
    symbols: [],
    instruments: [],
    cells: [],
    summary: {
      pair_count: 0,
      available_pair_count: 0,
      unavailable_pair_count: 0,
      status: "OK",
    },
    ...partial,
  };
}

function ok(a: string, b: string, pearson: number) {
  return {
    symbol_a: a,
    symbol_b: b,
    pearson,
    status: "OK",
    is_valid: true,
    sample_count: 58,
    as_of_date: "2026-08-28",
  };
}

function missing(a: string, b: string) {
  return {
    symbol_a: a,
    symbol_b: b,
    pearson: null,
    status: "UNSUPPORTED_PAIR",
    is_valid: false,
  };
}

describe("portfolioRelationsInsight", () => {
  it("builds strong cluster summary for live-like equity triangle + weak CBOM", () => {
    const data = baseMatrix({
      symbols: ["MGNT", "CBOM", "UPRO", "RTKMP", "SU26207RMFS9", "RU000A0JR4U9"],
      instruments: [
        { symbol: "MGNT", status: "READY" },
        { symbol: "CBOM", status: "READY" },
        { symbol: "UPRO", status: "READY" },
        { symbol: "RTKMP", status: "READY" },
        { symbol: "SU26207RMFS9", status: "INPUT_MISSING" },
        { symbol: "RU000A0JR4U9", status: "INPUT_MISSING" },
      ],
      cells: [
        ok("MGNT", "CBOM", 0.16),
        ok("MGNT", "UPRO", 0.74),
        ok("MGNT", "RTKMP", 0.76),
        ok("CBOM", "UPRO", 0.15),
        ok("CBOM", "RTKMP", 0.24),
        ok("UPRO", "RTKMP", 0.81),
        missing("MGNT", "SU26207RMFS9"),
        missing("MGNT", "RU000A0JR4U9"),
        missing("CBOM", "SU26207RMFS9"),
        missing("CBOM", "RU000A0JR4U9"),
        missing("UPRO", "SU26207RMFS9"),
        missing("UPRO", "RU000A0JR4U9"),
        missing("RTKMP", "SU26207RMFS9"),
        missing("RTKMP", "RU000A0JR4U9"),
        missing("SU26207RMFS9", "RU000A0JR4U9"),
      ],
      summary: {
        pair_count: 15,
        available_pair_count: 6,
        unavailable_pair_count: 9,
        status: "OK",
      },
    });

    const insight = buildRelationsInsight(data);
    expect(insight.kind).toBe("STRONG_CLUSTER");
    expect(insight.cluster).toEqual(["MGNT", "RTKMP", "UPRO"]);
    expect(insight.weakly_linked).toContain("CBOM");
    expect(insight.unsupported).toEqual(["RU000A0JR4U9", "SU26207RMFS9"]);
    expect(insight.title_ru).toMatch(/тесно связанных/);
    expect(insight.body_ru).toMatch(/MGNT/);
    expect(insight.body_ru).toMatch(/каждая пара/);
    expect(insight.bullets_ru.some((b) => b.includes("CBOM"))).toBe(true);
    expect(insight.bullets_ru.join(" ")).not.toMatch(/INPUT_MISSING|Relations universe/);
    expect(insight.pair_availability_ru).toMatch(/6 из 15/);

    const graph = buildGraphModel(data);
    expect(graph.nodes).toEqual(["CBOM", "MGNT", "RTKMP", "UPRO"]);
    expect(graph.edges).toHaveLength(6);
    expect(graph.edges.every((e) => e.pearson != null)).toBe(true);
    const strong = graph.edges.filter((e) => e.strength === "strong");
    expect(strong.length).toBe(3);
    expect(strong.every((e) => e.pearson >= STRONG_POSITIVE)).toBe(true);
  });

  it("does not call chain A-B / B-C / weak A-C a tight group (connected ≠ clique)", () => {
    const data = baseMatrix({
      symbols: ["A", "B", "C"],
      instruments: [
        { symbol: "A", status: "READY" },
        { symbol: "B", status: "READY" },
        { symbol: "C", status: "READY" },
      ],
      cells: [ok("A", "B", 0.8), ok("B", "C", 0.8), ok("A", "C", 0.1)],
      summary: { pair_count: 3, available_pair_count: 3, unavailable_pair_count: 0, status: "OK" },
    });
    const insight = buildRelationsInsight(data);
    expect(insight.kind).not.toBe("STRONG_CLUSTER");
    expect(insight.title_ru).not.toMatch(/группа тесно связанных/);
    expect(insight.kind).toBe("STRONG_PAIR_ONLY");
    expect(insight.cluster).toHaveLength(2);
    expect(insight.bullets_ru.join(" ")).toMatch(/не считается «тесной группой»/);
  });

  it("regression: live MGNT/UPRO/RTKMP triangle remains a tight strong clique", () => {
    const data = baseMatrix({
      symbols: ["MGNT", "UPRO", "RTKMP"],
      instruments: [
        { symbol: "MGNT", status: "READY" },
        { symbol: "UPRO", status: "READY" },
        { symbol: "RTKMP", status: "READY" },
      ],
      cells: [ok("MGNT", "UPRO", 0.74), ok("MGNT", "RTKMP", 0.76), ok("UPRO", "RTKMP", 0.81)],
      summary: { pair_count: 3, available_pair_count: 3, unavailable_pair_count: 0, status: "OK" },
    });
    const insight = buildRelationsInsight(data);
    expect(insight.kind).toBe("STRONG_CLUSTER");
    expect(insight.cluster).toEqual(["MGNT", "RTKMP", "UPRO"]);
    expect(insight.title_ru).toMatch(/группа тесно связанных/);
  });

  it("does not coerce null pearson to zero in available pairs", () => {
    const cells = [
      ok("A", "B", 0.5),
      { symbol_a: "A", symbol_b: "C", pearson: null, status: "OK", is_valid: false },
      missing("B", "C"),
    ];
    const pairs = extractAvailablePairs(cells as never);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].pearson).toBe(0.5);
    expect(pairs.some((p) => p.pearson === 0)).toBe(false);
  });

  it("reports no strong cluster when only moderate links exist", () => {
    const data = baseMatrix({
      symbols: ["AAA", "BBB", "CCC"],
      instruments: [
        { symbol: "AAA", status: "READY" },
        { symbol: "BBB", status: "READY" },
        { symbol: "CCC", status: "READY" },
      ],
      cells: [ok("AAA", "BBB", 0.45), ok("AAA", "CCC", 0.42), ok("BBB", "CCC", 0.41)],
      summary: { pair_count: 3, available_pair_count: 3, unavailable_pair_count: 0, status: "OK" },
    });
    const insight = buildRelationsInsight(data);
    expect(insight.kind).toBe("NO_STRONG_CLUSTER");
    expect(insight.cluster).toEqual([]);
    expect(insight.title_ru).toMatch(/не обнаружено/);
  });

  it("handles all missing", () => {
    const data = baseMatrix({
      symbols: ["X", "Y"],
      instruments: [
        { symbol: "X", status: "INPUT_MISSING" },
        { symbol: "Y", status: "INPUT_MISSING" },
      ],
      cells: [missing("X", "Y")],
      summary: { pair_count: 1, available_pair_count: 0, unavailable_pair_count: 1, status: "EMPTY" },
    });
    const insight = buildRelationsInsight(data);
    expect(insight.kind).toBe("INSUFFICIENT_DATA");
    expect(buildGraphModel(data).nodes).toEqual([]);
    expect(buildGraphModel(data).edges).toEqual([]);
  });

  it("mentions negative correlations", () => {
    const data = baseMatrix({
      symbols: ["A", "B"],
      instruments: [
        { symbol: "A", status: "READY" },
        { symbol: "B", status: "READY" },
      ],
      cells: [ok("A", "B", -0.55)],
      summary: { pair_count: 1, available_pair_count: 1, unavailable_pair_count: 0, status: "OK" },
    });
    const insight = buildRelationsInsight(data);
    expect(insight.kind).toBe("NEGATIVE_PRESENT");
    expect(insight.bullets_ru.join(" ")).toMatch(/-0\.55/);
    expect(buildGraphModel(data).edges[0].strength).toBe("negative");
  });

  it("handles single supported instrument", () => {
    const data = baseMatrix({
      symbols: ["ONLY", "BOND"],
      instruments: [
        { symbol: "ONLY", status: "READY" },
        { symbol: "BOND", status: "INPUT_MISSING" },
      ],
      cells: [missing("ONLY", "BOND")],
      summary: { pair_count: 1, available_pair_count: 0, unavailable_pair_count: 1, status: "EMPTY" },
    });
    expect(buildRelationsInsight(data).kind).toBe("SINGLE_INSTRUMENT");
  });
});
