/** Forward Signal V0 API client. */

import { apiRequest } from "./client";

export interface ForwardBatchSummary {
  id: string;
  as_of_date: string;
  segment: string;
  status: string;
  candidate_name: string;
  candidate_version: string;
  candidate_config_hash: string;
  feature_schema_hash: string;
  prediction_hash?: string | null;
  eligible_count: number;
  ineligible_count: number;
  prediction_count: number;
  pit_status: string;
  generated_at?: string | null;
  completed_at?: string | null;
}

export interface ForwardPredictionItem {
  instrument_id: number;
  ticker: string;
  as_of_date: string;
  predicted_return_20d: number;
  rank?: number | null;
  eligible_count?: number | null;
  percentile?: number | null;
  quality_status: string;
  outcome_status: string;
  candidate_config_hash: string;
  generated_at?: string | null;
}

export interface ForwardBatchDetail {
  batch: ForwardBatchSummary;
  predictions: ForwardPredictionItem[];
  input_lineage?: Record<string, unknown> | null;
  completeness?: Record<string, unknown> | null;
  timings?: Record<string, unknown> | null;
}

export function getLatestForwardBatch(signal?: AbortSignal): Promise<ForwardBatchDetail> {
  return apiRequest("/predictions/forward/latest", { signal });
}

export function listForwardBatches(limit = 50, signal?: AbortSignal): Promise<ForwardBatchSummary[]> {
  return apiRequest(`/predictions/forward?limit=${limit}`, { signal });
}

export function getForwardBatch(batchId: string | number, signal?: AbortSignal): Promise<ForwardBatchDetail> {
  return apiRequest(`/predictions/forward/${encodeURIComponent(String(batchId))}`, { signal });
}
