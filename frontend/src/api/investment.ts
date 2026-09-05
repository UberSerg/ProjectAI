import { apiRequest } from "./client";

export interface HurdleQuote {
  status: string;
  as_of?: string;
  annual_rate?: number;
  hurdle_return?: number;
  hurdle_20d?: number;
  hurdle_1y?: number;
  known_at_quality?: string;
  source?: string;
  disclaimer?: string;
}

export interface ReadinessCheck {
  code: string;
  status: string;
}

export interface BondInstrument {
  instrument_id: number;
  symbol: string;
  name: string;
  bond_type: string;
  currency?: string | null;
  currency_display?: string | null;
  currency_raw?: string | null;
  nominal?: number | null;
  maturity_date?: string | null;
  support_status: string;
  credit_quality_status: string;
  real_portfolio_eligible: boolean;
}

export interface AllocationPosition {
  symbol: string;
  lots: number;
  units: number;
  notional: string | number;
  fees: string | number;
  cash_used: string | number;
}

export const getHurdle = (signal?: AbortSignal) =>
  apiRequest<HurdleQuote>("/investment/hurdle?horizon=1y", { signal });

export const getInvestmentReadiness = (signal?: AbortSignal) =>
  apiRequest<{ status: string; checks: ReadinessCheck[] }>("/investment/readiness", { signal });

export const getBonds = (signal?: AbortSignal) =>
  apiRequest<{ items: BondInstrument[] }>("/fixed-income/instruments", { signal });

export const previewAllocation = (body: {
  capital: number;
  cost_bps: number;
  candidates: Array<{
    symbol: string;
    sleeve: string;
    price: number;
    lot_size: number;
    target_weight: number;
  }>;
}) =>
  apiRequest<{
    positions: AllocationPosition[];
    fees: string | number;
    cash_remainder: string | number;
    diagnostics: string[];
    mode: string;
  }>("/portfolio/allocation/preview", { method: "POST", body });

export interface AllocationDecisionView {
  policy_id: string;
  equity_weight: number;
  fixed_income_weight: number;
  cash_weight: number;
  weights_pct: { equity: number; fixed_income: number; cash: number };
  reason_codes: string[];
  reason_codes_ru: string[];
  explanation_ru: string;
  status: string;
  confidence: number | null;
  limitations: string[];
  bond_safety_reminder: string;
}

export interface AllocationDecideResponse {
  context: Record<string, unknown>;
  decision: AllocationDecisionView;
  lots: {
    sleeve_cash_used: Record<string, string>;
    target_weights: { equity: number; fixed_income: number; cash: number };
    lot_result: {
      cash_remainder: string | number;
      fees: string | number;
      positions: AllocationPosition[];
    };
  };
  economic_verdict: {
    question_ru: string;
    answer_ru: string;
    cbr_hurdle_return?: number | null;
  };
  mode: string;
}

export const getAllocationPolicies = (signal?: AbortSignal) =>
  apiRequest<{ policies: Array<{ id: string; title: string; kind: string }> }>(
    "/allocation/policies",
    { signal },
  );

export const decideAllocation = (
  body: {
    policy_id: string;
    capital: number;
    equity_expected_excess_return?: number | null;
    equity_price?: number;
    equity_lot_size?: number;
    bond_price?: number;
    bond_lot_size?: number;
    cost_bps?: number;
  },
  signal?: AbortSignal,
) =>
  apiRequest<AllocationDecideResponse>("/allocation/decide", {
    method: "POST",
    body,
    signal,
  });

export const compareAllocations = (
  params?: { capital?: number; equity_expected_excess_return?: number | null },
  signal?: AbortSignal,
) => {
  const q = new URLSearchParams();
  if (params?.capital != null) q.set("capital", String(params.capital));
  if (params?.equity_expected_excess_return != null) {
    q.set("equity_expected_excess_return", String(params.equity_expected_excess_return));
  }
  const suffix = q.toString() ? `?${q}` : "";
  return apiRequest<{
    comparisons: Array<{
      policy: { id: string; title: string };
      decision: AllocationDecisionView;
    }>;
    note: string;
  }>(`/allocation/compare${suffix}`, { signal });
};
