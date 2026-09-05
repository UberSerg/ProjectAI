import { describe, expect, it } from "vitest";
import { getMetricHelp, getPageHelp } from "./registry";
import { clampRange, presetRange } from "../features/quotes/range";

describe("help registry", () => {
  it("defines confidence as coverage×agreement×quality, not probability", () => {
    const entry = getMetricHelp("confidence");
    expect(entry).toBeTruthy();
    expect(entry?.summary.toLowerCase()).toContain("coverage");
    expect(entry?.summary.toLowerCase()).toContain("не вероятность");
    expect(entry?.details).toMatch(/coverage/i);
  });

  it("defines RSI14 and return_20d", () => {
    expect(getMetricHelp("rsi14")?.title).toBe("RSI14");
    expect(getMetricHelp("return_20d")?.title).toContain("20");
  });

  it("defines relations term and page help for existing pages", () => {
    expect(getMetricHelp("relations_term")?.title).toMatch(/Связи/);
    for (const id of [
      "overview",
      "market",
      "instrument",
      "analytics",
      "relations",
      "technical",
      "workflows",
      "system",
      "simulator",
      "simulator_run",
      "shadow",
      "research_lab",
      "research_compare",
    ]) {
      expect(getPageHelp(id)?.title).toBeTruthy();
    }
    expect(getMetricHelp("research_lab")?.title).toMatch(/Лаборатория/);
    expect(getMetricHelp("observed_holdout")?.title).toMatch(/holdout/i);
    expect(getMetricHelp("development_oos")?.title).toMatch(/OOS|Development/i);
  });

  it("defines simulator help metrics", () => {
    expect(getMetricHelp("sim_excess")?.summary.toLowerCase()).toContain("процентн");
    expect(getMetricHelp("sim_oos")?.summary.toLowerCase()).toMatch(/mixed|oos|research/);
    expect(getMetricHelp("sim_survivorship")?.title).toMatch(/Survivorship/);
    expect(getMetricHelp("decision_why")?.summary.toLowerCase()).toMatch(/llm|фактов/);
    expect(getMetricHelp("decision_pred_20d")?.title).toMatch(/20d|Predicted/i);
    expect(getMetricHelp("decision_rank")?.details.toLowerCase()).toMatch(/лучшая компания/);
    expect(getMetricHelp("shadow_portfolio")?.summary.toLowerCase()).toMatch(/проспектив/);
    expect(getMetricHelp("prospective_experiment")?.details.toLowerCase()).toMatch(/симулятор|open/);
    expect(getMetricHelp("research_cycle")?.title).toMatch(/исследовательский цикл/i);
    expect(getMetricHelp("daily_cycle_health")?.summary.toLowerCase()).toMatch(/синхрон/);
    expect(getMetricHelp("forward_outcome_pending")?.title).toMatch(/20d|outcome/i);
  });

  it("defines Model Edge Research Pack help keys", () => {
    for (const id of [
      "model_quality",
      "portfolio_translation",
      "economic_viability",
      "cash_hurdle",
      "rate_based_cash_proxy",
      "excess_vs_cash",
      "top_tail_quality",
      "top_k_precision",
      "top_k_recall",
      "loser_contamination",
      "rank_stability",
      "rank_churn",
      "rank_persistence",
      "model_disagreement",
      "decision_attribution",
      "regime_analysis",
      "paired_prospective_model",
      "sample_maturity",
      "rank_correlation",
      "top20_overlap",
      "break_even_cost",
    ]) {
      expect(getMetricHelp(id)?.title).toBeTruthy();
    }
    expect(getMetricHelp("cash_hurdle")?.summary).toMatch(/Условная денежная альтернатива/);
    expect(getMetricHelp("cash_hurdle")?.summary).toMatch(/исследовательский benchmark/);
    expect(getMetricHelp("top_tail_quality")?.summary).toMatch(/верхнюю его часть/);
    expect(getMetricHelp("rank_stability")?.summary).toMatch(/порядок инструментов/);
    expect(getPageHelp("research_diagnostics")?.title).toMatch(/Диагностика/);
    expect(getPageHelp("research_prospective")?.title).toMatch(/Проспективное/);
  });

  it("defines Fundamental & Event help keys", () => {
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
    expect(getMetricHelp("known_at")?.summary).toMatch(/известна рынку/);
    expect(getMetricHelp("dividend_recommendation")?.details).toMatch(/approval/i);
    expect(getPageHelp("fundamentals")?.title).toMatch(/Фундаментал/);
  });
});

describe("quote range helpers", () => {
  const available = { from: "2015-01-15", to: "2026-08-20" };

  it("clamps manual range to instrument availability", () => {
    expect(clampRange({ from: "2010-01-01", to: "2030-01-01" }, available)).toEqual(available);
  });

  it("builds presets relative to last available date", () => {
    expect(presetRange("MAX", available)).toEqual(available);
    expect(presetRange("1Y", available).to).toBe("2026-08-20");
    expect(presetRange("1Y", available).from).toBe("2025-08-20");
    expect(presetRange("YTD", available).from).toBe("2026-01-01");
  });

  it("short history later-listed instruments collapse long presets to available window", () => {
    const short = { from: "2024-06-01", to: "2024-09-01" };
    expect(presetRange("5Y", short)).toEqual(short);
    expect(presetRange("MAX", short)).toEqual(short);
  });
});
