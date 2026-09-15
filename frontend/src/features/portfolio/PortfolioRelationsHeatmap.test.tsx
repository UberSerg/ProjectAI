import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HelpProvider } from "../../help";
import { getPortfolioRelationsMatrix } from "../../api/relations";
import { PortfolioRelationsBlock } from "./PortfolioRelationsHeatmap";

vi.mock("../../api/relations", () => ({
  getPortfolioRelationsMatrix: vi.fn(),
}));

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

const liveLike = {
  version: "PORTFOLIO_RELATIONS_VISUALIZATION_V1",
  metric: {
    name: "pearson",
    label_ru: "Корреляция доходностей (Pearson)",
    return_label_ru: "дневные лог-доходности",
    window_observations: 60,
    window_label_ru: "окно 60 торговых дней",
  },
  relation_set: { code: "basic_relations", version: 1, id: "x" },
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
    { symbol_a: "MGNT", symbol_b: "MGNT", pearson: 1, status: "DIAGONAL", is_valid: true },
    ok("MGNT", "CBOM", 0.16),
    ok("MGNT", "UPRO", 0.74),
    ok("MGNT", "RTKMP", 0.76),
    ok("CBOM", "UPRO", 0.15),
    ok("CBOM", "RTKMP", 0.24),
    ok("UPRO", "RTKMP", 0.81),
    {
      symbol_a: "MGNT",
      symbol_b: "SU26207RMFS9",
      pearson: null,
      status: "UNSUPPORTED_PAIR",
      is_valid: false,
    },
    {
      symbol_a: "MGNT",
      symbol_b: "RU000A0JR4U9",
      pearson: null,
      status: "UNSUPPORTED_PAIR",
      is_valid: false,
    },
  ],
  summary: {
    pair_count: 15,
    available_pair_count: 6,
    unavailable_pair_count: 9,
    status: "OK",
    status_ru: "Доступно 6 из 15 пар.",
  },
  as_of_date: "2026-08-28",
};

describe("PortfolioRelationsBlock UX V2", () => {
  beforeEach(() => {
    vi.mocked(getPortfolioRelationsMatrix).mockResolvedValue(liveLike as never);
  });

  it("shows human summary, graph, missing FI, and collapsed triangular details", async () => {
    render(
      <HelpProvider>
        <PortfolioRelationsBlock
          symbols={["MGNT", "CBOM", "UPRO", "RTKMP", "SU26207RMFS9", "RU000A0JR4U9"]}
        />
      </HelpProvider>,
    );

    expect(await screen.findByText("Связи внутри портфеля")).toBeInTheDocument();
    expect(
      screen.getByText(/исторически двигались вместе/i),
    ).toBeInTheDocument();

    const insight = screen.getByTestId("portfolio-relations-insight");
    expect(insight).toHaveTextContent(/тесно связанных/);
    expect(insight).toHaveTextContent(/MGNT/);
    expect(insight).toHaveTextContent(/CBOM/);
    expect(insight).not.toHaveTextContent("INPUT_MISSING");
    expect(insight).not.toHaveTextContent("LEVEL");
    expect(insight).toHaveTextContent(/6 из 15/);

    expect(screen.queryByText("Средняя |corr|")).not.toBeInTheDocument();
    expect(screen.queryByText("Сильнейшая +")).not.toBeInTheDocument();

    expect(screen.getByTestId("portfolio-relations-graph")).toBeInTheDocument();
    expect(screen.getAllByText("0.81").length).toBeGreaterThan(0);

    const missing = screen.getByTestId("portfolio-relations-missing");
    expect(missing).toHaveTextContent(/Нет данных для 2 из 6/);
    expect(missing).toHaveTextContent("SU26207RMFS9");
    expect(missing).not.toHaveTextContent("Relations universe");

    const details = screen.getByTestId("portfolio-relations-details");
    expect(details).not.toHaveAttribute("open");
    expect(screen.queryByLabelText("Матрица корреляции доходностей")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Подробные связи"));
    await waitFor(() => {
      expect(screen.getByLabelText("Матрица корреляции доходностей")).toBeInTheDocument();
    });

    const table = screen.getByLabelText("Матрица корреляции доходностей");
    expect(table).toHaveTextContent("0.81");
    expect(table).toHaveTextContent("N/A");
    // Diagonal 1.00 should not appear as a data cell label in triangular view
    // (headers only). Count of "1.00" should be 0.
    expect(table.textContent?.includes("1.00")).toBe(false);

    expect(getPortfolioRelationsMatrix).toHaveBeenCalledWith(
      {
        symbols: ["MGNT", "CBOM", "UPRO", "RTKMP", "SU26207RMFS9", "RU000A0JR4U9"],
        window: 60,
      },
      expect.any(AbortSignal),
    );
  });

  it("shows insufficient-data summary when all pairs missing", async () => {
    vi.mocked(getPortfolioRelationsMatrix).mockResolvedValue({
      ...liveLike,
      symbols: ["A", "B"],
      instruments: [
        { symbol: "A", status: "INPUT_MISSING" },
        { symbol: "B", status: "INPUT_MISSING" },
      ],
      cells: [],
      summary: {
        pair_count: 1,
        available_pair_count: 0,
        unavailable_pair_count: 1,
        status: "EMPTY",
      },
    } as never);

    render(
      <HelpProvider>
        <PortfolioRelationsBlock symbols={["A", "B"]} />
      </HelpProvider>,
    );

    expect(await screen.findByTestId("portfolio-relations-insight")).toHaveTextContent(
      /Недостаточно данных, чтобы оценить структуру связей/,
    );
  });

  it("shows no-strong-cluster summary", async () => {
    vi.mocked(getPortfolioRelationsMatrix).mockResolvedValue({
      ...liveLike,
      symbols: ["AAA", "BBB"],
      instruments: [
        { symbol: "AAA", status: "READY" },
        { symbol: "BBB", status: "READY" },
      ],
      cells: [ok("AAA", "BBB", 0.22)],
      summary: {
        pair_count: 1,
        available_pair_count: 1,
        unavailable_pair_count: 0,
        status: "OK",
      },
    } as never);

    render(
      <HelpProvider>
        <PortfolioRelationsBlock symbols={["AAA", "BBB"]} />
      </HelpProvider>,
    );

    expect(
      await screen.findByText(/Выраженной группы тесно связанных позиций не обнаружено/),
    ).toBeInTheDocument();
  });
});
