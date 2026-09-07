import { apiRequest } from "./client";

export interface ManualPosition {
  id: number;
  instrument_id: number;
  units: number;
  average_price: number | null;
  note: string | null;
  non_standard_lot: boolean;
}

export interface ManualPortfolio {
  id: number;
  name: string;
  source: string;
  base_currency: string;
  cash_rub: number;
  version: number;
  created_at: string | null;
  updated_at: string | null;
  positions: ManualPosition[];
}

export interface ManualPositionAnalysis {
  position_id: number;
  instrument_id: number;
  symbol: string;
  units: number;
  market_value: number | null;
  unit_price: number | null;
  quality: string;
  price_source: string | null;
  supported: boolean;
  detail: Record<string, unknown>;
  capabilities: Record<string, unknown>;
  suggested_action: string;
  research_member: boolean;
  weight: number | null;
}

export interface ManualRiskFinding {
  code: string;
  severity: string;
  message: string;
  symbol?: string;
  issuer?: string;
  weight?: number;
  instrument_id?: number;
  detail?: Record<string, unknown>;
}

export interface ManualPortfolioAnalysis {
  portfolio: ManualPortfolio;
  cash_rub: number;
  market_value_supported: number;
  nav: number;
  positions: ManualPositionAnalysis[];
  allocation: Array<{ symbol: string; weight: number; sleeve?: string }>;
  concentration_by_issuer: Array<{
    issuer_key: string;
    issuer_title: string;
    market_value: number;
    weight: number;
  }>;
  risk_findings: ManualRiskFinding[];
  coverage_pct: number;
  quality: string;
  unsupported_count: number;
  advisory: boolean;
  note: string;
}

export interface ManualCompareRow {
  symbol: string;
  manual_weight: number | null;
  candidate_weight: number | null;
  status: string;
  suggested_action: string;
  note: string | null;
}

export interface ManualCompareCandidate {
  nav: number;
  candidate_source: string;
  candidate_id?: string | null;
  comparisons: ManualCompareRow[];
  manual_analysis: {
    coverage_pct: number;
    quality: string;
    risk_findings: ManualRiskFinding[];
  };
}

export interface ManualRebalancePlanRow {
  instrument_id: number;
  ticker: string;
  action: string;
  lots_delta: number;
  units_delta: number;
  target_weight: number;
  current_weight: number;
  estimated_price: number | null;
  estimated_notional: number;
  lot_size: number | null;
  reason: string;
}

export interface ManualRebalanceReviewRow {
  symbol: string;
  reason: string;
  action: string;
  manual_units?: number;
  target_weight?: number;
}

export interface ManualRebalancePlan {
  advisory: boolean;
  persisted_orders: boolean;
  nav: number;
  cash: number;
  projected_cash: number;
  plan_rows: ManualRebalancePlanRow[];
  review_rows: ManualRebalanceReviewRow[];
  diagnostics: Record<string, unknown>;
  cash_safe: boolean;
}

export interface PositionCreateBody {
  instrument_id: number;
  units: number;
  average_price?: number | null;
  note?: string | null;
  non_standard_lot?: boolean;
}

export interface PositionPatchBody {
  units?: number;
  average_price?: number | null;
  note?: string | null;
  non_standard_lot?: boolean;
}

export function getPrimaryManualPortfolio(signal?: AbortSignal): Promise<ManualPortfolio> {
  return apiRequest("/manual-portfolios/primary", { signal });
}

export function updatePrimaryCash(cashRub: number, signal?: AbortSignal): Promise<ManualPortfolio> {
  return apiRequest("/manual-portfolios/primary/cash", {
    method: "PUT",
    body: { cash_rub: cashRub },
    signal,
  });
}

export function addPrimaryPosition(
  body: PositionCreateBody,
  signal?: AbortSignal,
): Promise<ManualPosition> {
  return apiRequest("/manual-portfolios/primary/positions", {
    method: "POST",
    body,
    signal,
  });
}

export function patchPrimaryPosition(
  positionId: number,
  body: PositionPatchBody,
  signal?: AbortSignal,
): Promise<ManualPosition> {
  return apiRequest(`/manual-portfolios/primary/positions/${positionId}`, {
    method: "PATCH",
    body,
    signal,
  });
}

export function deletePrimaryPosition(
  positionId: number,
  signal?: AbortSignal,
): Promise<{ status: string; id: number }> {
  return apiRequest(`/manual-portfolios/primary/positions/${positionId}`, {
    method: "DELETE",
    signal,
  });
}

export function getPrimaryAnalysis(signal?: AbortSignal): Promise<ManualPortfolioAnalysis> {
  return apiRequest("/manual-portfolios/primary/analysis", { signal });
}

export function getPrimaryCompareCandidate(signal?: AbortSignal): Promise<ManualCompareCandidate> {
  return apiRequest("/manual-portfolios/primary/compare-candidate", { signal });
}

export function getPrimaryRebalance(signal?: AbortSignal): Promise<ManualRebalancePlan> {
  return apiRequest("/manual-portfolios/primary/rebalance", { signal });
}
