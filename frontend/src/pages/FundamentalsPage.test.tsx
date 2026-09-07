import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as fundamentalsApi from "../api/fundamentals";
import { HelpProvider } from "../help";
import { getMetricHelp, getPageHelp } from "../help/registry";
import { FundamentalIssuerPage } from "./FundamentalIssuerPage";
import { FundamentalsPage } from "./FundamentalsPage";

vi.mock("../api/fundamentals", async () => {
  const actual = await vi.importActual<typeof import("../api/fundamentals")>("../api/fundamentals");
  return {
    ...actual,
    getFundamentalsSummary: vi.fn(),
    getFundamentalsCoverage: vi.fn(),
    getFundamentalsQuality: vi.fn(),
    getFundamentalsMlReadiness: vi.fn(),
    listFundamentalIssuers: vi.fn(),
    getFundamentalIssuer: vi.fn(),
    getIssuerReports: vi.fn(),
    getIssuerDividends: vi.fn(),
    getIssuerEvents: vi.fn(),
    getIssuerAsOf: vi.fn(),
    getTotalReturnCoverage: vi.fn(),
  };
});

describe("FundamentalsPage", () => {
  beforeEach(() => {
    vi.mocked(fundamentalsApi.getFundamentalsSummary).mockResolvedValue({
      status: "NOT_READY",
      pit_quality: "NOT_READY",
      issuers_mapped: 0,
      reports: 0,
      financial_facts: 0,
      dividend_events: 0,
      corporate_events: 0,
      providers: [{ name: "MOEX dividends", status: "DEFERRED", deferred: true }],
    });
    vi.mocked(fundamentalsApi.getFundamentalsCoverage).mockResolvedValue([]);
    vi.mocked(fundamentalsApi.getFundamentalsQuality).mockResolvedValue({
      status: "NOT_READY",
      reports_without_known_at: 0,
    });
    vi.mocked(fundamentalsApi.getFundamentalsMlReadiness).mockResolvedValue({
      status: "NOT_READY",
      dataset_v2_features: 90,
      fundamental_v1_candidate_features: 0,
      event_v1_candidate_features: 0,
      potential_v3_total: 90,
      pit_violations: 0,
      main_blockers: ["Живые дивидендные/отчётные ленты недоступны"],
    });
    vi.mocked(fundamentalsApi.listFundamentalIssuers).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(fundamentalsApi.getTotalReturnCoverage).mockResolvedValue({
      quality: "NOT_READY",
      verdict: "NOT_READY",
      dividend_events_stored: 0,
      instruments_with_dividend_events: 0,
      instruments_with_price_history: 10,
      coverage_ratio: 0,
      reasons: ["dividend_events_empty"],
      notes: [],
      mode: "TOTAL_RETURN_GROSS_V1",
      tax_treatment: "gross_pre_tax",
      simulator_total_return_mode: "NOT_IN_THIS_PR",
      dataset_mutation: false,
      training: false,
    });
  });

  it("renders fundamentals route and visible PIT card", async () => {
    render(
      <HelpProvider>
        <MemoryRouter initialEntries={["/fundamentals"]}>
          <Routes>
            <Route path="/fundamentals" element={<FundamentalsPage />} />
          </Routes>
        </MemoryRouter>
      </HelpProvider>,
    );

    expect(await screen.findByTestId("fundamentals-page")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Компании" })).toBeInTheDocument();
    expect(screen.getByTestId("fundamentals-coverage-summary")).toBeInTheDocument();
    expect(await screen.findByTestId("total-return-coverage")).toHaveTextContent(/Не готово|NOT_READY|Полная/i);
    expect(screen.getByTestId("pit-explanation-card")).toHaveTextContent(/Почему важна дата публикации/i);
    expect(screen.getByTestId("pit-explanation-card")).toHaveTextContent(/15 мая/i);
    expect(screen.getByTestId("fundamentals-ml-readiness")).toHaveTextContent(/Готовность к следующей модели/i);
    expect(screen.getByTestId("fundamentals-research-targets")).toHaveTextContent(/денежную альтернативу/i);
  });

  it("shows honest empty coverage and issuers state", async () => {
    render(
      <HelpProvider>
        <MemoryRouter initialEntries={["/fundamentals"]}>
          <Routes>
            <Route path="/fundamentals" element={<FundamentalsPage />} />
          </Routes>
        </MemoryRouter>
      </HelpProvider>,
    );

    expect(await screen.findByTestId("fundamentals-coverage-empty")).toBeInTheDocument();
    expect(screen.getByTestId("fundamentals-issuers-empty")).toHaveTextContent(/Список компаний пуст/i);
    expect(screen.getByTestId("fundamentals-quality")).toHaveTextContent(/Нельзя безопасно использовать в ML/i);
  });
});

describe("FundamentalIssuerPage", () => {
  beforeEach(() => {
    vi.mocked(fundamentalsApi.getFundamentalIssuer).mockResolvedValue({
      id: "42",
      name: "Тестовый эмитент",
      inn: "7707083893",
      securities: [{ ticker: "SBER", instrument_id: "1" }],
    });
    vi.mocked(fundamentalsApi.getIssuerReports).mockResolvedValue([]);
    vi.mocked(fundamentalsApi.getIssuerDividends).mockResolvedValue({
      status: "NOT_READY",
      history: [],
      events_stored_total: 0,
      total_return_foundation: {
        mode: "TOTAL_RETURN_GROSS_V1",
        available: false,
        note: "empty dividend_events",
      },
      note: "Empty because MOEX dividend endpoints were rejected.",
    });
    vi.mocked(fundamentalsApi.getIssuerEvents).mockResolvedValue([]);
  });

  it("shows as-of explorer and empty reports/dividends", async () => {
    render(
      <HelpProvider>
        <MemoryRouter initialEntries={["/fundamentals/42"]}>
          <Routes>
            <Route path="/fundamentals/:issuerId" element={<FundamentalIssuerPage />} />
          </Routes>
        </MemoryRouter>
      </HelpProvider>,
    );

    expect(await screen.findByTestId("fundamentals-issuer-page")).toBeInTheDocument();
    expect(screen.getByTestId("asof-explorer")).toHaveTextContent(/Что было известно на дату/i);
    expect(screen.getByTestId("asof-date-input")).toBeInTheDocument();
    expect(screen.getByTestId("reports-empty")).toBeInTheDocument();
    expect(screen.getByTestId("dividends-empty")).toBeInTheDocument();
    expect(screen.getByTestId("dividends-tr-foundation")).toHaveTextContent(/NOT_READY|событий нет/i);
  });

  it("loads as-of result when explorer is used", async () => {
    vi.mocked(fundamentalsApi.getIssuerAsOf).mockResolvedValue({
      as_of: "2024-04-01",
      latest_report: null,
      dividends: [],
      events: [],
      notes: ["На эту дату известных отчётов нет"],
    });

    render(
      <HelpProvider>
        <MemoryRouter initialEntries={["/fundamentals/42"]}>
          <Routes>
            <Route path="/fundamentals/:issuerId" element={<FundamentalIssuerPage />} />
          </Routes>
        </MemoryRouter>
      </HelpProvider>,
    );

    expect(await screen.findByTestId("asof-explorer")).toBeInTheDocument();
    await waitFor(async () => {
      screen.getByRole("button", { name: /Показать/i }).click();
      expect(await screen.findByTestId("asof-result")).toHaveTextContent(/2024-04-01/);
    });
    expect(fundamentalsApi.getIssuerAsOf).toHaveBeenCalledWith("42", "2024-04-01", expect.anything());
  });
});

describe("fundamentals help keys", () => {
  it("defines Phase 28 concept keys and page help", () => {
    for (const id of [
      "fundamental_data",
      "financial_report",
      "reporting_period",
      "publication_date",
      "known_at",
      "point_in_time",
      "restatement",
      "IFRS",
      "RAS",
      "revenue",
      "net_income",
      "EBITDA",
      "cash_flow",
      "margin",
      "dividend_recommendation",
      "dividend_approval",
      "record_date",
      "dividend_yield",
      "corporate_event",
      "report_age",
      "fundamental_staleness",
      "source_provenance",
    ]) {
      expect(getMetricHelp(id)?.title).toBeTruthy();
    }
    expect(getMetricHelp("known_at")?.summary).toMatch(/известна рынку/i);
    expect(getMetricHelp("IFRS")?.summary).toMatch(/Международные стандарты/i);
    expect(getMetricHelp("RAS")?.summary).toMatch(/Российские стандарты/i);
    expect(getMetricHelp("dividend_recommendation")?.summary).toMatch(/не утверждённый/i);
    expect(getPageHelp("fundamentals")?.title).toMatch(/Компании/);
  });
});
