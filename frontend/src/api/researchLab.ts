import { apiRequest, queryString } from "./client";
import type { SimulationMetrics, SimulationRunSummary, SimulationSpecSummary } from "./simulator";

/** Research Lab V0 — historical experiments over frozen Prediction Candidates. */

export interface CandidateOption {
  id: string;
  candidate_name: string;
  candidate_version: string;
  human_name: string;
  technical_line: string;
  research_verdict: string;
  model_type: string;
  target_label: string;
  /** EXPECTED_RETURN | RANKING_SCORE */
  prediction_semantic?: string;
  /** Human output label, e.g. «Рейтинговый балл». */
  output_label?: string;
  eligible: boolean;
  help_id?: string;
}

export interface PredictionSegmentOption {
  id: string;
  human_label: string;
  launchable: boolean;
  help_id?: string;
  date_from?: string | null;
  date_to?: string | null;
  badge?: string | null;
  explanation?: string | null;
  holdout_start?: string | null;
}

export interface StrategyOption {
  id: string;
  technical_id: string;
  human_name: string;
  description: string;
  parameters: Record<string, unknown>;
  help_id?: string;
  frozen?: boolean;
}

export interface CostPresetOption {
  bps: number;
  human_label: string;
  preset: boolean;
  help_id?: string;
}

export interface CostCustomOption {
  allowed: boolean;
  min_bps: number;
  max_bps: number;
  human_label: string;
  help_id?: string;
  friction_model?: string;
}

export interface ResearchDefaults {
  candidate_id: string;
  segment: string;
  policy_id: string;
  risk_id: string;
  commission_bps: number;
  initial_capital: number;
  date_from?: string | null;
  date_to?: string | null;
}

export interface ExecutionAssumptions {
  execution?: string;
  fractional_shares?: boolean;
  dividends?: string;
  benchmark?: string;
  no_leverage?: boolean;
  editable_in_lab?: boolean;
  [key: string]: unknown;
}

export interface ResearchOptions {
  candidates: CandidateOption[];
  prediction_segments: PredictionSegmentOption[];
  policies: StrategyOption[];
  risk_policies: StrategyOption[];
  cost_presets: CostPresetOption[];
  cost_custom: CostCustomOption;
  defaults: ResearchDefaults;
  capital_bounds: { min: number; max: number };
  execution_assumptions: ExecutionAssumptions;
  period_warnings?: { short_calendar_days?: number; min_trading_days_soft?: number };
  quick_suite?: {
    label: string;
    variants: Array<{ policy_id: string; risk_id: string }>;
    costs_bps: number[];
    max_configs: number;
  };
  prediction_ready?: Record<string, unknown> | null;
  holdout_start?: string | null;
}

/** research block appended by backend enrich_run_summary. */
export interface ResearchContext {
  display_name: string;
  note?: string | null;
  created_from?: string | null;
  requested_date_from?: string | null;
  requested_date_to?: string | null;
  observed_holdout: boolean;
  launchable_again: boolean;
  context?: string | null;
  cost_family_fingerprint?: string | null;
}

export interface ResearchSpecSummary extends SimulationSpecSummary {
  risk_name?: string | null;
}

export interface ResearchRunSummary extends Omit<SimulationRunSummary, "spec"> {
  spec?: ResearchSpecSummary | null;
  research?: ResearchContext | null;
  nav_preview?: { points: number; from?: string | null; to?: string | null } | null;
}

export interface LaunchRequest {
  candidate_id: string;
  segment: string;
  policy_id: string;
  risk_id: string;
  commission_bps: number;
  date_from?: string | null;
  date_to?: string | null;
  initial_capital: number;
  name?: string | null;
  note?: string | null;
  force_rerun?: boolean;
}

export type LaunchOutcome = "REUSE_EXISTING" | "CREATED";

export interface LaunchResponse {
  outcome: LaunchOutcome;
  status: string;
  message: string;
  run: ResearchRunSummary;
  config_hash?: string | null;
  cost_family_fingerprint?: string | null;
  warnings?: string[];
  simulation_executed: boolean;
  metrics?: SimulationMetrics | null;
}

