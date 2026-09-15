import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { HelpProvider } from "../../help";
import { getPortfolioRelationsMatrix } from "../../api/relations";
import { PortfolioRelationsBlock } from "./PortfolioRelationsHeatmap";

vi.mock("../../api/relations", () => ({
  getPortfolioRelationsMatrix: vi.fn(),
}));

const matrix = {
  version: "PORTFOLIO_RELATIONS_VISUALIZATION_V1",
  metric: {
    name: "pearson",
    label_ru: "Корреляция доходностей (Pearson)",
    return_label_ru: "дневные лог-доходности",
    window_observations: 60,
    window_label_ru: "окно 60 торговых дней",
    note_ru:
      "Чем ближе значение к +1, тем чаще активы двигались в одном направлении. Историческая корреляция может меняться и не гарантирует будущего поведения.",
  },
  relation_set: { code: "basic_relations", version: 1, id: "x" },
  symbols: ["SBER", "GAZP", "SU26238"],
  instruments: [
    { symbol: "SBER", status: "READY" },
    { symbol: "GAZP", status: "READY" },
    {
      symbol: "SU26238",
      status: "INPUT_MISSING",
      reason_ru: "Нет Relations-входа",
    },
  ],
  cells: [
    {
      symbol_a: "SBER",
      symbol_b: "SBER",
      pearson: 1,
      status: "DIAGONAL",
      is_valid: true,
    },
    {
      symbol_a: "GAZP",
      symbol_b: "GAZP",
      pearson: 1,
      status: "DIAGONAL",
      is_valid: true,
    },
    {
      symbol_a: "SU26238",
      symbol_b: "SU26238",
      pearson: null,
      status: "INPUT_MISSING",
      is_valid: false,
    },
    {
      symbol_a: "SBER",
      symbol_b: "GAZP",
      pearson: 0.81,
      status: "OK",
      is_valid: true,
      sample_count: 58,
      as_of_date: "2026-09-05",
      band: "HIGH_POSITIVE",
    },
    {
      symbol_a: "SBER",
      symbol_b: "SU26238",
      pearson: null,
      status: "UNSUPPORTED_PAIR",
      is_valid: false,
      reason_ru: "Нет Relations-входа для SU26238.",
    },
    {
      symbol_a: "GAZP",
      symbol_b: "SU26238",
      pearson: null,
      status: "UNSUPPORTED_PAIR",
      is_valid: false,
      reason_ru: "Нет Relations-входа для SU26238.",
    },
  ],
  summary: {
    pair_count: 3,
    available_pair_count: 1,
    unavailable_pair_count: 2,
    strongest_positive: { symbol_a: "SBER", symbol_b: "GAZP", pearson: 0.81 },
    lowest: { symbol_a: "SBER", symbol_b: "GAZP", pearson: 0.81 },
    average_abs_correlation: 0.81,
    high_positive_pair_count: 1,
    status: "OK",
    status_ru: "Доступно 1 из 3 пар. Сильных положительных (≥0.70): 1.",
  },
  as_of_date: "2026-09-05",
};

describe("PortfolioRelationsBlock", () => {
  beforeEach(() => {
    vi.mocked(getPortfolioRelationsMatrix).mockResolvedValue(matrix as never);
  });

  it("renders heatmap, metadata, strongest pair and N/A for unsupported", async () => {
    render(
      <HelpProvider>
        <PortfolioRelationsBlock symbols={["SBER", "GAZP", "SU26238"]} />
      </HelpProvider>,
    );

    expect(await screen.findByText("Связи внутри портфеля")).toBeInTheDocument();
    expect(screen.getByText(/окно 60 торговых дней/)).toBeInTheDocument();
    expect(screen.getAllByText(/SBER×GAZP 0.81/).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Матрица корреляции доходностей")).toBeInTheDocument();
    expect(screen.getAllByText("0.81").length).toBeGreaterThan(0);
    expect(screen.getAllByText("N/A").length).toBeGreaterThan(0);
    expect(screen.getByText(/Облигации часто отсутствуют/)).toBeInTheDocument();
    expect(getPortfolioRelationsMatrix).toHaveBeenCalledWith(
      { symbols: ["SBER", "GAZP", "SU26238"], window: 60 },
      expect.any(AbortSignal),
    );
  });

  it("shows empty state when no available pairs", async () => {
    vi.mocked(getPortfolioRelationsMatrix).mockResolvedValue({
      ...matrix,
      cells: [],
      summary: {
        pair_count: 0,
        available_pair_count: 0,
        unavailable_pair_count: 0,
        status: "EMPTY",
        status_ru: "Нет доступных pairwise корреляций для текущего состава.",
      },
    } as never);

    render(
      <HelpProvider>
        <PortfolioRelationsBlock symbols={["AAA"]} />
      </HelpProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Корреляции недоступны")).toBeInTheDocument();
    });
  });
});
