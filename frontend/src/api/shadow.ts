/** Shadow Portfolio / Live Research API client. */

import { apiRequest } from "./client";
import type { IntradayLastRefresh } from "./intraday";

export interface ShadowLivePosition {
  instrument_id: number;
  ticker: string;
  quantity: number;
  lots?: number | null;
  lot_size?: number | null;
  avg_entry?: number | null;
  cost_basis?: number | null;
  realized_pnl?: number | null;
  mark_price?: number | null;
  mark_source?: string | null;
  market_value?: number | null;
  freshness?: string | null;
  entry_price?: number | null;
  invested_cost?: number | null;
  /** Alias used by UI; prefer unrealized_pnl_pct from API when present. */
  change_pct?: number | null;
  unrealized_pnl?: number | null;
  unrealized_pnl_pct?: number | null;
  quote_time?: string | null;
  observed_at?: string | null;
}

export interface ShadowLiveSnapshot {
  cash: number;
  invested_cost?: number | null;
  market_value: number;
  nav: number;
  unrealized_pnl?: number | null;
  unrealized_pnl_pct?: number | null;
  realized_pnl?: number | null;
  fees_paid?: number | null;
  quote_coverage?: number | null;
  warnings?: string[];
  as_of?: string | null;
  positions: ShadowLivePosition[];
}

export interface ShadowCashBreakdown {
  cash?: number | null;
  invested_cost?: number | null;
  market_value?: number | null;
  nav?: number | null;
  fees_paid?: number | null;
  realized_pnl?: number | null;
  unrealized_pnl?: number | null;
}

export interface ShadowOrderPlanSkipped {
  instrument_id?: number;
  ticker: string;
  action?: string;
  reason: string;
  lot_size?: number | null;
  rank?: number | null;
}

export interface ShadowOrderPlan {
  projected_cash?: number | null;
  fees_total?: number | null;
  rounding_remainder?: number | null;
  starting_cash?: number | null;
  strategic_cash_reserve?: number | null;
  sell_proceeds?: number | null;
  buy_notional?: number | null;
  rows?: Array<Record<string, unknown>>;
  skipped?: ShadowOrderPlanSkipped[];
  orders?: Array<Record<string, unknown>>;
}

export interface ShadowPendingOrderReason {
  order_id: number;
  ticker: string;
  side: string;
  min_execution_date: string;
  created_at?: string | null;
  reason: string;
  session_date?: string | null;
  delayed_observation?: boolean;
  open_price?: number | null;
  quote_freshness?: string | null;
  market_status?: string | null;
}

export interface ShadowReadinessSummary {
  ready_for_next_session?: boolean | null;
  blocker_code?: string | null;
  status_code?: string | null;
  latest_complete_eod_date?: string | null;
  pending_orders?: number | null;
}

export interface ShadowPortfolioSummary {
  id: string;
  name: string;
  status: string;
  policy_name: string;
  risk_name: string;
  activated_at?: string | null;
  cash: number;
  nav?: number;
  peak_nav?: number;
  initial_capital?: number;
  market_value?: number;
  drawdown?: number;
  gross_exposure?: number;
  nav_as_of?: string | null;
  risk_mode: string;
  exposure_cap: number;
  pending_orders: number;
  fills: number;
  position_count?: number;
  last_processed_market_date?: string | null;
  first_forward_batch_id?: number | null;
  first_forward_as_of_date?: string | null;
  last_decision_iso_week?: string | null;
  last_processed_prediction_batch_id?: number | null;
  experiment_group?: string | null;
  dd_trigger?: number | null;
  dd_recovery?: number | null;
  dd_risk_off_gross?: number | null;
  dd_normal_gross?: number | null;
  kind?: string;
  fractional_shares?: boolean;
  lot_aware?: boolean;
  execution_version?: string | null;
  version?: string | null;
  /** Live / intraday enrichment from overview or /live. */
  intraday_enabled?: boolean;
  open_execution_policy?: string | null;
  last_intraday_refresh?: IntradayLastRefresh | null;
  live?: ShadowLiveSnapshot | null;
  live_nav?: number | null;
  live_market_value?: number | null;
  cash_breakdown?: ShadowCashBreakdown | null;
  order_plan?: ShadowOrderPlan | null;
  skipped?: ShadowOrderPlanSkipped[] | null;
  pending_order_reasons?: ShadowPendingOrderReason[];
  pending_execution?: boolean;
  readiness?: ShadowReadinessSummary | null;
}

export interface ShadowOverviewIntraday {
  enabled: boolean;
  policy?: string | null;
  last_refresh?: IntradayLastRefresh | null;
  refresh_minutes?: number | null;
}

export interface ShadowOverview {
  kind: string;
  experiment_group?: string | null;
  activated_at?: string | null;
  automatic_schedule?: string | null;
  portfolios: ShadowPortfolioSummary[];
  intraday?: ShadowOverviewIntraday | null;
}

