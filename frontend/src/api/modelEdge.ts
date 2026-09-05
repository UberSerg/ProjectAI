/**
 * Model Edge Research Pack V0 — diagnostics + prospective A/B API client.
 *
 * Assumed response shapes (backend may add fields; UI uses optional chaining):
 *
 * GET /model-diagnostics/summary
 *   { models: { v0?: ModelSummary, v1?: ModelSummary }, conclusion?: string,
 *     human_summary?: string, learned?: string[] }
 *   ModelSummary: { rank_ic?, top20_spread?, stability?, cagr?, max_drawdown?,
 *     turnover_ratio?, excess_vs_cash?, human_label? }
 *
 * GET /model-diagnostics/top-tail
 *   { rows: TopTailRow[] }  — quantile 0.05|0.10|0.20|0.30
 *
 * GET /model-diagnostics/stability
 *   { week_to_week_correlation?, avg_rank_movement?, top20_persistence?,
 *     top35_persistence?, entry_churn?, exit_churn?, by_model?: Record }
 *
 * GET /model-diagnostics/regimes
 *   { rows: RegimeRow[] }
 *
 * GET /model-diagnostics/disagreements?as_of=
 *   { as_of?, dates?: string[], rows: DisagreementRow[],
 *     human_example?: string }
 *
 * GET /model-diagnostics/economic-viability?annual_rate=0.10
 *   { annual_rate, cash_hurdle_mutates_portfolio?: false, cells?: EconomicCell[],
 *     models?: Record<string, { cagr?, excess_vs_cash?, max_drawdown?,
 *       hurdle_return?, conclusion? }> }
 *
 * GET /model-experiments/prospective/latest
 *   experiment status + portfolio snapshots + pipeline flags + agreement
 *
 * GET /model-experiments/prospective/batches
 *   { items: ProspectiveBatchSummary[] }
 *
 * GET /model-experiments/prospective/batches/{id}
 *   batch detail + prediction rows (V0 expected return %, V1 ranking score raw)
 *
 * GET /model-experiments/prospective/evaluation
 *   { mature_dates?, sample_maturity?, metrics?, conclusion? }
 */
import { apiRequest, queryString } from "./client";

export interface ModelSummaryCard {
  human_label?: string | null;
  rank_ic?: number | null;
  top20_spread?: number | null;
  top20_realized?: number | null;
  stability?: number | null;
  rank_stability?: number | null;
  cagr?: number | null;
  max_drawdown?: number | null;
  turnover_ratio?: number | null;
  excess_vs_cash?: number | null;
  [key: string]: unknown;
}

export interface DiagnosticsSummary {
  models?: {
    v0?: ModelSummaryCard;
    v1?: ModelSummaryCard;
    V0?: ModelSummaryCard;
    V1?: ModelSummaryCard;
    [key: string]: ModelSummaryCard | undefined;
  };
  conclusion?: string | null;
  human_summary?: string | null;
  learned?: string[] | null;
  what_we_learned?: string[] | null;
  [key: string]: unknown;
}

export interface TopTailRow {
  quantile?: number | null;
  label?: string | null;
  v0_realized_return?: number | null;
  v1_realized_return?: number | null;
  v0_hit_rate?: number | null;
  v1_hit_rate?: number | null;
  v0_loser_contamination?: number | null;
  v1_loser_contamination?: number | null;
  [key: string]: unknown;
}

export interface TopTailResponse {
  rows?: TopTailRow[];
  items?: TopTailRow[];
  [key: string]: unknown;
}

export interface StabilityMetrics {
  week_to_week_correlation?: number | null;
  avg_rank_movement?: number | null;
  top20_persistence?: number | null;
  top35_persistence?: number | null;
  entry_churn?: number | null;
  exit_churn?: number | null;
  by_model?: Record<string, StabilityMetrics>;
  v0?: StabilityMetrics;
  v1?: StabilityMetrics;
  [key: string]: unknown;
}

