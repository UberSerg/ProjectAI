import type { ManualPortfolioAnalysis } from "../../api/manualPortfolios";
import { isBondLike } from "../manualPortfolio/labels";

export interface AllocationWeights {
  equity: number;
  fixedIncome: number;
  cash: number;
}

/** Derive sleeve weights from primary portfolio analysis (no catalog fetch). */
export function allocationFromAnalysis(analysis: ManualPortfolioAnalysis): AllocationWeights {
  const nav = analysis.nav || 0;
  if (nav <= 0) {
    return { equity: 0, fixedIncome: 0, cash: 1 };
  }
  let equity = 0;
  let fixedIncome = 0;
  for (const row of analysis.positions) {
    const sleeve = (row as { sleeve?: string }).sleeve?.toUpperCase?.() ?? "";
    const fromAlloc = analysis.allocation.find((a) => a.symbol.toUpperCase() === row.symbol.toUpperCase());
    const allocSleeve = (fromAlloc?.sleeve ?? "").toUpperCase();
    const w = row.weight ?? (row.market_value != null ? row.market_value / nav : 0);
    const bond =
      allocSleeve.includes("FIXED") ||
      allocSleeve.includes("BOND") ||
      sleeve.includes("FIXED") ||
      isBondLike(null, null, typeof row.detail === "object" && row.detail ? row.detail : null) ||
      /^(SU|OFZ)/i.test(row.symbol) ||
      (row.capabilities?.can_fixed_income_analyze === true);
    if (bond) fixedIncome += w;
    else equity += w;
  }
  const cash = analysis.cash_rub / nav;
  const sum = equity + fixedIncome + cash;
  if (sum > 0 && Math.abs(sum - 1) > 0.02) {
    // Normalize soft drift from unsupported prices
    return {
      equity: equity / sum,
      fixedIncome: fixedIncome / sum,
      cash: cash / sum,
    };
  }
  return { equity, fixedIncome, cash };
}

export function unrealizedPnl(analysis: ManualPortfolioAnalysis): number | null {
  const byId = new Map(analysis.portfolio.positions.map((p) => [p.id, p]));
  let cost = 0;
  let hasCost = false;
  let mv = 0;
  let hasMv = false;
  for (const row of analysis.positions) {
    const pos = byId.get(row.position_id);
    if (pos?.average_price != null) {
      cost += pos.average_price * pos.units;
      hasCost = true;
    }
    if (row.market_value != null) {
      mv += row.market_value;
      hasMv = true;
    }
  }
  if (!hasCost || !hasMv) return null;
  return mv - cost;
}

export function topConcentration(analysis: ManualPortfolioAnalysis): {
  label: string;
  weight: number;
} | null {
  const top = [...analysis.concentration_by_issuer].sort((a, b) => b.weight - a.weight)[0];
  if (!top) return null;
  return { label: top.issuer_title || top.issuer_key, weight: top.weight };
}