export interface ShadowLiveResponse {
  kind: string;
  intraday_enabled: boolean;
  open_execution_policy?: string | null;
  last_intraday_refresh?: IntradayLastRefresh | null;
  portfolios: ShadowPortfolioSummary[];
}

export interface ShadowDailyOperations {
  latest_complete_eod_date?: string | null;
  latest_forward_as_of?: string | null;
  order_plan_status?: string | null;
  pending_orders?: number | null;
  ready_for_next_session?: boolean | null;
  next_execution_session?: string | null;
  status_code?: string | null;
  blocker_code?: string | null;
  eod_readiness?: {
    ready?: boolean;
    blocker_code?: string | null;
    latest_complete_eod_date?: string | null;
    reason?: string | null;
  } | null;
  automation?: Record<string, unknown> | null;
  last_eod_cycle?: {
    workflow_id?: number | null;
    status?: string | null;
    finished_at?: string | null;
    covers_latest_eod?: boolean | null;
    stale?: boolean | null;
  } | null;
  last_intraday_refresh?: IntradayLastRefresh | null;
  consistency?: Array<Record<string, unknown>>;
  portfolios?: Array<{
    id: number;
    name: string;
    experiment_group?: string | null;
    status?: string;
    lot_aware?: boolean;
    fractional_shares?: boolean;
    cash?: number;
    last_processed_market_date?: string | null;
  }>;
  watermarks?: Record<string, string | null>;
}

export interface ShadowOrder {
  id: number;
  instrument_id?: number;
  ticker: string;
  display_name?: string | null;
  side: string;
  quantity: number;
  target_weight?: number | null;
  reason?: string | null;
  status: string;
  rank?: number | null;
  predicted_return_20d?: number | null;
  eligible_count?: number | null;
  decision_at?: string | null;
  min_execution_date?: string | null;
  execution_date?: string | null;
  decision_id?: number | null;
  metadata?: Record<string, unknown> | null;
}

export interface ShadowFill {
  id: number;
  order_id: number;
  ticker: string;
  side: string;
  quantity: number;
  raw_open?: number | null;
  fill_price?: number | null;
  notional?: number | null;
  commission?: number | null;
  slippage_cost?: number | null;
  execution_date: string;
  filled_at?: string | null;
  decision_at?: string | null;
}

export interface ShadowNavPoint {
  as_of_date: string;
  cash: number;
  market_value: number;
  nav: number;
  gross_exposure: number;
  drawdown: number;
  peak_nav?: number;
  position_count: number;
  benchmark_value?: number | null;
}

export interface ShadowDecision {
  id: number;
  forward_batch_id: number;
  signal_as_of_date: string;
  signal_generated_at?: string | null;
  decision_at?: string | null;
  iso_week: string;
  targets?: Array<Record<string, unknown>>;
  risk_mode?: string | null;
  exposure_cap?: number | null;
  policy_name?: string | null;
  risk_name?: string | null;
  metadata?: Record<string, unknown> | null;
}

export function getShadowOverview(signal?: AbortSignal): Promise<ShadowOverview> {
  return apiRequest("/shadow/overview", { signal });
}

export function getShadowLive(signal?: AbortSignal): Promise<ShadowLiveResponse> {
  return apiRequest("/shadow/live", { signal });
}

export function getShadowDailyOperations(signal?: AbortSignal): Promise<ShadowDailyOperations> {
  return apiRequest("/shadow/daily-operations", { signal });
}

export function listShadowPortfolios(signal?: AbortSignal): Promise<ShadowPortfolioSummary[]> {
  return apiRequest("/shadow/portfolios", { signal });
}

export function getShadowPortfolio(id: string | number, signal?: AbortSignal): Promise<ShadowPortfolioSummary> {
  return apiRequest(`/shadow/portfolios/${encodeURIComponent(String(id))}`, { signal });
}

export function getShadowOrders(id: string | number, signal?: AbortSignal): Promise<ShadowOrder[]> {
  return apiRequest(`/shadow/portfolios/${encodeURIComponent(String(id))}/orders`, { signal });
}

export function getShadowFills(id: string | number, signal?: AbortSignal): Promise<ShadowFill[]> {
  return apiRequest(`/shadow/portfolios/${encodeURIComponent(String(id))}/fills`, { signal });
}

export function getShadowNav(id: string | number, signal?: AbortSignal): Promise<ShadowNavPoint[]> {
  return apiRequest(`/shadow/portfolios/${encodeURIComponent(String(id))}/nav`, { signal });
}

export function getShadowDecisions(id: string | number, signal?: AbortSignal): Promise<ShadowDecision[]> {
  return apiRequest(`/shadow/portfolios/${encodeURIComponent(String(id))}/decisions`, { signal });
}