export interface CompareDifference {
  field: string;
  human: string;
  values: Record<string, unknown>;
}

export interface CompareMetricRow {
  metric_id: string;
  human_label: string;
  help_id: string;
  values: Record<string, number | null>;
}

export interface CompareNavPoint {
  date: string;
  nav: number;
  drawdown: number;
  nav_normalized: number;
}

export interface CostFamilyCell {
  run_id: number;
  total_price_return?: number | null;
  max_drawdown?: number | null;
  turnover_ratio?: number | null;
  sharpe_rf0?: number | null;
}

export interface CostFamilyRow {
  policy_name?: string | null;
  risk_name?: string | null;
  segment?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  candidate_config_hash?: string | null;
  cells: Record<string, CostFamilyCell>;
}

export interface CostFamily {
  present: boolean;
  message: string;
  matrix?: CostFamilyRow[] | null;
}

export interface CompareResponse {
  runs: ResearchRunSummary[];
  fair_comparison: boolean;
  fair_badge: string;
  /** true when fair and candidate hashes differ (model A/B). */
  model_comparison?: boolean;
  differences: CompareDifference[];
  metrics_table: CompareMetricRow[];
  interpretation: string[];
  observed_holdout_warning?: string | null;
  cost_family: CostFamily;
  nav_series: Record<string, CompareNavPoint[]>;
  normalization?: string;
  period_aligned: boolean;
}

export interface SuiteRequest {
  candidate_id?: string;
  date_from?: string | null;
  date_to?: string | null;
  initial_capital?: number;
}

export interface SuitePlanItem {
  policy_id: string;
  risk_id: string;
  commission_bps: number;
  config_hash: string;
  exists: boolean;
  existing_run_id?: number | null;
}

export interface SuitePlanResponse {
  label: string;
  total: number;
  already_exist: number;
  will_run: number;
  items: SuitePlanItem[];
  not_optimization: boolean;
}

export interface SuiteRunResponse {
  label: string;
  total: number;
  already_exist: number;
  created: number;
  reused: number;
  runs: ResearchRunSummary[];
  not_optimization: boolean;
  message: string;
}

export interface ResearchRunFilters {
  limit?: number;
  policy_id?: string;
  risk_id?: string;
  status?: string;
  segment?: string;
  commission_bps?: number;
  sort?: string;
}

export function getResearchOptions(signal?: AbortSignal): Promise<ResearchOptions> {
  return apiRequest("/research-lab/options", { signal });
}

export async function listResearchRuns(
  filters: ResearchRunFilters = {},
  signal?: AbortSignal,
): Promise<ResearchRunSummary[]> {
  const response = await apiRequest<{ items: ResearchRunSummary[] }>(
    `/research-lab/runs${queryString({
      limit: filters.limit ?? 100,
      policy_id: filters.policy_id,
      risk_id: filters.risk_id,
      status: filters.status,
      segment: filters.segment,
      commission_bps: filters.commission_bps,
      sort: filters.sort,
    })}`,
    { signal },
  );
  return response.items ?? [];
}

export function getResearchRun(
  runId: number | string,
  signal?: AbortSignal,
): Promise<ResearchRunSummary> {
  return apiRequest(`/research-lab/runs/${encodeURIComponent(String(runId))}`, { signal });
}

export function launchResearchRun(
  body: LaunchRequest,
  signal?: AbortSignal,
): Promise<LaunchResponse> {
  return apiRequest("/research-lab/runs", { method: "POST", body, signal });
}

export function compareResearchRuns(
  runIds: Array<number | string>,
  signal?: AbortSignal,
): Promise<CompareResponse> {
  return apiRequest(`/research-lab/compare${queryString({ run_ids: runIds.join(",") })}`, {
    signal,
  });
}

export function planQuickSuite(
  body: SuiteRequest = {},
  signal?: AbortSignal,
): Promise<SuitePlanResponse> {
  return apiRequest("/research-lab/suites/plan", { method: "POST", body, signal });
}

export function runQuickSuite(
  body: SuiteRequest = {},
  signal?: AbortSignal,
): Promise<SuiteRunResponse> {
  return apiRequest("/research-lab/suites", { method: "POST", body, signal });
}
