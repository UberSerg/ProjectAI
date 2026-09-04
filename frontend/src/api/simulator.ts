import { apiRequest, queryString } from "./client";

/** Simulation segment codes from backend. */
export type SimulationSegment = "DEVELOPMENT_OOS" | "FINAL_HOLDOUT" | string;

export interface SimulationSpecSummary {
  config_hash?: string | null;
  policy_name?: string | null;
  commission_bps?: number | null;
  slippage_bps?: number | null;
  cost_sensitivity_label?: string | null;
  top_quantile?: number | null;
  rebalance?: string | null;
  execution_timing?: string | null;
  initial_capital?: number | null;
  fractional_shares?: boolean | null;
  dividend_cash?: boolean | null;
  candidate_name?: string | null;
  candidate_version?: string | null;
}

export interface SimulationMetrics {
  initial_nav?: number | null;
  final_nav?: number | null;
  total_price_return?: number | null;
  cagr?: number | null;
  annualized_volatility?: number | null;
  sharpe_rf0?: number | null;
  sharpe_note?: string | null;
  max_drawdown?: number | null;
  max_drawdown_peak_date?: string | null;
  max_drawdown_trough_date?: string | null;
  max_drawdown_recovery_date?: string | null;
  turnover_notional?: number | null;
  turnover_ratio?: number | null;
  trade_count?: number | null;
  rebalance_count?: number | null;
  average_gross_exposure?: number | null;
  average_cash_weight?: number | null;
  trading_days?: number | null;
  excess_vs_imoex?: number | null;
  return_type?: string | null;
  research_result?: string | null;
  [key: string]: unknown;
}

export interface SimulationBenchmark {
  benchmark_type?: string | null;
  total_price_return?: number | null;
  [key: string]: unknown;
}

export interface SimulationRunSummary {
  id: number;
  status: string;
  engineering_status?: string | null;
  research_result?: string | null;
  segment: SimulationSegment;
  date_from?: string | null;
  date_to?: string | null;
  candidate_config_hash?: string | null;
  dataset_values_hash?: string | null;
  prediction_hash?: string | null;
  values_hash?: string | null;
  metrics?: SimulationMetrics | null;
  benchmark?: SimulationBenchmark | null;
  provenance?: Record<string, unknown> | null;
  created_at?: string | null;
  spec?: SimulationSpecSummary | null;
}

export interface NavPoint {
  date: string;
  nav: number;
  cash: number;
  gross_exposure: number;
  cash_weight: number;
  peak_nav: number;
  drawdown: number;
}

export interface BenchmarkPoint {
  date: string;
  close: number;
}

export interface NavSeriesResponse {
  run_id: number;
  benchmark?: SimulationBenchmark | null;
  benchmark_series: BenchmarkPoint[];
  rebalance_dates: string[];
  date_from?: string | null;
  date_to?: string | null;
  items: NavPoint[];
}

export interface DayPosition {
  instrument_id: number;
  ticker: string;
  quantity: number;
  market_price?: number | null;
  market_value?: number | null;
  weight?: number | null;
}

export interface DayOrder {
  decision_date: string;
  execution_date: string;
  instrument_id: number;
  ticker: string;
  side: string;
  target_weight?: number | null;
  quantity?: number | null;
  predicted_return_20d?: number | null;
  rank?: number | null;
  policy_name?: string | null;
  prediction_date?: string | null;
  fold_id?: string | null;
  reason?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface DayFill {
  execution_date: string;
  decision_date?: string | null;
  instrument_id: number;
  ticker: string;
  side: string;
  quantity: number;
  raw_open?: number | null;
  fill_price?: number | null;
  notional?: number | null;
  commission?: number | null;
  slippage_cost?: number | null;
}

export interface DayInspectorResponse {
  run_id: number;
  as_of: string;
  nav: {
    nav: number;
    cash: number;
    gross_exposure: number;
    cash_weight: number;
    peak_nav: number;
    drawdown: number;
    positions_count: number;
  } | null;
  rebalance: boolean;
  positions: DayPosition[];
  orders: DayOrder[];
  fills: DayFill[];
}

export interface CostSensitivityItem {
  run_id: number;
  commission_bps?: number | null;
  slippage_bps?: number | null;
  cost_sensitivity_label?: string | null;
  total_price_return?: number | null;
  final_nav?: number | null;
  max_drawdown?: number | null;
  is_current: boolean;
}

export interface CostSensitivityResponse {
  run_id: number;
  segment?: string | null;
  items: CostSensitivityItem[];
}

export interface SimulationFill extends DayFill {
  prediction_date?: string | null;
  predicted_return_20d?: number | null;
  rank?: number | null;
  policy_name?: string | null;
  target_weight?: number | null;
  fold_id?: string | null;
  reason?: string | null;
  eligible_count?: number | null;
  display_name?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface SimulationOrder {
  decision_date: string;
  execution_date: string;
  instrument_id: number;
  ticker: string;
  side: string;
  target_weight?: number | null;
  target_notional?: number | null;
  quantity?: number | null;
  reason?: string | null;
  prediction_date?: string | null;
  predicted_return_20d?: number | null;
  rank?: number | null;
  policy_name?: string | null;
  fold_id?: string | null;
  metadata?: Record<string, unknown> | null;
}

export async function listSimulatorRuns(limit = 50, signal?: AbortSignal): Promise<SimulationRunSummary[]> {
  const response = await apiRequest<{ items: SimulationRunSummary[] }>(
    `/simulator/runs${queryString({ limit })}`,
    { signal },
  );
  return response.items ?? [];
}

export function getSimulatorRun(runId: number | string, signal?: AbortSignal): Promise<SimulationRunSummary> {
  return apiRequest(`/simulator/runs/${encodeURIComponent(String(runId))}`, { signal });
}

export function getSimulatorNav(runId: number | string, signal?: AbortSignal): Promise<NavSeriesResponse> {
  return apiRequest(`/simulator/runs/${encodeURIComponent(String(runId))}/nav`, { signal });
}

export function getSimulatorDay(
  runId: number | string,
  asOf: string,
  signal?: AbortSignal,
): Promise<DayInspectorResponse> {
  return apiRequest(
    `/simulator/runs/${encodeURIComponent(String(runId))}/day${queryString({ as_of: asOf })}`,
    { signal },
  );
}

export function getSimulatorCostSensitivity(
  runId: number | string,
  signal?: AbortSignal,
): Promise<CostSensitivityResponse> {
  return apiRequest(`/simulator/runs/${encodeURIComponent(String(runId))}/cost-sensitivity`, { signal });
}

export async function getSimulatorFills(
  runId: number | string,
  signal?: AbortSignal,
): Promise<SimulationFill[]> {
  const response = await apiRequest<{ items: SimulationFill[] }>(
    `/simulator/runs/${encodeURIComponent(String(runId))}/fills`,
    { signal },
  );
  return response.items ?? [];
}

export async function getSimulatorOrders(
  runId: number | string,
  signal?: AbortSignal,
): Promise<SimulationOrder[]> {
  const response = await apiRequest<{ items: SimulationOrder[] }>(
    `/simulator/runs/${encodeURIComponent(String(runId))}/orders`,
    { signal },
  );
  return response.items ?? [];
}

export async function getSimulatorPositions(
  runId: number | string,
  asOf: string,
  signal?: AbortSignal,
): Promise<DayPosition[]> {
  const response = await apiRequest<{ items: DayPosition[] }>(
    `/simulator/runs/${encodeURIComponent(String(runId))}/positions${queryString({ as_of: asOf })}`,
    { signal },
  );
  return response.items ?? [];
}