export interface RegimeRow {
  regime?: string | null;
  year?: number | string | null;
  label?: string | null;
  v0_rank_ic?: number | null;
  v1_rank_ic?: number | null;
  v0_top20?: number | null;
  v1_top20?: number | null;
  v0_portfolio_result?: number | null;
  v1_portfolio_result?: number | null;
  observations?: number | null;
  [key: string]: unknown;
}

export interface RegimesResponse {
  rows?: RegimeRow[];
  items?: RegimeRow[];
  [key: string]: unknown;
}

export interface DisagreementRow {
  ticker?: string | null;
  instrument_id?: string | number | null;
  v0_rank?: number | null;
  v1_rank?: number | null;
  rank_delta?: number | null;
  v0_selected?: boolean | null;
  v1_selected?: boolean | null;
  realized_20d?: number | null;
  portfolio_contribution?: number | null;
  [key: string]: unknown;
}

export interface DisagreementsResponse {
  as_of?: string | null;
  dates?: string[];
  rows?: DisagreementRow[];
  items?: DisagreementRow[];
  human_example?: string | null;
  [key: string]: unknown;
}

export interface EconomicViabilityModel {
  cagr?: number | null;
  total_price_return?: number | null;
  excess_vs_cash?: number | null;
  max_drawdown?: number | null;
  hurdle_return?: number | null;
  annual_rate?: number | null;
  conclusion?: string | null;
  [key: string]: unknown;
}

export interface EconomicViabilityResponse {
  annual_rate?: number;
  cash_hurdle_annual_rate?: number;
  cash_hurdle_mutates_portfolio?: boolean;
  models?: Record<string, EconomicViabilityModel>;
  cells?: Array<Record<string, unknown>>;
  conclusion?: string | null;
  [key: string]: unknown;
}

export interface ProspectivePipeline {
  experiment_activated?: boolean;
  new_market_data?: boolean;
  paired_predictions?: boolean;
  strategy_decision?: boolean;
  future_open?: boolean;
  execution?: boolean;
  twenty_observations?: boolean;
  model_evaluation?: boolean;
  /** Alternative flat list of completed stage ids. */
  completed?: string[];
  [key: string]: unknown;
}

export interface ProspectivePortfolioSnap {
  name?: string | null;
  human_name?: string | null;
  nav?: number | null;
  cash?: number | null;
  drawdown?: number | null;
  max_drawdown?: number | null;
  turnover_ratio?: number | null;
  trade_count?: number | null;
  [key: string]: unknown;
}

export interface ProspectiveAgreement {
  rank_correlation?: number | null;
  top20_overlap?: number | null;
  top1_agreement?: boolean | null;
  selected_overlap?: number | null;
  [key: string]: unknown;
}

export interface ProspectiveLatest {
  experiment?: {
    code?: string;
    human_name?: string;
    status?: string;
    activated_at?: string | null;
    activation_market_watermark?: string | null;
    [key: string]: unknown;
  } | null;
  status?: string | null;
  activated_at?: string | null;
  pipeline?: ProspectivePipeline | null;
  portfolio_a?: ProspectivePortfolioSnap | null;
  portfolio_b?: ProspectivePortfolioSnap | null;
  portfolios?: {
    v0?: ProspectivePortfolioSnap;
    v1?: ProspectivePortfolioSnap;
    a?: ProspectivePortfolioSnap;
    b?: ProspectivePortfolioSnap;
  };
  agreement?: ProspectiveAgreement | null;
  batch_count?: number | null;
  fill_count?: number | null;
  mature_outcome_count?: number | null;
  paired_prediction_count?: number | null;
  [key: string]: unknown;
}

export interface ProspectiveBatchSummary {
  id: number | string;
  as_of_date?: string | null;
  status?: string | null;
  comparability_status?: string | null;
  rank_correlation?: number | null;
  top20_overlap?: number | null;
  [key: string]: unknown;
}

