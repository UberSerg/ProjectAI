import { describe, expect, it } from "vitest";
import { allocationFromAnalysis } from "./allocation";
import { buildKrakenActions } from "./recommendations";
import type { ManualPortfolioAnalysis } from "../../api/manualPortfolios";

describe("dashboard allocation", () => {
  it("splits equity / cash from analysis", () => {
    const analysis = {
      cash_rub: 25,
      nav: 100,
      market_value_supported: 75,
      positions: [
        {
          position_id: 1,
          instrument_id: 1,
          symbol: "SBER",
          units: 1,
          market_value: 75,
          unit_price: 75,
          quality: "LIVE",
          price_source: null,
          supported: true,
          detail: {},
          capabilities: {},
          suggested_action: "KEEP",
          research_member: true,
          weight: 0.75,
        },
      ],
      allocation: [{ symbol: "SBER", weight: 0.75, sleeve: "EQUITY" }],
      concentration_by_issuer: [],
      risk_findings: [],
      coverage_pct: 1,
      quality: "LIVE",
      unsupported_count: 0,
      advisory: true,
      note: "",
      portfolio: {
        id: 1,
        name: "P",
        source: "M",
        base_currency: "RUB",
        cash_rub: 25,
        version: 1,
        created_at: null,
        updated_at: null,
        positions: [],
      },
    } as ManualPortfolioAnalysis;
    const w = allocationFromAnalysis(analysis);
    expect(w.equity).toBeCloseTo(0.75, 2);
    expect(w.cash).toBeCloseTo(0.25, 2);
  });
});

describe("buildKrakenActions", () => {
  it("prefers rebalance rows", () => {
    const cards = buildKrakenActions({
      analysis: null,
      compare: null,
      decision: null,
      rebalance: {
        advisory: true,
        persisted_orders: false,
        nav: 1,
        cash: 1,
        projected_cash: 1,
        plan_rows: [
          {
            instrument_id: 1,
            ticker: "LKOH",
            action: "BUY",
            lots_delta: 1,
            units_delta: 1,
            target_weight: 0.1,
            current_weight: 0,
            estimated_price: 1,
            estimated_notional: 1,
            lot_size: 1,
            reason: "Довести вес",
          },
        ],
        review_rows: [],
        diagnostics: {},
        cash_safe: true,
      },
    });
    expect(cards[0]?.title).toMatch(/Докупить LKOH/);
    expect(cards[0]?.cta).toBe("Подробнее");
    expect(cards[0]?.href).toContain("tab=rebalance");
    expect(cards[0]?.bullets.length).toBeGreaterThan(0);
  });

  it("falls back to hold when empty", () => {
    const cards = buildKrakenActions({
      analysis: {
        positions: [{ symbol: "SBER" }],
        cash_rub: 1,
      } as never,
      rebalance: null,
      compare: null,
      decision: null,
    });
    expect(cards.some((c) => c.id === "hold-default")).toBe(true);
  });
});
