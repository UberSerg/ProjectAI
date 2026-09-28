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
  /** Personal Portfolio application boundary (journal → projection → analytics). */
  source?: "personal_portfolio" | string;
  journal_state?: "EMPTY" | "LEGACY_PENDING" | "ACTIVE" | string;
  journal_cutover_at?: string | null;
  contributed_rub?: number;
  withdrawn_rub?: number;
  investment_pnl_rub?: number | null;
  realized_pnl_rub?: number;
  valuation_complete?: boolean;
  valuation_partial?: boolean;
  valuation_as_of?: string | null;
  valuation_from?: string | null;
  valuation_to?: string | null;
  valuation_label?: string | null;
  missing_price_count?: number;
  credit_intelligence?: {
    government_weight: number;
    corporate_weight: number;
    rated_corporate_weight: number;
    unrated_corporate_weight: number;
    credit_data_unavailable_weight: number;
    no_rating_found_weight?: number;
    bond_weight: number;
    top_issuers: Array<{
      issuer_key: string;
      issuer_title: string;
      market_value: number;
      weight: number;
      availability_status?: string;
      rating_raw?: string | null;
      agency_code?: string | null;
      symbols?: string[];
    }>;
    provider_verdict?: string;
    notes?: string[];
    advisory?: boolean;
  };
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

export function getPrimaryManualPortfolio(_signal?: AbortSignal): Promise<ManualPortfolio> {
  return Promise.reject(new Error("/manual-portfolios/primary retired"));
}

export function updatePrimaryCash(_cashRub: number, _signal?: AbortSignal): Promise<ManualPortfolio> {
  return Promise.reject(new Error("/manual-portfolios/primary retired"));
}

export function addPrimaryPosition(
  _body: PositionCreateBody,
  _signal?: AbortSignal,
): Promise<ManualPosition> {
  return Promise.reject(new Error("Use addDraftPosition(portfolioId, ...)"));
}

export function patchPrimaryPosition(
  _positionId: number,
  _body: PositionPatchBody,
  _signal?: AbortSignal,
): Promise<ManualPosition> {
  return Promise.reject(new Error("Use patchDraftPosition(portfolioId, ...)"));
}

export function deletePrimaryPosition(
  _positionId: number,
  _signal?: AbortSignal,
): Promise<{ status: string; id: number }> {
  return Promise.reject(new Error("Use deleteDraftPosition(portfolioId, ...)"));
}

export function getPortfolioAnalysis(
  portfolioId: number,
  signal?: AbortSignal,
): Promise<ManualPortfolioAnalysis> {
  return apiRequest(`/personal-portfolios/${portfolioId}/analysis`, { signal });
}

/** @deprecated use getPortfolioAnalysis(portfolioId) */
export function getPrimaryAnalysis(portfolioId: number, signal?: AbortSignal) {
  return getPortfolioAnalysis(portfolioId, signal);
}

export function getPortfolioCompareCandidate(
  portfolioId: number,
  signal?: AbortSignal,
): Promise<ManualCompareCandidate> {
  return apiRequest(`/personal-portfolios/${portfolioId}/compare-candidate`, { signal });
}

/** @deprecated use getPortfolioCompareCandidate(portfolioId) */
export function getPrimaryCompareCandidate(portfolioId: number, signal?: AbortSignal) {
  return getPortfolioCompareCandidate(portfolioId, signal);
}

export function getPortfolioRebalance(
  portfolioId: number,
  signal?: AbortSignal,
): Promise<ManualRebalancePlan> {
  return apiRequest(`/personal-portfolios/${portfolioId}/rebalance`, { signal });
}

/** @deprecated use getPortfolioRebalance(portfolioId) */
export function getPrimaryRebalance(portfolioId: number, signal?: AbortSignal) {
  return getPortfolioRebalance(portfolioId, signal);
}

export interface PortfolioCashflowHorizon {
  days: number;
  gross: number;
  coupon: number;
  amortization: number;
  redemption: number;
  event_count: number;
}

export interface PortfolioCashflowEvent {
  instrument_id: number;
  symbol: string;
  event_date: string;
  event_type: string;
  amount_per_unit: number | null;
  units: number;
  gross_amount: number | null;
  currency: string | null;
  informational: boolean;
}

export interface PortfolioCashflows {
  as_of: string;
  portfolio_id: number;
  horizons: Record<string, PortfolioCashflowHorizon>;
  events: PortfolioCashflowEvent[];
  next_payment: PortfolioCashflowEvent | null;
  positions: Array<{
    instrument_id: number;
    symbol: string;
    units: number;
    bond_type: string | null;
    maturity_date: string | null;
    cashflow_count: number;
    next_payment: PortfolioCashflowEvent | null;
    enrichment_pending: boolean;
    missing_terms: boolean;
  }>;
  analysis: {
    maturity_ladder: Record<string, number>;
    gov_vs_corp: { government: number; corporate_or_other: number };
    bond_position_count: number;
  };
  note?: string;
}

export function getPortfolioCashflows(
  portfolioId: number,
  signal?: AbortSignal,
): Promise<PortfolioCashflows> {
  return apiRequest(`/personal-portfolios/${portfolioId}/cashflows`, { signal });
}

/** @deprecated use getPortfolioCashflows(portfolioId) */
export function getPrimaryCashflows(portfolioId: number, signal?: AbortSignal) {
  return getPortfolioCashflows(portfolioId, signal);
}