export interface ProspectiveBatchesResponse {
  items?: ProspectiveBatchSummary[];
  batches?: ProspectiveBatchSummary[];
  [key: string]: unknown;
}

export interface ProspectivePredictionRow {
  ticker?: string | null;
  instrument_id?: string | number | null;
  v0_expected_return?: number | null;
  v0_rank?: number | null;
  v1_ranking_score?: number | null;
  v1_rank?: number | null;
  rank_delta?: number | null;
  v0_selected?: boolean | null;
  v1_selected?: boolean | null;
  state?: string | null;
  /** Never format as % when semantic is RANKING_SCORE. */
  prediction_semantic_a?: string | null;
  prediction_semantic_b?: string | null;
  [key: string]: unknown;
}

export interface ProspectiveBatchDetail extends ProspectiveBatchSummary {
  predictions?: ProspectivePredictionRow[];
  rows?: ProspectivePredictionRow[];
  agreement?: ProspectiveAgreement | null;
  [key: string]: unknown;
}

export interface ProspectiveEvaluation {
  mature_dates?: number | null;
  mature_count?: number | null;
  sample_maturity?: string | null;
  metrics?: Record<string, unknown> | null;
  conclusion?: string | null;
  [key: string]: unknown;
}

export function getDiagnosticsSummary(signal?: AbortSignal): Promise<DiagnosticsSummary> {
  return apiRequest("/model-diagnostics/summary", { signal });
}

export function getDiagnosticsTopTail(signal?: AbortSignal): Promise<TopTailResponse> {
  return apiRequest("/model-diagnostics/top-tail", { signal });
}

export function getDiagnosticsStability(signal?: AbortSignal): Promise<StabilityMetrics> {
  return apiRequest("/model-diagnostics/stability", { signal });
}

export function getDiagnosticsRegimes(signal?: AbortSignal): Promise<RegimesResponse> {
  return apiRequest("/model-diagnostics/regimes", { signal });
}

export function getDiagnosticsDisagreements(
  asOf?: string | null,
  signal?: AbortSignal,
): Promise<DisagreementsResponse> {
  return apiRequest(
    `/model-diagnostics/disagreements${queryString({ as_of: asOf ?? undefined })}`,
    { signal },
  );
}

export function getEconomicViability(
  annualRate = 0.1,
  signal?: AbortSignal,
): Promise<EconomicViabilityResponse> {
  return apiRequest(
    `/model-diagnostics/economic-viability${queryString({ annual_rate: annualRate })}`,
    { signal },
  );
}

export function getProspectiveLatest(signal?: AbortSignal): Promise<ProspectiveLatest> {
  return apiRequest("/model-experiments/prospective/latest", { signal });
}

export async function listProspectiveBatches(
  signal?: AbortSignal,
): Promise<ProspectiveBatchSummary[]> {
  const response = await apiRequest<ProspectiveBatchesResponse>(
    "/model-experiments/prospective/batches",
    { signal },
  );
  return response.items ?? response.batches ?? [];
}

export function getProspectiveBatch(
  id: number | string,
  signal?: AbortSignal,
): Promise<ProspectiveBatchDetail> {
  return apiRequest(`/model-experiments/prospective/batches/${encodeURIComponent(String(id))}`, {
    signal,
  });
}

export function getProspectiveEvaluation(signal?: AbortSignal): Promise<ProspectiveEvaluation> {
  return apiRequest("/model-experiments/prospective/evaluation", { signal });
}

/** Pick V0/V1 summary cards from a loosely-shaped summary payload. */
export function pickModelCards(summary: DiagnosticsSummary | null | undefined): {
  v0: ModelSummaryCard | undefined;
  v1: ModelSummaryCard | undefined;
} {
  const models = summary?.models ?? {};
  return {
    v0: models.v0 ?? models.V0,
    v1: models.v1 ?? models.V1,
  };
}
