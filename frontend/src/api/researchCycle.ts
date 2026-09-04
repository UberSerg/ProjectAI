/** Daily Research Cycle V0 API client. */

import { apiRequest, queryString } from "./client";

export interface ResearchCycleStep {
  name: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
}

export interface ResearchCycleRun {
  id: string;
  name: string;
  workflow_type: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  meta?: Record<string, unknown> | null;
  steps: ResearchCycleStep[];
}

export interface ResearchCycleBrief {
  id: number;
  name: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  market_watermark_before?: string | null;
  market_watermark_after?: string | null;
  latest_forward_batch_id?: number | null;
  health?: string | null;
  duration_seconds?: number | null;
  step_results?: Record<string, unknown> | null;
}

export interface ShadowPortfolioWatermark {
  id: number;
  status: string;
  last_processed_market_date?: string | null;
  cash?: number | null;
  peak_nav?: number | null;
}

export interface ResearchCycleWatermarks {
  raw_market_latest_date?: string | null;
  analytics_v2_latest_date?: string | null;
  technical_v2_latest_date?: string | null;
  relations_v2_latest_as_of?: string | null;
  forward_latest_as_of?: string | null;
  forward_latest_generated_at?: string | null;
  forward_latest_batch_id?: number | null;
  shadow_portfolios?: ShadowPortfolioWatermark[];
  forward_outcome_latest_status?: string | null;
  forward_outcome_latest_evaluated_at?: string | null;
  max_relation_age_days?: number;
  technical_model_pin?: { code: string; version: number | string } | null;
}

export interface OutcomeMaturity {
  batch_id: number;
  as_of: string;
  future_trading_observations: number;
  required: number;
  status: string;
  matured: boolean;
}

export interface ResearchCycleSchedule {
  enabled: boolean;
  hour: number;
  minute: number;
  timezone: string;
}

export interface ResearchCycleOperationalStatus {
  health: string;
  health_human: string;
  watermarks: ResearchCycleWatermarks;
  latest_cycle: ResearchCycleBrief | null;
  schedule: ResearchCycleSchedule;
  outcome_maturity: OutcomeMaturity | null;
  automatic_schedule: "enabled" | "disabled" | string;
}

export interface ResearchCycleLatestResponse {
  run: ResearchCycleRun | null;
  operational: ResearchCycleOperationalStatus;
}

export interface ResearchCycleRunsResponse {
  items: ResearchCycleRun[];
}

export function getResearchCycleStatus(
  signal?: AbortSignal,
): Promise<ResearchCycleOperationalStatus> {
  return apiRequest("/research-cycle/status", { signal });
}

export function getResearchCycleLatest(
  signal?: AbortSignal,
): Promise<ResearchCycleLatestResponse> {
  return apiRequest("/research-cycle/latest", { signal });
}

export function getResearchCycleRuns(
  limit = 20,
  signal?: AbortSignal,
): Promise<ResearchCycleRunsResponse> {
  return apiRequest(`/research-cycle/runs${queryString({ limit })}`, { signal });
}
